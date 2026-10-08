# reelgore-agent

Headless Instagram agent for **@reelgore26** (Reel Gore, horror reviews since 2010).
Every day a GitHub Action picks horror movies from TMDB, has Claude write the copy in the Reel Gore voice,
renders a 1080×1350 carousel, and posts it to Instagram. It also posts the same slides as a 9:16 **Reel**
set to a trending scary track from Instagram's music library (see *Music* below).

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
   - `CLAUDE_MODEL` (optional; leave unset to use the newest Sonnet your API key can access)
   - `IG_GRAPH_HOST`: not needed. The host is picked from the token (`IGAA…` uses graph.instagram.com, `EAA…` uses graph.facebook.com)
6. **Test**: go to Actions > *ReelGore daily carousel* > Run workflow, keep **dry_run** checked, and download the
   `reelgore-…` artifact to review the slides and caption. Run again with dry_run unchecked to post for real.

The schedule runs daily at 6:07 PM Central, with backup attempts at 6:37, 7:17 and 8:47 PM, because GitHub sometimes delays or drops scheduled runs. Only the first one that runs posts; the rest see the scheduled post in `data/history.json` and skip. Manual runs never block the scheduled post.

## If Instagram blocks posting

If Instagram's anti-spam guard returns "Action is blocked" (error code 4 / subcode 2207051), usually after a burst of
posts, the agent stops, writes `data/cooldown.json` and pauses all posting for 24 hours. Backup schedule times and
manual runs are skipped until then, because retrying can extend a block. To override early, delete that file.
The log also prints how many API posts Instagram counted in the last 24 hours.

## International films and titles

International horror is welcome. If TMDB's main title isn't in English (e.g. Russian or Korean script), the agent
looks for an English alternate title or translation and uses it, with the original shown in small type under the
title on slides ("ORIGINAL TITLE Profondo Rosso"). Automatic posts skip films that have no English title at all;
movies you type in yourself are always kept. Original titles in Japanese, Korean, Chinese and similar scripts
appear in captions only, since the slide font can't draw them.

## Did you know? (trivia slide)

Deep-dive posts (classic, anniversary, your single-movie picks, upcoming spotlights) get a **Did you know?** slide
with two behind-the-scenes facts instead of a cast-and-crew rundown. To keep the trivia real, the agent pulls the
film's English Wikipedia article (production, costume, casting, filming, release, legacy sections) and Claude may
only use facts found there, reworded. If a film has no article, the facts come from TMDB numbers only (budget, box
office, runtime). List posts (upcoming roundups, picks lists) don't get a trivia slide.

## Post your own movies (manual run)

**Actions → ReelGore daily post → Run workflow** has a **movies** box. Type a comma-separated list:

```
Halloween (1978), The Thing, Hereditary, Suspiria 1977
```

- **One movie**: a "Reel Gore Pick" deep dive with a skull verdict and a Where to Watch slide. If it isn't out
  yet, you get an upcoming spotlight instead.
- **Several movies** (up to 8): a "Reel Gore Picks" list, one slide per film in your order. Fill in **list_title**
  (e.g. *Slashers for a rainy night*) and the cover uses it.
- Add the year for remakes and shared titles: `Halloween (1978)` vs `Halloween (2018)`. `tmdb:948` also works.
  If the typed year is slightly off, the nearest one wins.
- Titles that can't be found are skipped and listed in the run's summary. Use **dry_run** first to check.
- The box overrides "What to post". Leave it empty for the normal automatic pick. Scheduled runs ignore it.

## Spotlight one actor, actress or filmmaker (manual run)

Type **one** name in the **person** box (e.g. `Jamie Lee Curtis`). One person per post; commas or "&" are rejected.

The carousel: a **Horror Icon** cover with their portrait → who they are → a **Did you know?** trivia slide
(from their Wikipedia career, early-life and awards sections; personal life is skipped) → their 3 most notable
horror roles, one slide each → **Where to start** → a pick-one question pitting two roles against each other.

- Only people with horror credits on TMDB qualify (it's a horror account). Directors and writers count too.
- If two people share a name, use their TMDB id: `tmdb-person:8944` (the number in their TMDB page address).
- The log warns if you've spotlighted the same person before.
- The person box overrides the movies box and "What to post".

## Music (Reels)

Each Reel gets a **licensed Instagram track** through Meta's Instagram Audio API (`GET /ig_audio`, then
`audio_configuration` on the Reel):

1. It checks Instagram's **trending** audio for a track whose title or artist matches a horror keyword (scary, creepy, haunted, phonk…).
2. If nothing trending fits, it uses the top result of the searches in `config/brand.yaml` → `music.searches`.
3. Tracks aren't reused within 14 days (`no_repeat_days`), and the chosen track is logged in `data/history.json`.
4. If Instagram rejects the track (not licensed for this account or region), the Reel posts with the agent's own
   generated soundtrack instead, so a post is never lost.

Controls:
- Force a specific song: set the repo variable `IG_AUDIO_ID` to its audio ID (the log prints IDs of tracks it finds).
- Always use the generated soundtrack: set `music.use_instagram_music: false`.
- Turn Reels off completely: set the repo variable `POST_REEL` = `false`.

Requirements: a Facebook Login token (`EAA…`, which you already use) with `instagram_basic` + `instagram_content_publish`.
Meta notes the API library can differ from the app's. Business accounts in particular often get a smaller, more
commercial-safe catalog than Creator accounts, so hit songs may not appear.

