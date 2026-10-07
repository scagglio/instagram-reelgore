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
                        "type": {"type": "string", "enum": ["movie", "text", "trivia", "verdict", "cta"]},
                        "movie_index": {"type": "integer", "description": "Index into FACTS of the movie this slide is about"},
                        "kicker": {"type": "string", "description": "Tiny label above the title, max 4 words"},
                        "title": {"type": "string", "description": "Max 6 words"},
                        "body": {"type": "string", "description": "Max 38 words"},
                        "skulls": {"type": "integer", "minimum": 0, "maximum": 5, "description": "Verdict slides only: 1-5"},
                        "points": {"type": "array", "items": {"type": "string"},
                                   "description": "Trivia slides only: exactly 2 surprising behind-the-scenes facts, max 26 words each"},
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
        "Make a spotlight carousel on ONE upcoming horror release: a premise slide, a 'trivia' slide "
        "(behind-the-scenes facts about the production), a 'why we're hyped' slide, a 'what to watch before it' slide "
        "(older horror films with a similar vibe — titles only, no invented facts about them), then a 'cta'."
    ),
    "classic": (
        "Make a 'FROM THE CRYPT' deep-dive carousel on a classic horror film (theme: {theme}). "
        "Slides: the setup (no spoilers), a 'trivia' slide, why it still rules today, "
        "the scene/craft that earned its place (keep it vague if the sources don't describe it), "
        "a 'verdict' slide with a 1-5 skull rating and a one-line verdict, then a 'cta' asking for their rating."
    ),
    "pick": (
        "Make a 'REEL GORE PICK' deep-dive carousel on a film the Reel Gore host hand-picked. "
        "Slides: the setup (no spoilers), a 'trivia' slide, why it's worth your night, "
        "the craft that makes it work (keep it vague if the sources don't describe it), a 'verdict' slide with a 1-5 "
        "skull rating and a one-line verdict, then a 'cta'."
    ),
    "picks": (
        "Make a 'REEL GORE PICKS' list carousel of films the host hand-picked{list_title}. "
        "One 'movie' slide per film in FACTS order (movie_index 0, 1, 2...). Kicker = the release year "
        "(or 'IN THEATERS MON DD' if release_date is in the future). Title = the film's title. Body = a "
        "spoiler-free hook plus why it earns a spot on this list. Then exactly one 'cta' slide. "
        "The headline should sell the list as a whole{headline_hint}."
    ),
    "person": (
        "Make a 'HORROR ICON' spotlight carousel on ONE person: {person_name}. Slides, in order: "
        "a 'text' slide on who they are and why horror fans know them (kicker like 'THE ICON'); "
        "a 'trivia' slide; then one 'movie' slide for each of their 3 most notable horror roles from ROLES "
        "(movie_index = that role's index in FACTS, kicker = the year, title = the film, body = who they played "
        "and why the performance or film matters); a 'text' slide with kicker 'WHERE TO START' recommending "
        "one of those films for newcomers; then a 'cta' whose title pits two of their roles against each other "
        "(e.g. 'Laurie or Annie? Pick one.'). The headline names them."
    ),
    "anniversary": (
        "Make a '{years} YEARS AGO TODAY' anniversary carousel. The film was released on {release_date}. "
        "Headline must mention the {years} years. Slides: what hit screens that day, a 'trivia' slide, "
        "its legacy for horror, a 'where it stands now' slide, a 'verdict' slide with skull rating, then a 'cta' "
        "asking where they first saw it."
    ),
}


TRIVIA_KINDS = {"classic", "anniversary", "pick", "upcoming_spotlight", "person"}


def _trivia_rules(plan: dict) -> str:
    notes = plan.get("trivia_notes")
    person = plan.get("person")
    respect = ("- This is a real person. Stick to their career and public work. No comments on looks, private "
               "life, health, relationships or politics. If they have died (deathday), be respectful.\n"
               if person else "")
    base = ("\n\nTRIVIA RULES (for the 'trivia' slide):\n" + respect +
            "- kicker 'DID YOU KNOW?', a short punchy title, empty body, and exactly 2 'points'.\n"
            "- Pick the most surprising, fun behind-the-scenes facts: budget hacks, props, casting near-misses, "
            "shooting stories, censorship, box-office surprises. Skip dry facts like who wrote the score.\n"
            "- Do NOT list cast and crew anywhere in the carousel. Mentioning the director once in passing is fine.\n")
    if notes:
        return base + ("- Every trivia point MUST come from SOURCE NOTES below, reworded in your own words. "
                       "Never add details that aren't in the notes.\n\nSOURCE NOTES (Wikipedia):\n" + notes)
    return base + ("- No source notes are available for this film, so build both points only from FACTS "
                   "(budget, box office, runtime, release date, country, tagline). Never invent trivia.")


