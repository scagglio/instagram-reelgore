"""Decide today's post type and pick the movie(s)."""
from __future__ import annotations

import json
import os
import random
from datetime import date, timedelta
from pathlib import Path

from .tmdb import TMDB

HISTORY = Path("data/history.json")


def load_history(path: Path | None = None) -> dict:
    """Read post history. An empty, missing or damaged file never stops a post: it's treated as no history
    (a damaged file is backed up first so nothing is lost)."""
    path = path or HISTORY
    if not path.exists():
        return {"posts": []}
    raw = path.read_text().strip()
    if not raw:
        print(f"[history] {path} is empty; starting a fresh history")
        return {"posts": []}
    try:
        h = json.loads(raw)
        if isinstance(h, list):          # tolerate a bare list of posts
            h = {"posts": h}
        h.setdefault("posts", [])
        return h
    except json.JSONDecodeError as e:
        backup = path.with_name(path.name + ".broken")
        backup.write_text(raw)
        print(f"[history] {path} is damaged ({e}); saved a copy to {backup} and starting fresh")
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


def roundup_limit_reached(h: dict, cfg: dict, today: date) -> bool:
    """True if this calendar month already has as many upcoming roundups as `upcoming.roundups_per_month` allows."""
    limit = int(cfg.get("upcoming", {}).get("roundups_per_month", 1))
    if limit <= 0:
        return True   # 0 = never post automatic roundups
    month = today.isoformat()[:7]
    done = sum(1 for p in h["posts"] if p.get("kind") == "upcoming_roundup" and str(p.get("date", "")).startswith(month))
    return done >= limit


def load_weights() -> dict | None:
    """Rotation weights written by the weekly report (data/weights.json)."""
    path = Path("data/weights.json")
    try:
        w = json.loads(path.read_text()).get("weights") or {}
        return w if any(v != 1.0 for v in w.values()) else None
    except Exception:
        return None


def weighted_kind(rotation: list[str], weights: dict, h: dict, today: date) -> str:
    """Pick today's type in proportion to how well each type performs, without repeating
    yesterday's type when there's an alternative (keeps the feed varied)."""
    last = None
    for p in reversed(h["posts"]):
        if p.get("trigger") == "schedule" or p.get("trigger") is None:
            last = "upcoming" if p["kind"].startswith("upcoming") else p["kind"]
            break
    w = {k: float(weights.get(k, 1.0)) for k in rotation}
    if last in w and len(w) > 1:
        w[last] *= 0.35
    rng = random.Random(today.toordinal() * 7919)
    total = sum(w.values())
    x, acc = rng.uniform(0, total), 0.0
    for k, v in w.items():
        acc += v
        if x <= acc:
            print(f"[picker] weighted choice {k} from {w}")
            return k
    return rotation[-1]


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
        weights = load_weights()
        if weights:
            kind = weighted_kind(rotation, weights, h, today)
        # A big milestone (25/50/75/100) on today's date always takes the slot.
        if anniversaries and anniversaries[0]["_years"] % 25 == 0:
            kind = "anniversary"
        # Upcoming roundups are capped (default: once per calendar month); other days get something else.
        if kind == "upcoming" and roundup_limit_reached(h, cfg, today):
            kind = "anniversary" if anniversaries else "classic"
            print(f"[picker] this month's upcoming roundup already posted; posting {kind} instead")
        if kind == "anniversary" and not anniversaries:
            kind = "classic"
    else:
        kind = forced

    if kind == "anniversary":
        for m in anniversaries[:6]:
            d = tmdb.details(m["id"])
            if d.get("english_title", True):
                return {"kind": "anniversary", "years": m["_years"], "movies": [d]}
            print(f"[picker] skipping '{d['title']}': no English title on TMDB")
        if forced == "anniversary":
            raise SystemExit("No qualifying horror anniversaries today; try --type classic")
        kind = "classic"

    if kind == "upcoming":
        up = tmdb.upcoming_horror(cfg["upcoming"]["days_ahead"], cfg["upcoming"]["region"])
        up = [m for m in up if m.get("poster_path") or m.get("backdrop_path")]
        recent = recently_used(h, 14)
        fresh = [m for m in up if m["id"] not in recent] or up
        details = []
        for m in fresh[:12]:
            d = tmdb.details(m["id"])
            if d.get("english_title", True):
                details.append(d)
            else:
                print(f"[picker] skipping '{d['title']}': no English title on TMDB")
            if len(details) == 6:
                break
        if len(details) >= 4:
            return {"kind": "upcoming_roundup",
                    "movies": sorted(details, key=lambda m: m.get("release_date") or "9999")}
        if details:
            return {"kind": "upcoming_spotlight", "movies": [details[0]]}
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
    candidates = pool[:30]
    rng.shuffle(candidates)
    for m in candidates[:8]:
        d = tmdb.details(m["id"])
        if d.get("english_title", True):
            return {"kind": "classic", "theme": theme, "movies": [d]}
        print(f"[picker] skipping '{d['title']}': no English title on TMDB")
    raise SystemExit("Couldn't find a classic with an English title; try again or widen config.classic")


