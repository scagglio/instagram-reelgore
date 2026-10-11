"""Entry point.

  python -m reelgore.main plan     --type auto      # pick movies + write copy + render slides
  python -m reelgore.main publish  --base-url URL   # post rendered slides from out/ to Instagram
  python -m reelgore.main demo                       # offline render with sample data (no API keys)
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

import yaml

OUT = Path("out")


def load_cfg() -> dict:
    return yaml.safe_load(Path("config/brand.yaml").read_text())


def cmd_plan(args):
    from .picker import parse_titles, pick, pick_custom, pick_person
    from .render import Renderer
    from .tmdb import TMDB
    from .writer import caption_text, write_copy

    cfg = load_cfg()
    if os.environ.get("DRY_RUN", "false").lower() != "true":
        require_no_cooldown()
    person_name = (os.environ.get("PERSON") or "").strip()
    if any(sep in person_name for sep in (",", ";", " and ", " & ")):
        raise SystemExit("The person box takes ONE name per post. Run once per person.")
    tmdb = TMDB()
    titles = parse_titles(os.environ.get("MOVIES", ""))
    if person_name:
        print(f"[plan] person spotlight from the manual run: {person_name}")
        plan = pick_person(tmdb, person_name)
    elif titles:
        print(f"[plan] custom list from the manual run: {titles}")
        plan = pick_custom(tmdb, titles, os.environ.get("LIST_TITLE", ""))
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a") as f:
                f.write("### Your movies\n\n" + "\n".join(
                    f"- {m['title']} ({(m.get('release_date') or '????')[:4]})" for m in plan["movies"]) + "\n")
                if plan["missing"]:
                    f.write("\n> **Not found on TMDB, skipped:** " + ", ".join(plan["missing"]) +
                            ". Check the spelling or add the year, e.g. `The Thing (1982)`.\n")
    else:
        plan = pick(tmdb, cfg, forced=args.type)
    print(f"[plan] {plan['kind']}: {[m['title'] for m in plan['movies']]}")
    plan["series"] = active_series(cfg)
    if plan["series"]:
        print(f"[series] {plan['series']['name']}: night {plan['series']['n']}/{plan['series']['total']}")
    from .writer import TRIVIA_KINDS
    if plan["kind"] in TRIVIA_KINDS:
        from .wiki import trivia_notes
        try:
            if plan.get("person"):
                pp = plan["person"]
                plan["trivia_notes"] = trivia_notes({"title": pp["name"], "wikidata_id": pp.get("wikidata_id")},
                                                    person=True)
            else:
                plan["trivia_notes"] = trivia_notes(plan["movies"][0])
        except Exception as e:
            print(f"[trivia] Wikipedia lookup failed: {e}")
        if not plan.get("trivia_notes"):
            print("[trivia] no Wikipedia notes; trivia will use TMDB facts only")
    copy = write_copy(plan, cfg)
    plan.pop("trivia_notes", None)  # don't store the article text in plan.json/history
    if plan["series"]:
        tag = plan["series"]["hashtag"]
        copy["hashtags"] = [tag] + [h for h in copy["hashtags"] if h.lower() != tag.lower()]
        copy["hashtags"] = copy["hashtags"][: cfg["hashtags"]["max_total"]]
    add_watch_slide(tmdb, plan, copy, cfg)
    plan["copy"] = copy
    plan["caption"] = caption_text(copy, plan, extra=plan.get("watch_line"))

    def fetch(path):
        try:
            return tmdb.download(path, "w1280")
        except Exception:
            return None

    OUT.mkdir(exist_ok=True)
    renderer = Renderer(cfg, fetch)
    paths = renderer.render_all(plan, copy, OUT)
    plan["slides"] = [p.name for p in paths]

    if os.environ.get("POST_REEL", "true").lower() != "false":
        from .video import build_reel
        reel_slides = renderer.render_all(plan, copy, OUT / "reel_frames", swipe=False)
        seed = int(date.today().strftime("%Y%m%d"))
        build_reel(reel_slides, copy, OUT / "reel.mp4", seed)
        plan["reel"] = "reel.mp4"
    if cfg.get("stories", {}).get("enabled", True) and os.environ.get("POST_STORY", "true").lower() != "false":
        renderer.story_image(paths[0], plan, OUT / "story.jpg")
        plan["story"] = "story.jpg"
        print("[plan] story image rendered -> out/story.jpg")
    (OUT / "plan.json").write_text(json.dumps(plan, indent=2))
    (OUT / "caption.txt").write_text(plan["caption"])
    print(f"[plan] rendered {len(paths)} slides -> {OUT}/")
    print(plan["caption"])


def central_today() -> date:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/Chicago")).date()


def active_series(cfg: dict, today: date | None = None) -> dict | None:
    """Return the running seasonal series (e.g. 31 Nights of Horror) with today's night number."""
    today = today or central_today()
    for s in cfg.get("series", []) or []:
        sm, sd = map(int, s["start"].split("-"))
        em, ed = map(int, s["end"].split("-"))
        start, end = date(today.year, sm, sd), date(today.year, em, ed)
        if start <= today <= end:
            return {"name": s["name"], "hashtag": s["hashtag"], "badge": s.get("badge", "NIGHT {n:02d}/{total}"),
                    "n": (today - start).days + 1, "total": (end - start).days + 1}
    return None


