"""Trivia source: the film's English Wikipedia article (production, release, legacy sections).
Claude may only use trivia found in this text, so the 'Did you know?' facts are grounded, not invented."""
from __future__ import annotations

import re

import requests

UA = {"User-Agent": "reelgore-agent/1.0 (https://github.com/scagglio/instagram-reelgore)"}
API = "https://en.wikipedia.org/w/api.php"
# Sections that tend to hold good trivia, in priority order
WANT = ["production", "costume", "mask", "design", "location", "inspiration", "background", "conception", "development", "pre-production", "writing", "casting", "filming", "principal photography",
        "special effects", "effects", "makeup", "music", "soundtrack", "release", "box office", "reception",
        "legacy", "influence", "controversy", "censorship", "home media", "trivia", "accolades"]


def _title_from_wikidata(qid: str) -> str | None:
    try:
        r = requests.get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json", headers=UA, timeout=20)
        r.raise_for_status()
        ent = r.json()["entities"][qid]
        return ent.get("sitelinks", {}).get("enwiki", {}).get("title")
    except Exception:
        return None


def _title_from_search(title: str, year: str) -> str | None:
    try:
        r = requests.get(API, headers=UA, timeout=20, params={
            "action": "query", "list": "search", "format": "json", "srlimit": 5,
            "srsearch": f'"{title}" {year} film'})
        hits = r.json().get("query", {}).get("search", [])
    except Exception:
        return None
    for h in hits:
        if title.lower() in h["title"].lower() and ("film" in h["title"].lower() or year in h.get("snippet", "")):
            return h["title"]
    return hits[0]["title"] if hits and title.lower() in hits[0]["title"].lower() else None


def _extract(page: str) -> str | None:
    try:
        r = requests.get(API, headers=UA, timeout=20, params={
            "action": "query", "prop": "extracts", "explaintext": 1, "exsectionformat": "wiki",
            "redirects": 1, "format": "json", "titles": page})
        pages = r.json()["query"]["pages"]
        return next(iter(pages.values())).get("extract")
    except Exception:
        return None


def trivia_notes(movie: dict, max_chars: int = 7000) -> str | None:
    """Return the trivia-rich parts of the film's Wikipedia article, or None."""
    year = (movie.get("release_date") or "")[:4]
    page = (_title_from_wikidata(movie["wikidata_id"]) if movie.get("wikidata_id") else None) \
        or _title_from_search(movie["title"], year)
    if not page:
        return None
    text = _extract(page)
    if not text:
        return None
    # Split into sections on "== Heading ==" (any level)
    parts = re.split(r"\n(=+)\s*(.+?)\s*\1\n", "\n" + text)
    sections = []
    for i in range(1, len(parts) - 2, 3):
        heading, body = parts[i + 1].strip(), parts[i + 2].strip()
        if body:
            sections.append((heading, body))
    skip = ("plot", "synopsis", "cast", "references", "see also", "external links", "notes", "further reading",
            "bibliography", "citations", "sources", "footnotes", "works cited")
    usable = [(h, b) for h, b in sections if not any(h.lower().startswith(x) for x in skip)
              or "casting" in h.lower()]
    def priority(hb):
        h = hb[0].lower()
        return next((i for i, w in enumerate(WANT) if w in h), len(WANT))
    picked = sorted(usable, key=priority)
    if not picked:  # no useful sections: use the lead paragraph(s)
        lead = parts[0].strip()
        return f"[{page}]\n{lead[:max_chars]}" if lead else None
    out, total = [f"[Wikipedia: {page}]"], 0
    for heading, body in picked:
        chunk = f"\n## {heading}\n{body}"
        if total + len(chunk) > max_chars:
            chunk = chunk[: max(0, max_chars - total)]
        out.append(chunk)
        total += len(chunk)
        if total >= max_chars:
            break
    print(f"[trivia] Wikipedia '{page}': {total} chars from {', '.join(h for h, _ in picked[:6])}")
    return "".join(out)