def parse_titles(raw: str) -> list[str]:
    """Split the manual-run box on commas (or semicolons / new lines), dropping blanks and duplicates."""
    import re
    parts = [x.strip().strip('"').strip("'").strip() for x in re.split(r"[,;\n]", raw or "")]
    seen, out = set(), []
    for x in parts:
        if x and x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out


def pick_custom(tmdb: TMDB, titles: list[str], list_title: str = "", max_films: int = 8) -> dict:
    """Build a plan from movies you typed in. One film = deep dive; several = a 'Reel Gore Picks' list."""
    found, missing = [], []
    for t in titles[:max_films]:
        hit = tmdb.find_movie(t)
        if hit:
            d = tmdb.details(hit["id"])
            print(f"[picker] '{t}' -> {d['title']} ({(d.get('release_date') or '????')[:4]}) tmdb:{d['id']}")
            found.append(d)
        else:
            missing.append(t)
            print(f"[picker] couldn't find '{t}' on TMDB; skipping it")
    if len(titles) > max_films:
        print(f"[picker] only the first {max_films} titles fit in one carousel; ignoring {titles[max_films:]}")
    if not found:
        raise SystemExit(f"None of these matched a movie on TMDB: {titles}. Check spelling, or add the year, "
                         "e.g. 'The Thing (1982)'.")
    released = lambda m: bool(m.get("release_date")) and m["release_date"] <= date.today().isoformat()
    if len(found) == 1:
        m = found[0]
        kind = "pick" if released(m) else "upcoming_spotlight"
        return {"kind": kind, "movies": [m], "custom": True, "missing": missing}
    return {"kind": "picks", "movies": found, "custom": True, "missing": missing,
            "list_title": list_title.strip(), "max_slides": len(found) + 2}


def pick_person(tmdb: TMDB, name: str) -> dict:
    """Single-person horror spotlight (one actor, actress or filmmaker per post)."""
    hit = tmdb.find_person(name)
    if not hit:
        raise SystemExit(f"Couldn't find '{name}' on TMDB. Check the spelling, or use their TMDB id like "
                         "'tmdb-person:8944' (the number in their TMDB page address).")
    person = tmdb.person_details(hit["id"])
    print(f"[picker] '{name}' -> {person['name']} (tmdb-person:{person['id']}), "
          f"{person['horror_count']} horror credits")
    if not person["roles"]:
        raise SystemExit(f"{person['name']} has no horror credits on TMDB, so there's nothing to spotlight "
                         "for a horror account. Double-check it's the right person.")
    h = load_history()
    before = [p_["date"] for p_ in h["posts"] if p_.get("kind") == "person" and p_.get("person_id") == person["id"]]
    if before:
        print(f"[picker] heads-up: {person['name']} was already spotlighted on {', '.join(before)}")
    # Roles double as the "movies" list so the existing slide types (movie slides etc.) can show them
    return {"kind": "person", "person": person, "movies": person["roles"], "custom": True}


def record(plan: dict, permalink: str | None, media_id: str | None, reel: dict | None = None,
           facebook: dict | None = None, story: dict | None = None) -> None:
    h = load_history()
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        today = datetime.now(ZoneInfo("America/Chicago")).date().isoformat()
    except Exception:
        today = date.today().isoformat()
    h["posts"].append({
        "date": today,
        "trigger": os.environ.get("GITHUB_EVENT_NAME", "local"),
        "kind": plan["kind"],
        "movie_ids": [m["id"] for m in plan["movies"]],
        "titles": [plan["person"]["name"]] if plan.get("person") else [m["title"] for m in plan["movies"]],
        "person_id": (plan.get("person") or {}).get("id"),
        "headline": plan.get("copy", {}).get("headline"),
        "media_id": media_id,
        "permalink": permalink,
        "reel": reel,
        "facebook": facebook,
        "story": story,
        "watch": plan.get("watch"),
        "poster": (plan["movies"][0].get("poster") if plan.get("movies") else None),
    })
    save_history(h)
