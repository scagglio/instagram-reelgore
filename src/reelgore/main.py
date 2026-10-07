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
    from .picker import parse_titles, pick, pick_custom
    from .render import Renderer
    from .tmdb import TMDB
    from .writer import caption_text, write_copy

    cfg = load_cfg()
    tmdb = TMDB()
    titles = parse_titles(os.environ.get("MOVIES", ""))
    if titles:
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


def cmd_publish(args):
    from .picker import record
    from .publish import Instagram

    plan = json.loads((OUT / "plan.json").read_text())
    base = args.base_url.rstrip("/")
    urls = [f"{base}/{name}" for name in plan["slides"]]
    if args.dry_run:
        print("[publish] dry run, would post:", *urls, plan.get("reel", "(no reel)"), sep="\n  ")
        return
    ig = Instagram()
    mid, link = ig.carousel(urls, plan["caption"])
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
    fb, fb_error = crosspost_facebook(ig, plan, urls)
    record(plan, link, mid, reel=reel, facebook=fb)
    try:
        from .links import build_links_page
        build_links_page(load_cfg())
    except Exception as e:
        print(f"[links] page build failed: {e}")
    if reel_error or fb_error:
        raise SystemExit(1)


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
