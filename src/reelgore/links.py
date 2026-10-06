"""Build the link-in-bio page (docs/index.html) from post history. Served free by GitHub Pages."""
from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path

PAGE = Path("docs/index.html")
IMG = "https://image.tmdb.org/t/p/w342"


def _e(s) -> str:
    return html.escape(str(s or ""), quote=True)


def build_links_page(cfg: dict, history_path: Path = Path("data/history.json")) -> Path:
    acfg = cfg.get("affiliate", {})
    acct = cfg["account"]
    posts = json.loads(history_path.read_text())["posts"] if history_path.exists() else []
    items = [p for p in reversed(posts) if p.get("watch")][: acfg.get("page_items", 30)]

    shop = "".join(
        f'<a class="btn shop" href="{_e(s["url"])}" rel="sponsored noopener" target="_blank">{_e(s["label"])}</a>'
        for s in acfg.get("pinned_links", []) or [])

    cards = []
    for p in items:
        w = p["watch"]
        poster = f'<img src="{IMG}{_e(p["poster"])}" alt="" loading="lazy" onerror="this.style.visibility=\'hidden\'">' if p.get("poster") else '<div class="ph"></div>'
        stream = ""
        if w.get("stream"):
            chips = "".join(
                (f'<a class="chip" href="{_e(s["url"])}" rel="sponsored noopener" target="_blank">{_e(s["name"])}</a>'
                 if s.get("url") else f'<span class="chip">{_e(s["name"])}</span>')
                for s in w["stream"])
            stream = f'<div class="row"><span class="lbl">Stream</span>{chips}</div>'
        elif w.get("rent"):
            stream = f'<div class="row"><span class="lbl">Rent</span><span class="chip">{_e(", ".join(w["rent"]))}</span></div>'
        own = "".join(
            f'<a class="btn" href="{_e(o["url"])}" rel="sponsored noopener" target="_blank">{_e(o["label"])}</a>'
            for o in w.get("own", []))
        ig = f'<a class="post" href="{_e(p["permalink"])}" target="_blank">See the post</a>' if p.get("permalink") else ""
        cards.append(f'''
      <article class="card">
        {poster}
        <div class="info">
          <h2>{_e(w["title"])} <span class="yr">{_e(w.get("year"))}</span></h2>
          <div class="date">Posted {_e(p["date"])}</div>
          {stream}
          <div class="own">{own}</div>
          {ig}
        </div>
      </article>''')

    empty = '<p class="empty">Fresh links show up here after the next classic or anniversary post.</p>'
    body = "".join(cards) or empty
    disclosure = _e(acfg.get("page_disclosure",
                             "Some links are affiliate links. As an Amazon Associate we earn from qualifying purchases."))
    handle = acct["handle"].lstrip("@")
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(acct["name"])} | Where to watch</title>
<meta name="description" content="Where to stream and own every film featured on {_e(acct["handle"])}.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  :root {{ --ink:#0B0B0D; --card:#16121a; --blood:#B3121B; --bone:#F2E6D0; --rust:#D9663B; --mute:#9b8f86; }}
  * {{ box-sizing:border-box }}
  body {{ margin:0; background:var(--ink); color:var(--bone); font:16px/1.5 Inter,system-ui,sans-serif; }}
  header {{ text-align:center; padding:36px 16px 20px; border-bottom:6px solid var(--blood); }}
  h1 {{ font:400 64px/0.9 "Bebas Neue",Impact,sans-serif; margin:0; letter-spacing:1px; }}
  h1 span {{ color:var(--blood) }}
  .tag {{ color:var(--mute); margin:8px 0 18px }}
  .links {{ display:flex; flex-direction:column; gap:10px; max-width:520px; margin:0 auto }}
  main {{ max-width:720px; margin:0 auto; padding:24px 16px 48px; display:grid; gap:16px }}
  .card {{ display:grid; grid-template-columns:110px 1fr; gap:16px; background:var(--card); border-radius:14px; padding:14px; }}
  .card img, .ph {{ width:110px; aspect-ratio:2/3; object-fit:cover; border-radius:8px; background:#222 }}
  h2 {{ font:400 32px/1 "Bebas Neue",Impact,sans-serif; margin:2px 0 4px }}
  .yr {{ color:var(--mute) }}
  .date {{ color:var(--mute); font-size:13px; margin-bottom:10px }}
  .row {{ display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-bottom:10px }}
  .lbl {{ color:var(--rust); font-weight:700; font-size:12px; letter-spacing:1px; text-transform:uppercase; margin-right:4px }}
  .chip {{ background:#2a2228; color:var(--bone); padding:4px 10px; border-radius:999px; font-size:14px; text-decoration:none }}
  .own {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:8px }}
  .btn {{ display:block; text-align:center; background:var(--blood); color:var(--bone); font-weight:700; text-decoration:none;
         padding:10px 14px; border-radius:10px; }}
  .btn:hover {{ filter:brightness(1.15) }}
  .shop {{ background:transparent; border:2px solid var(--blood); padding:12px }}
  .post {{ color:var(--mute); font-size:14px }}
  .empty {{ color:var(--mute); text-align:center }}
  footer {{ color:var(--mute); font-size:13px; text-align:center; padding:0 16px 40px; max-width:640px; margin:0 auto }}
  footer a {{ color:var(--mute) }}
  @media (max-width:480px) {{ .card {{ grid-template-columns:84px 1fr }} .card img, .ph {{ width:84px }} h1 {{ font-size:52px }} }}
</style></head>
<body>
<header>
  <h1>REEL <span>GORE</span></h1>
  <p class="tag">{_e(acct.get("tagline", ""))} Where to stream and own every film we feature.</p>
  <div class="links">
    <a class="btn" href="https://www.instagram.com/{_e(handle)}/" target="_blank">Follow {_e(acct["handle"])} on Instagram</a>
    {shop}
  </div>
</header>
<main>{body}
</main>
<footer>{disclosure}<br>Streaming data from <a href="https://www.justwatch.com" target="_blank">JustWatch</a> via TMDB.
Updated {date.today().isoformat()}.</footer>
</body></html>
''')
    print(f"[links] link-in-bio page updated ({len(items)} films) -> {PAGE}")
    return PAGE