def add_watch_slide(tmdb, plan: dict, copy: dict, cfg: dict) -> None:
    """Insert a 'where to watch / own it' slide before the CTA for released films."""
    acfg = cfg.get("affiliate", {})
    types = acfg.get("post_types", ["classic", "anniversary"]) + ["pick"]
    if not acfg.get("enabled", True) or plan["kind"] not in types:
        return
    from .affiliate import build_watch, ig_caption_line, watch_slide
    watch = build_watch(tmdb, plan["movies"][0], cfg)
    if not watch:
        print("[affiliate] no streaming or shop links for this film; skipping the slide")
        return
    plan["watch"] = watch
    plan["watch_line"] = ig_caption_line(watch, cfg)
    slides = copy["slides"]
    max_body = plan.get("_count_max", cfg["slides"]["count_max"]) - 1
    cta_at = next((i for i, sl in enumerate(slides) if sl.get("type") == "cta"), len(slides))
    slides.insert(cta_at, watch_slide(watch))
    while len(slides) > max_body:  # stay within the slide limit: drop a middle text slide
        drop = next((i for i, sl in enumerate(slides) if sl.get("type") == "text"), None)
        if drop is None:
            break
        slides.pop(drop)
    print(f"[affiliate] watch slide added: stream={[p['name'] for p in watch['stream']]} own={len(watch['own'])} links")


COOLDOWN = Path("data/cooldown.json")


def is_action_block(err: Exception) -> bool:
    """Instagram's anti-spam 'Action is blocked' (code 4 / subcode 2207051) or similar rate limits."""
    t = str(err)
    return any(k in t for k in ('"error_subcode":2207051', "Action is blocked", "Application request limit reached",
                                '"code":4,', '"code":32,', '"code":613,'))


