# reelgore-agent

Headless Instagram agent for **@reelgore26** (Reel Gore, horror reviews since 2010).
Every day a GitHub Action picks horror movies from TMDB, has Claude write the copy in the Reel Gore voice,
renders a 1080×1350 carousel, and posts it to Instagram.

## What it posts

| Type | Format | When |
|---|---|---|
| **Upcoming** | "Coming to haunt you" roundup of 4–6 horror releases in the next 120 days (or a single-film spotlight if fewer are scheduled) | Rotation |
| **Classic** | "From the Crypt" deep dive on a pre-2000 horror film, with a rotating sub-genre theme (slasher, Universal monsters, giallo, 80s practical FX, etc.) and a 1–5 skull verdict | Rotation |
| **Anniversary** | "X years ago today" for a horror film released on today's date at a milestone (10, 20, 25, 30… years) | Rotation, and **always** on 25/50/75/100-year milestones |

Rotation is by day of year: upcoming, then classic, then anniversary. If no anniversary qualifies that day, it posts a classic instead.
Movies are never repeated within 365 days (upcoming roundups avoid repeats for 14 days). See `data/history.json`.

Tune everything in `config/brand.yaml`: voice, themes, milestone years, palette, hashtags, slide count.

## Setup

1. **Create the repo** `scagglio/reelgore-agent` and push these files. It must be **public**:
   Instagram downloads each slide from a public URL, and the workflow hosts slides on the `media` branch through `raw.githubusercontent.com`.
2. **TMDB**: create a free account, then go to Settings > API and copy the **API Read Access Token**.
3. **Instagram**: @reelgore26 must be a Professional (Business or Creator) account. Get a long-lived token with
   `instagram_business_basic` + `instagram_business_content_publish` (Instagram Login), or
   `instagram_basic` + `instagram_content_publish` (Facebook Login via the Reel Gore Page). You can reuse the
   Meta app from the 3d Charged agent and add @reelgore26 as another account.
4. **Repo secrets** (Settings > Secrets and variables > Actions):
   - `TMDB_TOKEN`
   - `ANTHROPIC_API_KEY`
   - `IG_ACCESS_TOKEN`
   - `IG_USER_ID` (the Instagram professional account ID, not the handle)
5. **Optional repo variables**:
   - `CLAUDE_MODEL` (default `claude-sonnet-4-5`)
   - `IG_GRAPH_HOST`: `graph.instagram.com` if you use Instagram Login, otherwise leave it as the default `graph.facebook.com`
6. **Test**: go to Actions > *ReelGore daily carousel* > Run workflow, keep **dry_run** checked, and download the
   `reelgore-…` artifact to review the slides and caption. Run again with dry_run unchecked to post for real.

The schedule runs daily at 6:07 PM Central (`cron: "7 23 * * *"`, UTC).

## Run locally

```bash
pip install -r requirements.txt
export PYTHONPATH=src
python -m reelgore.main demo                        # offline design preview -> out/demo/
TMDB_TOKEN=... ANTHROPIC_API_KEY=... python -m reelgore.main plan --type classic   # -> out/
```

## Notes

- Claude may only state facts that TMDB returned (dates, cast, crew, runtime, plot). Opinions and the skull verdict are its own.
- Captions credit TMDB, as their API terms require. Posters and stills belong to the studios. Using them for commentary and review
  is common practice, but it is not guaranteed; if a post gets flagged, switch `cover`/`movie_slide` to backdrops only or to text-only layouts.
- Long-lived Instagram tokens expire after about 60 days. Refresh yours before it lapses, or the publish step will fail.
- Fonts: Inter (OFL) ships in `assets/fonts`. The workflow downloads Bebas Neue (OFL) for headlines and falls back to Inter Display Black.
