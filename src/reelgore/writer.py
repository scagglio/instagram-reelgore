"""Use Claude to write slide copy + caption in the Reel Gore voice."""
from __future__ import annotations

import json
import os
import re

SCHEMA = """Return ONLY a JSON object, no prose, with this shape:
{
  "headline": "cover hook, max 8 words, ALL CAPS friendly",
  "subhead": "one short line under the hook, max 12 words",
  "slides": [
    {
      "type": "movie" | "text" | "verdict" | "cta",
      "movie_index": 0,            // which movie in FACTS this slide is about
      "kicker": "tiny label above title, max 4 words (e.g. 'IN THEATERS OCT 17')",
      "title": "max 6 words",
      "body": "max 38 words",
      "skulls": 0                  // verdict slides only: 1-5 skull rating
    }
  ],
  "caption": "Instagram caption, 60-150 words, hook first line, ends with a question to drive comments",
  "hashtags": ["#tag", "..."]      // 6-10 niche tags specific to these movies/sub-genre
}"""

BRIEFS = {
    "upcoming_roundup": (
        "Make a 'COMING TO HAUNT YOU' carousel of upcoming horror releases. One 'movie' slide per film "
        "in FACTS order, kicker = release date in the form 'IN THEATERS MON DD' (use release_date). "
        "Body = spoiler-free premise plus one reason a horror fan should care (director, cast, sub-genre). "
        "Finish with one 'cta' slide asking which one they're seeing first."
    ),
    "upcoming_spotlight": (
        "Make a spotlight carousel on ONE upcoming horror release: a premise slide, a 'who's behind it' slide "
        "(director/writers/cast from FACTS), a 'why we're hyped' slide, a 'what to watch before it' slide "
        "(older horror films with a similar vibe — titles only, no invented facts about them), then a 'cta'."
    ),
    "classic": (
        "Make a 'FROM THE CRYPT' deep-dive carousel on a classic horror film (theme: {theme}). "
        "Slides: the setup (no spoilers), the people who made it (from FACTS), why it still rules today, "
        "the scene/craft that earned its place (keep it vague if FACTS don't describe it), "
        "a 'verdict' slide with a 1-5 skull rating and a one-line verdict, then a 'cta' asking for their rating."
    ),
    "anniversary": (
        "Make a '{years} YEARS AGO TODAY' anniversary carousel. The film was released on {release_date}. "
        "Headline must mention the {years} years. Slides: what hit screens that day, who made it (FACTS), "
        "its legacy for horror, a 'where it stands now' slide, a 'verdict' slide with skull rating, then a 'cta' "
        "asking where they first saw it."
    ),
}


def _facts(plan: dict) -> str:
    keep = ["title", "release_date", "runtime", "overview", "tagline", "genres", "countries",
            "directors", "writers", "makeup_fx", "composer", "cast", "budget", "revenue", "vote_average"]
    return json.dumps([{k: m.get(k) for k in keep if m.get(k)} for m in plan["movies"]], indent=1)


def write_copy(plan: dict, cfg: dict) -> dict:
    import anthropic

    brief = BRIEFS[plan["kind"]].format(
        theme=plan.get("theme", ""),
        years=plan.get("years", ""),
        release_date=plan["movies"][0].get("release_date", ""),
    )
    s = cfg["slides"]
    prompt = (
        f"{brief}\n\nTotal slides including cover must be between {s['count_min']} and {s['count_max']} "
        f"(the cover is generated from headline/subhead and is NOT in the slides array).\n\n"
        f"FACTS (the only facts you may state):\n{_facts(plan)}\n\n{SCHEMA}"
    )
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5"),
        max_tokens=2500,
        system=cfg["voice"],
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    copy = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
    return _clamp(copy, plan, cfg)


def _clamp(copy: dict, plan: dict, cfg: dict) -> dict:
    n = len(plan["movies"])
    max_body = cfg["slides"]["count_max"] - 1
    copy["slides"] = copy.get("slides", [])[:max_body]
    for sl in copy["slides"]:
        sl["movie_index"] = min(max(int(sl.get("movie_index", 0) or 0), 0), n - 1)
        sl["skulls"] = min(max(int(sl.get("skulls", 0) or 0), 0), 5)
    tags = cfg["hashtags"]
    merged = list(dict.fromkeys(tags["always"] + [t if t.startswith("#") else f"#{t}" for t in copy.get("hashtags", [])] + tags["pool"]))
    copy["hashtags"] = merged[: tags["max_total"]]
    return copy


def caption_text(copy: dict, plan: dict) -> str:
    credit = "\n\nMovie data & images: TMDB."
    return f"{copy['caption'].strip()}{credit}\n.\n.\n{' '.join(copy['hashtags'])}"[:2200]
