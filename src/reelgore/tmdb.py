"""Thin TMDB client: horror discovery, details, images."""
from __future__ import annotations

import os
from datetime import date, timedelta

import requests

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p"
HORROR = 27


def is_latin(text: str | None) -> bool:
    """True if the title reads in the Latin alphabet (English, Italian, Spanish, French...)."""
    import unicodedata
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return True
    latin = sum(1 for c in letters if "LATIN" in unicodedata.name(c, ""))
    return latin / len(letters) >= 0.8


class TMDB:
    def __init__(self, token: str | None = None):
        # Accepts either a v4 "read access token" (long JWT) or a v3 API key.
        self.token = token or os.environ.get("TMDB_TOKEN") or os.environ.get("TMDB_API_KEY")
        if not self.token:
            raise RuntimeError("Set TMDB_TOKEN (v4 read token) or TMDB_API_KEY")
        self.s = requests.Session()
        if len(self.token) > 40:
            self.s.headers["Authorization"] = f"Bearer {self.token}"
            self._key = None
        else:
            self._key = self.token

    def get(self, path: str, **params) -> dict:
        if self._key:
            params["api_key"] = self._key
        r = self.s.get(f"{API}{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    # ---------- discovery ----------
    def upcoming_horror(self, days_ahead: int = 120, region: str = "US", pages: int = 3) -> list[dict]:
        today = date.today()
        out = []
        for p in range(1, pages + 1):
            data = self.get(
                "/discover/movie",
                with_genres=HORROR,
                region=region,
                with_release_type="2|3",  # limited + theatrical
                **{
                    "primary_release_date.gte": today.isoformat(),
                    "primary_release_date.lte": (today + timedelta(days=days_ahead)).isoformat(),
                },
                sort_by="popularity.desc",
                include_adult="false",
                page=p,
            )
            out += data.get("results", [])
            if p >= data.get("total_pages", 1):
                break
        return out

    def classic_horror(self, max_year: int, min_votes: int, page: int = 1, keyword_ids: str | None = None) -> list[dict]:
        params = {
            "with_genres": HORROR,
            "primary_release_date.lte": f"{max_year}-12-31",
            "vote_count.gte": min_votes,
            "sort_by": "vote_average.desc",
            "include_adult": "false",
            "page": page,
        }
        if keyword_ids:
            params["with_keywords"] = keyword_ids
        return self.get("/discover/movie", **params).get("results", [])

    def released_on(self, month: int, day: int, year: int, min_votes: int) -> list[dict]:
        d = date(year, month, day).isoformat()
        return self.get(
            "/discover/movie",
            with_genres=HORROR,
            **{"primary_release_date.gte": d, "primary_release_date.lte": d},
            sort_by="popularity.desc",
            include_adult="false",
        ).get("results", [])

    def keyword_id(self, text: str) -> str | None:
        res = self.get("/search/keyword", query=text).get("results", [])
        return str(res[0]["id"]) if res else None

    def find_movie(self, query: str) -> dict | None:
        """Best TMDB match for a typed title. Accepts 'Title', 'Title (1978)', 'Title 1978' or 'tmdb:948'."""
        import re
        q = query.strip()
        m = re.fullmatch(r"tmdb:(\d+)", q, re.I)
        if m:
            return {"id": int(m.group(1))}
        year = None
        m = re.fullmatch(r"(.+?)\s*[\(\[]?((?:19|20)\d{2})[\)\]]?", q)
        if m:
            q, year = m.group(1).strip(), int(m.group(2))
        params = {"query": q, "include_adult": "false"}
        if year:
            params["year"] = year
        results = self.get("/search/movie", **params).get("results", [])
        if not results and year:  # year typed slightly off: retry without it
            results = self.get("/search/movie", query=q, include_adult="false").get("results", [])
        if not results:
            return None

        def rank(r):
            exact = r.get("title", "").lower() == q.lower() or r.get("original_title", "").lower() == q.lower()
            horror = HORROR in r.get("genre_ids", [])
            ry = int((r.get("release_date") or "0")[:4] or 0)
            closeness = -abs(ry - year) if year and ry else 0   # typed year slightly off: nearest wins
            return (exact, horror, closeness, r.get("vote_count", 0))
        return max(results[:10], key=rank)

    # ---------- people ----------
    def find_person(self, name: str) -> dict | None:
        """Best TMDB match for a typed name ('Jamie Lee Curtis', or 'tmdb-person:8944')."""
        import re
        m = re.fullmatch(r"tmdb-person:(\d+)", name.strip(), re.I)
        if m:
            return {"id": int(m.group(1))}
        results = self.get("/search/person", query=name.strip(), include_adult="false").get("results", [])
        if not results:
            return None

        def rank(r):
            exact = r.get("name", "").lower() == name.strip().lower()
            horror_known = any(HORROR in (k.get("genre_ids") or []) for k in r.get("known_for", []))
            return (exact, horror_known, r.get("popularity", 0))
        return max(results[:10], key=rank)

    def person_details(self, person_id: int, max_roles: int = 6) -> dict:
        """Bio facts plus their most notable horror work (acting and directing), best-known first."""
        p = self.get(f"/person/{person_id}", append_to_response="movie_credits,images,external_ids")
        credits = p.get("movie_credits", {})
        horror = {}
        for c in credits.get("cast", []):
            if HORROR in (c.get("genre_ids") or []) and c.get("release_date"):
                horror.setdefault(c["id"], {**c, "role": c.get("character") or ""})
        for c in credits.get("crew", []):
            if HORROR in (c.get("genre_ids") or []) and c.get("release_date") and c.get("job") in ("Director", "Screenplay", "Writer"):
                e = horror.setdefault(c["id"], {**c, "role": ""})
                e["role"] = ", ".join(x for x in [e["role"], c["job"]] if x)
        roles = sorted(horror.values(), key=lambda c: -(c.get("vote_count") or 0))[:max_roles]
        profiles = [i["file_path"] for i in (p.get("images") or {}).get("profiles", [])[:4]]
        return {
            "id": p["id"],
            "name": p.get("name"),
            "birthday": p.get("birthday"),
            "deathday": p.get("deathday"),
            "place_of_birth": p.get("place_of_birth"),
            "known_for_department": p.get("known_for_department"),
            "biography": (p.get("biography") or "")[:1500],
            "profile": p.get("profile_path"),
            "profiles": profiles or ([p["profile_path"]] if p.get("profile_path") else []),
            "wikidata_id": (p.get("external_ids") or {}).get("wikidata_id"),
            "horror_count": len(horror),
            "roles": [{
                "id": r["id"], "title": r.get("title"), "release_date": r.get("release_date"),
                "role": r.get("role"), "poster": r.get("poster_path"),
                "backdrops": [r["backdrop_path"]] if r.get("backdrop_path") else [],
                "overview": (r.get("overview") or "")[:300],
            } for r in roles],
        }

    # ---------- details ----------
    def details(self, movie_id: int) -> dict:
        m = self.get(f"/movie/{movie_id}",
                     append_to_response="credits,images,videos,release_dates,external_ids,alternative_titles,translations",
                     include_image_language="en,null")
        title, original = m.get("title"), m.get("original_title")
        if not is_latin(title):
            # TMDB has no English title on the main record: look for an English alternate title or translation
            alts = (m.get("alternative_titles") or {}).get("titles", [])
            trans = (m.get("translations") or {}).get("translations", [])
            english = [a.get("title") for a in alts if a.get("iso_3166_1") in ("US", "GB", "CA", "AU")] + \
                      [x.get("data", {}).get("title") for x in trans if x.get("iso_639_1") == "en"] + \
                      [a.get("title") for a in alts]
            better = next((e for e in english if e and is_latin(e)), None)
            if better:
                print(f"[tmdb] using English title '{better}' for '{title}'")
                title = better
        crew = m.get("credits", {}).get("crew", [])
        cast = m.get("credits", {}).get("cast", [])
        backdrops = [b["file_path"] for b in m.get("images", {}).get("backdrops", [])[:8]]
        posters = [b["file_path"] for b in m.get("images", {}).get("posters", [])[:3]]
        return {
            "id": m["id"],
            "title": title,
            "original_title": original,
            # Shown in small type under the title when it differs (e.g. Deep Red / Profondo Rosso)
            "aka": original if original and original.strip().lower() != (title or "").strip().lower() else None,
            "english_title": is_latin(title),
            "release_date": m.get("release_date"),
            "runtime": m.get("runtime"),
            "overview": m.get("overview"),
            "tagline": m.get("tagline"),
            "genres": [g["name"] for g in m.get("genres", [])],
            "countries": [c["name"] for c in m.get("production_countries", [])],
            "directors": [c["name"] for c in crew if c.get("job") == "Director"],
            "writers": [c["name"] for c in crew if c.get("department") == "Writing"][:3],
            "makeup_fx": [c["name"] for c in crew if c.get("job") in ("Special Effects Makeup Artist", "Makeup Effects", "Special Makeup Effects Artist")][:3],
            "composer": [c["name"] for c in crew if c.get("job") == "Original Music Composer"][:2],
            "cast": [c["name"] for c in cast[:6]],
            "budget": m.get("budget") or None,
            "revenue": m.get("revenue") or None,
            "vote_average": m.get("vote_average"),
            "vote_count": m.get("vote_count"),
            "poster": m.get("poster_path"),
            "posters": posters,
            "backdrops": backdrops or ([m["backdrop_path"]] if m.get("backdrop_path") else []),
            "tmdb_url": f"https://www.themoviedb.org/movie/{m['id']}",
            "wikidata_id": (m.get("external_ids") or {}).get("wikidata_id"),
            "imdb_id": (m.get("external_ids") or {}).get("imdb_id") or m.get("imdb_id"),
        }

    @staticmethod
    def image_url(path: str, size: str = "original") -> str:
        return f"{IMG}/{size}{path}"

    def download(self, path: str, size: str = "w1280") -> bytes:
        r = requests.get(self.image_url(path, size), timeout=60)
        r.raise_for_status()
        return r.content


def watch_providers(tmdb: "TMDB", movie_id: int, region: str = "US") -> dict:
    """Where to stream / rent / buy in a region (TMDB data powered by JustWatch)."""
    res = tmdb.get(f"/movie/{movie_id}/watch/providers").get("results", {}).get(region, {})

    import re

    def base(name):
        # "Shudder Amazon Channel", "Peacock Premium Plus", "Paramount+ with Showtime" -> one service
        n = re.sub(r"\s+(amazon|apple tv|roku premium|youtube tv)\s+channels?$", "", name, flags=re.I)
        n = re.sub(r"\s+(standard )?with ads$", "", n, flags=re.I)
        return n.strip()

    seen: set[str] = set()

    def norm(key):
        out = []
        for p in sorted(res.get(key, []), key=lambda p: p.get("display_priority", 99)):
            b = base(p["provider_name"])
            if b.lower() in seen:
                continue
            seen.add(b.lower())
            out.append({"name": b, "logo": p.get("logo_path")})
        return out

    stream = norm("flatrate") + norm("free") + norm("ads")
    seen.clear()
    return {"stream": stream,
            "rent": norm("rent"), "buy": norm("buy"), "link": res.get("link")}
