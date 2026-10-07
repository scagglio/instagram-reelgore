"""Thin TMDB client: horror discovery, details, images."""
from __future__ import annotations

import os
from datetime import date, timedelta

import requests

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p"
HORROR = 27


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

    # ---------- details ----------
    def details(self, movie_id: int) -> dict:
        m = self.get(f"/movie/{movie_id}", append_to_response="credits,images,videos,release_dates,external_ids",
                     include_image_language="en,null")
        crew = m.get("credits", {}).get("crew", [])
        cast = m.get("credits", {}).get("cast", [])
        backdrops = [b["file_path"] for b in m.get("images", {}).get("backdrops", [])[:8]]
        posters = [b["file_path"] for b in m.get("images", {}).get("posters", [])[:3]]
        return {
            "id": m["id"],
            "title": m.get("title"),
            "original_title": m.get("original_title"),
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
