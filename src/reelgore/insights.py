"""Weekly performance report: pull Instagram Insights for recent posts, score each content type,
write rotation weights the picker uses, and suggest the best posting time."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

WEIGHTS = Path("data/weights.json")
REPORTS = Path("reports")
CENTRAL = ZoneInfo("America/Chicago")
PACIFIC = ZoneInfo("America/Los_Angeles")

CAROUSEL_METRICS = ["reach", "saved", "shares", "likes", "comments", "total_interactions"]
REEL_METRICS = CAROUSEL_METRICS + ["views", "ig_reels_avg_watch_time"]
TYPES = ["upcoming", "classic", "anniversary"]
# What a reaction is worth: sends and saves tell Instagram the most, likes the least.
SCORE = {"shares": 4, "saved": 3, "comments": 2, "likes": 1}


def kind_type(kind: str) -> str:
    return "upcoming" if kind.startswith("upcoming") else kind


def _value(item: dict):
    if "total_value" in item:
        return item["total_value"].get("value")
    vals = item.get("values") or [{}]
    return vals[0].get("value")


def media_insights(ig, media_id: str, metrics: list[str]) -> dict:
    """Ask for all metrics at once; if Meta rejects one, fall back to asking one at a time."""
    data = ig._try_get(f"{media_id}/insights", metric=",".join(metrics))
    if data and "data" in data:
        return {i["name"]: _value(i) for i in data["data"]}
    out = {}
    for m in metrics:
        d = ig._try_get(f"{media_id}/insights", metric=m)
        if d and d.get("data"):
            out[m] = _value(d["data"][0])
    return out


def score(m: dict) -> float:
    """Weighted engagement per 1,000 accounts reached."""
    reach = m.get("reach") or 0
    if not reach:
        return 0.0
    return sum((m.get(k) or 0) * w for k, w in SCORE.items()) / reach * 1000


def best_hours(ig) -> list[tuple[int, int]] | None:
    """Hours (Central) when followers are online. Meta reports these hours in Pacific time."""
    d = ig._try_get(f"{ig.user}/insights", metric="online_followers", period="lifetime")
    try:
        by_hour = d["data"][0]["values"][0]["value"]
    except Exception:
        return None
    if not by_hour:
        return None
    today = datetime.now(PACIFIC).date()
    out = []
    for h, n in by_hour.items():
        pt = datetime(today.year, today.month, today.day, int(h), tzinfo=PACIFIC)
        out.append((pt.astimezone(CENTRAL).hour, int(n)))
    return sorted(out, key=lambda x: -x[1])


def build_report(ig, history: dict, days: int = 28) -> tuple[str, dict]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    posts = [p for p in history["posts"] if p["date"] >= cutoff and p.get("media_id")]
    rows = []
    for p in posts:
        car = media_insights(ig, p["media_id"], CAROUSEL_METRICS)
        reel = {}
        if (p.get("reel") or {}).get("media_id"):
            reel = media_insights(ig, p["reel"]["media_id"], REEL_METRICS)
        combined = {k: (car.get(k) or 0) + (reel.get(k) or 0) for k in CAROUSEL_METRICS}
        rows.append({"date": p["date"], "type": kind_type(p["kind"]), "title": ", ".join(p.get("titles", [])[:2]),
                     "headline": p.get("headline") or "", "link": p.get("permalink"),
                     "carousel": car, "reel": reel, "all": combined,
                     "score": score(combined), "car_score": score(car), "reel_score": score(reel)})

    # Per-type averages and new rotation weights
    by_type = {t: [r for r in rows if r["type"] == t] for t in TYPES}
    overall = [r["score"] for r in rows if r["all"].get("reach")]
    overall_avg = sum(overall) / len(overall) if overall else 0
    weights, stats = {}, {}
    for t, rs in by_type.items():
        scored = [r["score"] for r in rs if r["all"].get("reach")]
        avg = sum(scored) / len(scored) if scored else 0
        reach = sum(r["all"].get("reach") or 0 for r in rs) / len(rs) if rs else 0
        stats[t] = {"posts": len(rs), "avg_score": round(avg, 1), "avg_reach": round(reach)}
        if len(scored) >= 2 and overall_avg > 0:
            weights[t] = round(min(2.0, max(0.5, avg / overall_avg)), 2)
        else:
            weights[t] = 1.0  # not enough data yet: stay neutral

    # Report
    today = date.today().isoformat()
    lines = [f"# Reel Gore weekly report: {today}", "",
             f"Last {days} days, {len(rows)} posts. **Score** = (shares×4 + saves×3 + comments×2 + likes) per 1,000 reached.", ""]
    if not rows:
        lines += ["No posts with Instagram media IDs in this window yet. The report fills in once a few daily posts are live."]
    else:
        lines += ["## By content type", "", "| Type | Posts | Avg reach (carousel + Reel) | Avg score | New weight |", "|---|---|---|---|---|"]
        for t in TYPES:
            s = stats[t]
            lines.append(f"| {t} | {s['posts']} | {s['avg_reach']:,} | {s['avg_score']} | {weights[t]}× |")
        lines += ["", "Weights above 1× get picked more often in the daily rotation (capped at 2×, floor 0.5×)."
                  " Types with fewer than 2 posts stay at 1×.", ""]

        top = sorted(rows, key=lambda r: -r["score"])[:3]
        lines += ["## Top posts", ""]
        for r in top:
            a = r["all"]
            link = f"[{r['headline'] or r['title']}]({r['link']})" if r["link"] else (r["headline"] or r["title"])
            lines.append(f"- **{r['score']:.0f}**: {link} ({r['type']}, {r['date']}): reach {a.get('reach', 0):,}, "
                         f"{a.get('shares', 0)} shares, {a.get('saved', 0)} saves, {a.get('comments', 0)} comments")
        lines.append("")

        car = [r for r in rows if r["carousel"].get("reach")]
        reels = [r for r in rows if r["reel"].get("reach")]
        if car and reels:
            car_reach = sum(r["carousel"]["reach"] for r in car) / len(car)
            reel_reach = sum(r["reel"]["reach"] for r in reels) / len(reels)
            car_s = sum(r["car_score"] for r in car) / len(car)
            reel_s = sum(r["reel_score"] for r in reels) / len(reels)
            lines += ["## Carousel vs Reel", "",
                      f"- Carousel: avg reach {car_reach:,.0f}, avg score {car_s:.1f}",
                      f"- Reel: avg reach {reel_reach:,.0f}, avg score {reel_s:.1f}"]
            watch = [r["reel"].get("ig_reels_avg_watch_time") for r in reels if r["reel"].get("ig_reels_avg_watch_time")]
            if watch:
                lines.append(f"- Reel avg watch time: {sum(watch) / len(watch) / 1000:.1f}s")
            lines.append("")

    hours = best_hours(ig)
    if hours:
        top3 = hours[:3]
        def fmt(h):
            return datetime(2000, 1, 1, h).strftime("%-I %p")
        lines += ["## When your followers are online (Central)", "",
                  "Busiest hours: " + ", ".join(f"{fmt(h)} ({n:,})" for h, n in top3), ""]
        best = top3[0][0]
        post_h = (best - 1) % 24  # post an hour before the peak so it's warmed up
        utc = datetime.now(CENTRAL).replace(hour=post_h, minute=7).astimezone(ZoneInfo("UTC"))
        current = (utc.minute, utc.hour) == (7, 23)
        cron = f'"{utc.minute} {utc.hour} * * *"'
        advice = ("That's already your schedule, so nothing to change." if current else
                  "To switch, change the first cron line in `.github/workflows/daily-post.yml` to "
                  f"`{cron}` (and move the backups to 30, 70 and 160 minutes later).")
        lines += [f"Suggested posting time: **{fmt(post_h).replace(' ', ':07 ')}** Central, an hour before "
                  f"the peak. {advice}", ""]
    else:
        lines += ["## When your followers are online", "",
                  "Not available yet. Instagram only reports this once the account has 100+ followers "
                  "and the token has `instagram_manage_insights`.", ""]

    if rows and all(not r["all"].get("reach") for r in rows):
        lines += ["> **No insight numbers came back.** The token probably lacks the `instagram_manage_insights` "
                  "permission. Regenerate the Page token with it (same steps as before) and re-run the report.", ""]

    weights_doc = {"updated": today, "window_days": days, "weights": weights, "stats": stats}
    return "\n".join(lines), weights_doc


def run(ig, history_path=Path("data/history.json")) -> Path:
    from .picker import load_history
    history = load_history(history_path)
    report, weights = build_report(ig, history)
    WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
    WEIGHTS.write_text(json.dumps(weights, indent=2))
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"{date.today().isoformat()}.md"
    out.write_text(report)
    print(report)
    print(f"[report] weights -> {weights['weights']}")
    return out
