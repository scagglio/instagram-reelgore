"""Use Claude to write slide copy + caption in the Reel Gore voice."""
from __future__ import annotations

import json
import re
import os

TOOL = {
    "name": "submit_carousel",
    "description": "Submit the finished Instagram carousel copy.",
    "input_schema": {
        "type": "object",
        "required": ["headline", "subhead", "slides", "caption", "hashtags"],
        "properties": {
            "headline": {"type": "string", "description": "Cover hook, max 8 words"},
            "subhead": {"type": "string", "description": "One short line under the hook, max 12 words"},
            "slides": {
                "type": "array",
                "description": "Body slides after the cover, in order",
                "items": {
                    "type": "object",
                    "required": ["type", "movie_index", "kicker", "title", "body"],
                    "properties": {
                        "type": {"type": "string", "enum": ["movie", "text", "verdict", "cta"]},
                        "movie_index": {"type": "integer", "description": "Index into FACTS of the movie this slide is about"},
                        "kicker": {"type": "string", "description": "Tiny label above the title, max 4 words"},
                        "title": {"type": "string", "description": "Max 6 words"},
                        "body": {"type": "string", "description": "Max 38 words"},
                        "skulls": {"type": "integer", "minimum": 0, "maximum": 5, "description": "Verdict slides only: 1-5"},
                    },
                },
            },
            "caption": {"type": "string", "description": "60-150 words, hook first line, ends with a question to drive comments"},
            "hashtags": {"type": "array", "items": {"type": "string"}, "description": "6-10 niche tags for these movies/sub-genre"},
        },
    },
}

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
    examples = "; ".join(f"'{e}'" for e in cfg.get("engagement", {}).get("cta_examples", []))
    rules = (
        "\n\nENGAGEMENT RULES:\n"
        "- The caption's LAST line must be a two-sided, pick-one debate question that readers can answer in "
        f"one or two words. Examples of the style: {examples}. Never end with 'thoughts?', 'let us know', "
        "or 'comment below'.\n"
        "- The 'cta' slide title must be that same kind of pick-one question (max 6 words). Its body names "
        "the two options, or asks for a 1-5 skull rating in one word.\n"
        "- The caption's first line is a scroll-stopping hook, not a summary."
    )
    series = plan.get("series")
    if series:
        n, total = series["n"], series["total"]
        tease = ("This is the FINALE: make the caption feel like a send-off and thank people for following "
                 "the series." if n >= total else
                 f"Before the closing question, tease tomorrow with one short line like 'Night {n + 1} drops "
                 "tomorrow.' (don't name tomorrow's film).")
        rules += (f"\n\nSERIES: This post is Night {n} of {total} in Reel Gore's '{series['name']}' series. "
                  f"Work 'Night {n}' naturally into the caption's first line. {tease}")
    prompt = (
        f"{brief}{rules}\n\nTotal slides including cover must be between {s['count_min']} and {s['count_max']} "
        f"(the cover is generated from headline/subhead and is NOT in the slides array).\n\n"
        f"FACTS (the only facts you may state):\n{_facts(plan)}\n\nSubmit the result with the submit_carousel tool."
    )
    client = anthropic.Anthropic()
    wanted = os.environ.get("CLAUDE_MODEL", "").strip()
    model = wanted or _pick_model(client)
    base = dict(max_tokens=8000, system=cfg["voice"], tools=[TOOL],
                messages=[{"role": "user", "content": prompt}])

    def call(model):
        try:
            return client.messages.create(
                model=model, tool_choice={"type": "tool", "name": "submit_carousel"}, **base)
        except anthropic.BadRequestError as e:
            if "tool_choice" not in str(e):
                raise
            # Some models (e.g. always-thinking ones) only allow tool_choice auto.
            print(f"[writer] {model} doesn't support forced tool_choice; using auto")
            return client.messages.create(model=model, **base)

    try:
        msg = call(model)
    except anthropic.NotFoundError:
        model = _pick_model(client)
        print(f"[writer] model '{wanted}' not found, falling back to '{model}'")
        msg = call(model)

    print(f"[writer] model={model} stop_reason={msg.stop_reason}")
    copy = _extract(msg)
    if not copy or not copy.get("slides"):
        raise RuntimeError("Claude returned no usable carousel copy")
    return _clamp(copy, plan, cfg)


def _extract(msg) -> dict | None:
    """Prefer the tool_use payload; otherwise parse JSON out of the text leniently."""
    for b in msg.content:
        if getattr(b, "type", "") == "tool_use" and b.name == "submit_carousel":
            return dict(b.input)
    text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
    return _loose_json(text)


def _loose_json(text: str) -> dict | None:
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    if start < 0:
        return None
    # Walk to the matching closing brace, respecting strings.
    depth, in_str, esc, end = 0, False, False, None
    for i, ch in enumerate(text[start:], start):
        if in_str:
            esc = (ch == "\\") and not esc
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    blob = text[start:end] if end else text[start:]
    blob = re.sub(r"(?m)^\s*//.*$", "", blob)          # whole-line // comments
    blob = re.sub(r",\s*([}\]])", r"\1", blob)         # trailing commas
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def _pick_model(client) -> str:
    """Newest Sonnet available to this API key (models.list returns newest first)."""
    ids = [m.id for m in client.models.list(limit=100).data]
    for family in ("sonnet", "opus", "haiku"):
        for mid in ids:
            if family in mid:
                return mid
    if not ids:
        raise RuntimeError("No Claude models available to this API key")
    return ids[0]


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


def caption_text(copy: dict, plan: dict, extra: str | None = None) -> str:
    watch = f"\n\n{extra}" if extra else ""
    credit = "\n\nMovie data & images: TMDB." + (" Streaming data: JustWatch." if extra else "")
    return f"{copy['caption'].strip()}{watch}{credit}\n.\n.\n{' '.join(copy['hashtags'])}"[:2200]