## Daily Story teaser

After the main posts go out, the agent publishes a still-image **Story** (1080×1920) to Instagram and the Facebook
Page: the day's cover, tilted like a dropped Polaroid, a **NEW POST** banner (plus the Night badge in October), and
"Swipe through it on our profile". Everything sits inside Instagram's safe zones, clear of the username and reply bar.

- The API can't add link, poll or question stickers, so the Story is a teaser. Add a sticker by hand in the app if you like.
- A failed Story never fails the run (the posts are already live); the reason shows in the run summary.
  Instagram's docs ask for a user token for Stories, so if a Page token is refused, the summary will say so.
- Turn it off with the repo variable `POST_STORY` = `false`, or per platform under `stories:` in `config/brand.yaml`.

## Facebook cross-posting

Every post also goes to the **Reel Gore Facebook Page**, using the same token:

- The slides as one multi-photo post, and the Reel as a Facebook Reel.
- The caption is trimmed for Facebook: 4 hashtags plus a plug for the Instagram account.
- The Page is found automatically as the one linked to @reelgore26 (set `FB_PAGE_ID` to override).
- The Facebook Reel keeps the generated soundtrack, because Instagram's licensed music doesn't carry over to Facebook.
- If Facebook fails, the Instagram posts are still live; the run is marked failed so you notice.
- Turn it off with the repo variable `POST_FACEBOOK` = `false`, or adjust it under `facebook:` in `config/brand.yaml`.

The token also needs **`pages_manage_posts`** (plus `pages_show_list` and `pages_read_engagement`, which you already have).

## Where to watch / own it (affiliate links)

Classic and anniversary posts get a **Where to watch** slide before the final slide. It shows the streaming services
(with logos) from TMDB's JustWatch data, plus an **Own it on 4K: link in bio** box. Upcoming films are skipped
because they aren't out yet.

Instagram captions can't hold clickable links, so the links go in two places:
- **Link-in-bio page**: `docs/index.html` is rebuilt after every post, listing each featured film with streaming
  services and your affiliate links. Host it free with GitHub Pages: repo **Settings → Pages → Deploy from a branch →
  `main` / `/docs`**. Your link is `https://scagglio.github.io/instagram-reelgore/`; put it in the Instagram bio.
- **Facebook post**: clickable "where to watch" and "own it" links, with an `#ad` disclosure.

Setup:
1. Join **Amazon Associates** (affiliate-program.amazon.com) and add your tag (like `reelgore-20`) as the repo variable
   `AMAZON_ASSOCIATE_TAG`. Without a tag, the slide shows streaming services only, with no "own it" links.
2. Optional, in `config/brand.yaml` → `affiliate:`:
   - `provider_links`: affiliate URLs for streaming services you're approved for (e.g. Shudder).
   - `extra_shops`: boutique labels (Vinegar Syndrome, Arrow, Shout! Factory) with affiliate programs.
   - `pinned_links`: always-on buttons at the top of the page, like your Etsy merch shop.

Disclosures are built in (`#ad` on Facebook, an Amazon Associates statement on the page). Amazon requires the
statement wherever its links appear, and the FTC requires clear affiliate disclosure.

## Engagement features

**31 Nights of Horror (October).** From Oct 1–31, every daily post is a numbered entry: a **NIGHT 06/31** badge on
the cover, `#31NightsOfHorror` as the first hashtag, "Night 6" in the caption's opening line, and a tease for
tomorrow (Night 31 gets a send-off). Add or change series under `series:` in `config/brand.yaml`.

**Pick-one questions.** Every caption ends with a two-sided debate question ("Original or remake? Pick one.") and
the final slide asks the same kind of question. Open-ended "thoughts?" endings are banned. Edit the style
examples under `engagement.cta_examples`.

**Weekly report** (`.github/workflows/weekly-report.yml`, Mondays 9:07 AM Central, or run it by hand):
- Pulls Instagram Insights (reach, shares, saves, comments, likes, Reel watch time) for the last 28 days of posts.
- Scores each post: (shares×4 + saves×3 + comments×2 + likes) per 1,000 reached.
- Writes `data/weights.json`. The daily rotation then picks better-performing types more often (0.5×–2×), and
  avoids repeating yesterday's type. Types with fewer than 2 posts stay neutral.
- Shows when your followers are online and suggests a posting time.
- Saves the report to `reports/` and opens a GitHub issue with it, so GitHub emails it to you.
- Needs the **`instagram_manage_insights`** permission on the token.

## Run locally

```bash
pip install -r requirements.txt
export PYTHONPATH=src
python -m reelgore.main demo                        # offline preview: slides + reel.mp4 -> out/demo/
TMDB_TOKEN=... ANTHROPIC_API_KEY=... python -m reelgore.main plan --type classic   # -> out/
```

## Notes

- Claude may only state facts that TMDB returned (dates, cast, crew, runtime, plot). Opinions and the skull verdict are its own.
- Captions credit TMDB, as their API terms require. Posters and stills belong to the studios. Using them for commentary and review
  is common practice, but it is not guaranteed; if a post gets flagged, switch `cover`/`movie_slide` to backdrops only or to text-only layouts.
- Long-lived Instagram tokens expire after about 60 days. Refresh yours before it lapses, or the publish step will fail.
- Fonts: Inter (OFL) ships in `assets/fonts`. The workflow downloads Bebas Neue (OFL) for headlines and falls back to Inter Display Black.
