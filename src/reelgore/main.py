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
    from .picker import pick
    from .render import Renderer
    from .tmdb import TMDB
    from .writer import caption_text, write_copy

    cfg = load_cfg()
    tmdb = TMDB()
    plan = pick(tmdb, cfg, forced=args.type)
    print(f"[plan] {plan['kind']}: {[m['title'] for m in plan['movies']]}")
    copy = write_copy(plan, cfg)
    plan["copy"] = copy
    plan["caption"] = caption_text(copy, plan)

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
    record(plan, link, mid, reel=reel)
    if reel_error:
        raise SystemExit(1)


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
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