def start_cooldown(err: Exception) -> None:
    """Pause posting after an Instagram action block. Repeat blocks escalate the pause (1, 2, 4, then 7 days),
    and every pause ends at 5 PM Central so the next evening's scheduled run gets a clean attempt."""
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    central = ZoneInfo("America/Chicago")
    now = datetime.now(timezone.utc)
    strikes = 1
    try:
        prev = json.loads(COOLDOWN.read_text())
        prev_until = datetime.fromisoformat(prev["until"])
        if now - prev_until < timedelta(days=3):   # blocked again soon after the last pause ended
            strikes = int(prev.get("strikes", 1)) + 1
    except Exception:
        pass
    days = min(7, 2 ** (strikes - 1))
    local = (now + timedelta(days=days)).astimezone(central)
    until = local.replace(hour=17, minute=0, second=0, microsecond=0)
    if until <= now.astimezone(central) + timedelta(hours=12):
        until += timedelta(days=1)
    COOLDOWN.parent.mkdir(parents=True, exist_ok=True)
    COOLDOWN.write_text(json.dumps({"until": until.astimezone(timezone.utc).isoformat(), "strikes": strikes,
                                    "blocked_at": now.isoformat(), "reason": str(err)[:500]}, indent=2))
    msg = (f"Instagram blocked publishing (block #{strikes} in a row). Pausing all posting until "
           f"{until.strftime('%a %b %-d, %-I:%M %p')} Central. Don't re-run before then: retries can extend the block. "
           "Open the Instagram app and check for an 'Action blocked' notice or Settings > Account status "
           "(tap 'Tell us' if it's a mistake).")
    print(f"[cooldown] {msg}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(f"\n> **Posting paused ({days} day{'s' if days > 1 else ''}).** {msg}\n")


def require_no_cooldown() -> None:
    """Stop before doing any work if posting is paused (dry runs are allowed; they never touch Instagram)."""
    until = cooldown_active()
    if not until or os.environ.get("IGNORE_COOLDOWN", "").lower() == "true":
        return
    from datetime import datetime
    from zoneinfo import ZoneInfo
    when = datetime.fromisoformat(until).astimezone(ZoneInfo("America/Chicago")).strftime("%a %b %-d, %-I:%M %p")
    msg = (f"Posting is paused until {when} Central after an Instagram action block. Wait it out (recommended), "
           "run with dry_run checked to preview, or delete data/cooldown.json to override.")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(f"\n> **{msg}**\n")
    raise SystemExit(f"[cooldown] {msg}")


def cooldown_active() -> str | None:
    from datetime import datetime, timezone
    try:
        c = json.loads(COOLDOWN.read_text())
        until = datetime.fromisoformat(c["until"])
        return c["until"] if until > datetime.now(timezone.utc) else None
    except Exception:
        return None


def report_usage() -> None:
    from .publish import usage_report
    line = usage_report()
    print(f"[usage] {line}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(f"\n{line}\n")


def cmd_publish(args):
    from .picker import record
    from .publish import Instagram

    plan = json.loads((OUT / "plan.json").read_text())
    base = args.base_url.rstrip("/")
    urls = [f"{base}/{name}" for name in plan["slides"]]
    if args.dry_run:
        print("[publish] dry run, would post:", *urls, plan.get("reel", "(no reel)"),
              f"story: {plan.get('story', '(no story)')}", sep="\n  ")
        return
    require_no_cooldown()
    ig = Instagram()
    usage = ig._try_get(f"{ig.user}/content_publishing_limit", fields="config,quota_usage")
    if usage and usage.get("data"):
        u = usage["data"][0]
        print(f"[publish] Instagram API posts used in the last 24h: {u.get('quota_usage')} of "
              f"{(u.get('config') or {}).get('quota_total', '?')}")
    try:
        mid, link = ig.carousel(urls, plan["caption"])
    except RuntimeError as e:
        report_usage()
        if is_action_block(e):
            start_cooldown(e)
            raise SystemExit(1)
        raise
    print(f"[publish] carousel posted: {mid} {link or ''}")
    reel = None
    reel_error = None
    if plan.get("reel") and (OUT / plan["reel"]).exists():
        try:
            music = None
            mcfg = load_cfg().get("music", {})
            if mcfg.get("use_instagram_music", True) and "instagram.com" not in ig.base:
                from .picker import load_history, recently_used_audio
                music = ig.pick_music(mcfg, recently_used_audio(load_history(), mcfg.get("no_repeat_days", 14)))
                print(f"[music] " + (f"using '{music['title']}' by {music['artist'] or '?'} ({music['id']}, {music.get('source')})"
                                     if music else "no Instagram track found; using generated soundtrack"))
            rid, rlink = ig.reel(OUT / plan["reel"], plan["caption"], video_url=f"{base}/{plan['reel']}",
                                 audio_id=music["id"] if music else None,
                                 music_volume=int(mcfg.get("volume", 100)))
            print(f"[publish] reel posted: {rid} {rlink or ''}")
            reel = {"media_id": rid, "permalink": rlink,
                    "audio": music if music and getattr(ig, "last_reel_music", False) else None}
        except Exception as e:
            reel_error = e
            print(f"[publish] reel FAILED (carousel is already live): {e}")
            if is_action_block(e):
                start_cooldown(e)
    fb, fb_error = crosspost_facebook(ig, plan, urls)
    story = post_stories(ig, plan, base)
    record(plan, link, mid, reel=reel, facebook=fb, story=story)
    try:
        from .links import build_links_page
        build_links_page(load_cfg())
    except Exception as e:
        print(f"[links] page build failed: {e}")
    report_usage()
    if reel_error or fb_error:
        raise SystemExit(1)


def post_stories(ig, plan: dict, base: str) -> dict | None:
    """Teaser Story on Instagram and the Facebook Page. Stories are a bonus: a failure here is logged
    (and shown in the run summary) but never fails the run, since the main posts are already live."""
    if not plan.get("story"):
        return None
    scfg = load_cfg().get("stories", {})
    url = f"{base}/{plan['story']}"
    result, problems = {}, []
    if scfg.get("instagram", True):
        try:
            result["instagram"] = ig.story(url)
            print(f"[story] Instagram story published: {result['instagram']}")
        except Exception as e:
            problems.append(f"Instagram story: {e}")
    if scfg.get("facebook", True) and os.environ.get("POST_FACEBOOK", "true").lower() != "false" \
            and "instagram.com" not in ig.base:
        try:
            from .facebook import FacebookPage
            page = FacebookPage(ig.token, ig.user, ig.base.rsplit("/", 1)[-1])
            result["facebook"] = page.photo_story(url)
        except Exception as e:
            problems.append(f"Facebook story: {e}")
    for p in problems:
        print(f"[story] WARNING (posts are fine, only the story failed): {p}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if problems and summary:
        with open(summary, "a") as f:
            f.write("\n> **Story not posted:** " + "; ".join(p[:300] for p in problems) + "\n")
    return result or None


def facebook_message(plan: dict, cfg: dict) -> str:
    """Facebook favors fewer hashtags than Instagram: caption + IG plug + a handful of tags."""
    fcfg = cfg.get("facebook", {})
    tags = plan["copy"].get("hashtags", [])[: int(fcfg.get("max_hashtags", 4))]
    plug = fcfg.get("instagram_plug", "").format(handle=cfg["account"]["handle"])
    links = ""
    if plan.get("watch"):
        from .affiliate import fb_links_block
        links = fb_links_block(plan["watch"], cfg)
    parts = [plan["copy"]["caption"].strip(), links, plug, "Movie data & images: TMDB.", " ".join(tags)]
    return "\n\n".join(p for p in parts if p)


def crosspost_facebook(ig, plan: dict, urls: list[str]):
    cfg = load_cfg()
    fcfg = cfg.get("facebook", {})
    if os.environ.get("POST_FACEBOOK", "true").lower() == "false" or not fcfg.get("enabled", True):
        return None, None
    if "instagram.com" in ig.base:
        print("[facebook] skipped: Facebook cross-posting needs a Facebook Login (EAA...) token")
        return None, None
    from .facebook import FacebookPage
    result, error = {}, None
    try:
        page = FacebookPage(ig.token, ig.user, ig.base.rsplit("/", 1)[-1])
        msg = facebook_message(plan, cfg)
        if fcfg.get("post_photos", True):
            try:
                result["post_id"] = page.photos(urls, msg)
            except Exception as e:
                error = e
                print(f"[facebook] photo post FAILED: {e}")
        if fcfg.get("post_reel", True) and plan.get("reel") and (OUT / plan["reel"]).exists():
            try:
                result["reel_id"] = page.reel(OUT / plan["reel"], msg)
            except Exception as e:
                error = e
                print(f"[facebook] reel FAILED: {e}")
    except Exception as e:
        error = e
        print(f"[facebook] cross-post FAILED (Instagram posts are live): {e}")
    return result or None, error


def cmd_report(args):
    from .insights import run
    from .publish import Instagram
    out = run(Instagram())
    print(f"[report] saved {out}")


def cmd_demo(args):
    """Offline render using generated placeholder art, to preview the design."""
    import io

    from PIL import Image, ImageDraw

    from .render import Renderer

    cfg = load_cfg()

    def fake(path):
        w, h = (500, 750) if "poster" in path else (1280, 720)
        im = Image.new("RGB", (w, h), (30, 20, 22))
        d = ImageDraw.Draw(im)
        for i in range(0, max(w, h), 40):
            d.ellipse([w * .6 - i, h * .3 - i, w * .6 + i, h * .3 + i], outline=(90 + i % 120, 30, 30), width=3)
        b = io.BytesIO()
        im.save(b, "JPEG")
        return b.getvalue()

    movie = {"title": "Night of the Sample", "poster": "/poster.jpg", "backdrops": ["/bd1.jpg", "/bd2.jpg"],
             "release_date": "1986-10-05"}
    plan = {"kind": "anniversary", "years": 40, "movies": [movie]}
    copy = {
        "headline": "40 years ago tonight, the dead got hungry",
        "subhead": "A drive-in staple turns 40. Here's why it still bites.",
        "slides": [
            {"type": "text", "movie_index": 0, "kicker": "October 5, 1986", "title": "It crawled out of a drive-in",
             "body": "Shot fast and cheap, with more latex than budget, it became the movie everyone's older cousin swore they snuck into."},
            {"type": "movie", "movie_index": 0, "kicker": "Who made it", "title": "Night of the Sample",
             "body": "Directed by a first-timer with a garage full of fake blood and a cast of local theater kids."},
            {"type": "text", "movie_index": 0, "kicker": "The legacy", "title": "Practical gore forever",
             "body": "Every melting face in a modern indie owes this one a drink."},
            {"type": "verdict", "movie_index": 0, "kicker": "The verdict", "title": "Still bites",
             "skulls": 4, "body": "Cheesy in the best way. A rite of passage for every slasher fan."},
            {"type": "cta", "movie_index": 0, "title": "Where did you first see it?",
             "body": "VHS at a sleepover? Late-night cable? Drop your origin story below."},
        ],
    }
    r = Renderer(cfg, fake)
    paths = r.render_all(plan, copy, OUT / "demo")
    print("\n".join(str(p) for p in paths))
    from .video import build_reel
    frames = r.render_all(plan, copy, OUT / "demo" / "reel_frames", swipe=False)
    build_reel(frames, copy, OUT / "demo" / "reel.mp4", seed=20261005)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--type", default=os.environ.get("POST_TYPE", "auto"),
                   choices=["auto", "upcoming", "classic", "anniversary"])
    p.set_defaults(fn=cmd_plan)
    q = sub.add_parser("publish")
    q.add_argument("--base-url", required=True, help="public URL prefix where out/ slides are hosted")
    q.add_argument("--dry-run", action="store_true")
    q.set_defaults(fn=cmd_publish)
    sub.add_parser("demo").set_defaults(fn=cmd_demo)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
