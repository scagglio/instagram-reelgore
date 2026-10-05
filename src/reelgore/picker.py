"""Decide today's post type and pick the movie(s)."""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

from .tmdb import TMDB

HISTORY = Path("data/history.json")


def load_history() -> dict:
    if HISTORY.exists():
        return json.loads(HISTORY.read_text())
    return {"posts": []}


def save_history(h: dict) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(h, indent=2))


def recently_used(h: dict, days: int) -> set[int]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    ids: set[int] = set()
    for p in h["posts"]:
        if p["date"] >= cutoff:
            ids.update(p.get("movie_ids", []))
    return ids


def recently_used_audio(h: dict, days: int) -> set[str]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return {p["reel"]["audio"]["id"] for p in h["posts"]
            if p["date"] >= cutoff and (p.get("reel") or {}).get("audio")}


def find_anniversaries(tmdb: TMDB, cfg: dict, today: date) -> list[dict]:
    a = cfg["anniversary"]
    hits = []
    for offset in range(0, a.get("window_days", 0) + 1):
        d = today + timedelta(days=offset)
        for years in a["milestone_years"]:
            y = d.year - years
            try:
                results = tmdb.released_on(d.month, d.day, y, a["min_vote_count"])
            except Exception:
                continue
            for m in results:
                if m.get("vote_count", 0) >= a["min_vote_count"]:
                    m["_years"] = years
                    m["_date"] = d.isoformat()
                    hits.append(m)
    # Rounder milestones and more-loved movies first
    hits.sort(key=lambda m: ((m["_years"] % 25 == 0), (m["_years"] % 10 == 0), m.get("vote_count", 0)), reverse=True)
    return hits


def pick(tmdb: TMDB, cfg: dict, forced: str = "auto", today: date | None = None) -> dict:
    today = today or date.today()
    h = load_history()
    used_year = recently_used(h, 365)

    anniversaries = [m for m in find_anniversaries(tmdb, cfg, today) if m["id"] not in used_year] \
        if forced in ("auto", "anniversary") else []

    if forced == "auto":
        rotation = cfg["rotation"]
        kind = rotation[today.timetuple().tm_yday % len(rotation)]
        # A big milestone (25/50/75/100) on today's date always takes the slot.
        if anniversaries and anniversaries[0]["_years"] % 25 == 0:
            kind = "anniversary"
        if kind == "anniversary" and not anniversaries:
            kind = "classic"
    else:
        kind = forced

    if kind == "anniversary":
        if not anniversaries:
            raise SystemExit("No qualifying horror anniversaries today; try --type classic")
        m = anniversaries[0]
        return {"kind": "anniversary", "years": m["_years"], "movies": [tmdb.details(m["id"])]}

    if kind == "upcoming":
        up = tmdb.upcoming_horror(cfg["upcoming"]["days_ahead"], cfg["upcoming"]["region"])
        up = [m for m in up if m.get("poster_path") or m.get("backdrop_path")]
        recent = recently_used(h, 14)
        fresh = [m for m in up if m["id"] not in recent] or up
        if len(fresh) >= 4:
            chosen = sorted(fresh[:6], key=lambda m: m.get("release_date") or "9999")
            return {"kind": "upcoming_roundup", "movies": [tmdb.details(m["id"]) for m in chosen]}
        if fresh:
            return {"kind": "upcoming_spotlight", "movies": [tmdb.details(fresh[0]["id"])]}
        kind = "classic"  # nothing upcoming; fall through

    # classic
    c = cfg["classic"]
    rng = random.Random(today.toordinal())
    theme = rng.choice(c["themes"])
    kw = None
    try:
        kw = tmdb.keyword_id(theme.split(" and ")[0])
    except Exception:
        pass
    pool = []
    for page in (1, 2, 3):
        pool += tmdb.classic_horror(c["max_year"], c["min_vote_count"], page=page, keyword_ids=kw)
    if len(pool) < 5:  # theme too narrow; widen
        theme = "all-time classic"
        for page in (1, 2, 3, 4, 5):
            pool += tmdb.classic_horror(c["max_year"], c["min_vote_count"], page=page)
    pool = [m for m in pool if m["id"] not in used_year]
    if not pool:
        raise SystemExit("Classic pool exhausted; widen config.classic")
    m = rng.choice(pool[:30])
    return {"kind": "classic", "theme": theme, "movies": [tmdb.details(m["id"])]}


def record(plan: dict, permalink: str | None, media_id: str | None, reel: dict | None = None) -> None:
    h = load_history()
    h["posts"].append({
        "date": date.today().isoformat(),
        "kind": plan["kind"],
        "movie_ids": [m["id"] for m in plan["movies"]],
        "titles": [m["title"] for m in plan["movies"]],
        "headline": plan.get("copy", {}).get("headline"),
        "media_id": media_id,
        "permalink": permalink,
        "reel": reel,
    })
    save_history(h)
