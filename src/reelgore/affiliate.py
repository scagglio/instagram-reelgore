"""Where-to-watch data + affiliate links for a post."""
from __future__ import annotations

import os
from urllib.parse import quote_plus

from .tmdb import TMDB, watch_providers


def _amazon(query: str, tag: str) -> str:
    return f"https://www.amazon.com/s?k={quote_plus(query)}&i=movies-tv&tag={quote_plus(tag)}"


def build_watch(tmdb: TMDB, movie: dict, cfg: dict) -> dict | None:
    """Collect streaming services and build 'own it' affiliate links for one movie."""
    acfg = cfg.get("affiliate", {})
    region = acfg.get("region", "US")
    try:
        prov = watch_providers(tmdb, movie["id"], region)
    except Exception as e:
        print(f"[affiliate] provider lookup failed: {e}")
        prov = {"stream": [], "rent": [], "buy": [], "link": None}

    year = (movie.get("release_date") or "")[:4]
    title = movie["title"]
    templates = acfg.get("provider_links", {}) or {}
    stream = []
    for p in prov["stream"][: acfg.get("max_services", 4)]:
        url = templates.get(p["name"])
        stream.append({**p, "url": url.format(title=quote_plus(title)) if url else None})

    own = []
    tag = (os.environ.get("AMAZON_ASSOCIATE_TAG") or acfg.get("amazon_tag") or "").strip()
    if tag:
        for label, suffix in (("4K UHD", "4K UHD"), ("Blu-ray", "Blu-ray")):
            own.append({"label": f"{label} on Amazon", "url": _amazon(f"{title} {year} {suffix}", tag)})
    for extra in acfg.get("extra_shops", []) or []:
        own.append({"label": extra["label"], "url": extra["url"].format(title=quote_plus(title), year=year)})

    if not stream and not prov["rent"] and not own:
        return None
    return {
        "title": title, "year": year, "stream": stream,
        "rent": [p["name"] for p in prov["rent"][:4]],
        "own": own, "justwatch": prov.get("link"),
    }


def watch_slide(watch: dict) -> dict:
    return {"type": "watch", "movie_index": 0, "kicker": "WHERE TO WATCH",
            "title": watch["title"], "body": ""}


def ig_caption_line(watch: dict, cfg: dict) -> str:
    acfg = cfg.get("affiliate", {})
    parts = []
    if watch["stream"]:
        parts.append("Stream it: " + ", ".join(p["name"] for p in watch["stream"]))
    if watch["own"]:
        parts.append(acfg.get("ig_link_line", "Own it on 4K: link in bio"))
    return " | ".join(parts)


def fb_links_block(watch: dict, cfg: dict) -> str:
    acfg = cfg.get("affiliate", {})
    lines = [f"Where to watch {watch['title']}:"]
    for p in watch["stream"]:
        lines.append(f"- Stream on {p['name']}" + (f": {p['url']}" if p.get("url") else ""))
    if watch["rent"] and not watch["stream"]:
        lines.append("- Rent on " + ", ".join(watch["rent"]))
    for o in watch["own"]:
        lines.append(f"- {o['label']}: {o['url']}")
    if watch["own"] or any(p.get("url") for p in watch["stream"]):
        lines.append(acfg.get("disclosure", "#ad Affiliate links: we may earn a commission at no cost to you."))
    lines.append("Streaming data: JustWatch.")
    return "\n".join(lines)