def _person_facts(plan: dict) -> str:
    p = plan["person"]
    person = {k: p.get(k) for k in ("name", "birthday", "deathday", "place_of_birth", "known_for_department",
                                    "biography", "horror_count") if p.get(k)}
    roles = [{"index": i, "title": r["title"], "year": (r.get("release_date") or "")[:4], "role": r.get("role"),
              "overview": r.get("overview")} for i, r in enumerate(plan["movies"])]
    return json.dumps({"PERSON": person, "ROLES": roles}, indent=1)


def _facts(plan: dict) -> str:
    if plan.get("person"):
        return _person_facts(plan)
    keep = ["title", "aka", "release_date", "runtime", "overview", "tagline", "genres", "countries",
            "directors", "writers", "makeup_fx", "composer", "cast", "budget", "revenue", "vote_average"]
    return json.dumps([{k: m.get(k) for k in keep if m.get(k)} for m in plan["movies"]], indent=1)


def write_copy(plan: dict, cfg: dict) -> dict:
    import anthropic

    lt = plan.get("list_title", "")
    brief = BRIEFS[plan["kind"]].format(
        person_name=(plan.get("person") or {}).get("name", ""),
        list_title=f" titled '{lt}'" if lt else "",
        headline_hint=f" (use or closely echo '{lt}')" if lt else "",
        theme=plan.get("theme", ""),
        years=plan.get("years", ""),
        release_date=plan["movies"][0].get("release_date", ""),
    )
    s = dict(cfg["slides"])
    if plan.get("max_slides"):  # list posts: one slide per film + cover + cta (Instagram allows 10)
        s["count_max"] = min(10, max(s["count_max"], plan["max_slides"]))
        s["count_min"] = min(s["count_max"], plan["max_slides"])
    plan["_count_max"] = s["count_max"]
    examples = "; ".join(f"'{e}'" for e in cfg.get("engagement", {}).get("cta_examples", []))
    rules = (
        "\n\nENGAGEMENT RULES:\n"
        "- The caption's LAST line must be a two-sided, pick-one debate question that readers can answer in "
        f"one or two words. Examples of the style: {examples}. Never end with 'thoughts?', 'let us know', "
        "or 'comment below'.\n"
        "- The 'cta' slide title must be that same kind of pick-one question (max 6 words). Its body names "
        "the two options, or asks for a 1-5 skull rating in one word.\n"
        "- The caption's first line is a scroll-stopping hook, not a summary.\n"
        "- Always call films by their FACTS 'title' (the English title). If a film has an 'aka' (original title), "
        "you may mention it once, e.g. 'Deep Red (Profondo Rosso)'."
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
        f"FACTS (the only facts you may state, plus SOURCE NOTES if given):\n{_facts(plan)}"
        f"{_trivia_rules(plan) if plan['kind'] in TRIVIA_KINDS else ''}\n\nSubmit the result with the submit_carousel tool."
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
    max_body = plan.get("_count_max", cfg["slides"]["count_max"]) - 1
    copy["slides"] = copy.get("slides", [])[:max_body]
    for sl in copy["slides"]:
        sl["movie_index"] = min(max(int(sl.get("movie_index", 0) or 0), 0), n - 1)
        sl["skulls"] = min(max(int(sl.get("skulls", 0) or 0), 0), 5)
        if sl.get("type") == "trivia":
            pts = [str(p).strip() for p in (sl.get("points") or []) if str(p).strip()]
            if not pts and sl.get("body"):
                pts = [sl["body"]]
            sl["points"] = pts[:2]
            if not sl["points"]:
                sl["type"] = "text"
    tags = cfg["hashtags"]
    merged = list(dict.fromkeys(tags["always"] + [t if t.startswith("#") else f"#{t}" for t in copy.get("hashtags", [])] + tags["pool"]))
    copy["hashtags"] = merged[: tags["max_total"]]
    return copy


def caption_text(copy: dict, plan: dict, extra: str | None = None) -> str:
    watch = f"\n\n{extra}" if extra else ""
    credit = "\n\nMovie data & images: TMDB." + (" Streaming data: JustWatch." if extra else "")
    return f"{copy['caption'].strip()}{watch}{credit}\n.\n.\n{' '.join(copy['hashtags'])}"[:2200]
