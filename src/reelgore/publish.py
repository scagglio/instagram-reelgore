"""Publish a carousel via the Instagram Graph API (content publishing)."""
from __future__ import annotations

import os
import time

import requests


class Instagram:
    def __init__(self):
        # Clean up common copy/paste damage in secrets: whitespace, quotes, "Bearer " prefix.
        tok = os.environ["IG_ACCESS_TOKEN"].strip().strip('"').strip("'").strip()
        if tok.lower().startswith("bearer "):
            tok = tok[7:].strip()
        if tok.isdigit() or len(tok) < 60:
            raise SystemExit(
                f"IG_ACCESS_TOKEN doesn't look like an access token (len={len(tok)}, starts '{tok[:4]}'). "
                "It should be a long EAA... or IGAA... string; an ID (all digits) was probably pasted instead."
            )
        self.token = tok
        self.user = (os.environ.get("IG_USER_ID") or "").strip().strip('"').strip("'")
        self.want_handle = (os.environ.get("IG_USERNAME") or "reelgore26").lstrip("@").lower()
        # IGAA... tokens = "Instagram API with Instagram Login" -> graph.instagram.com
        # EAA...  tokens = Facebook Login (IG account linked to a Page) -> graph.facebook.com
        auto = "graph.instagram.com" if tok.startswith("IG") else "graph.facebook.com"
        host = (os.environ.get("IG_GRAPH_HOST") or "").strip() or auto
        if host != auto:
            print(f"[publish] note: IG_GRAPH_HOST={host} but token looks like it belongs to {auto}; using {auto}")
            host = auto
        ver = (os.environ.get("IG_GRAPH_VERSION") or "").strip() or "v23.0"
        self.base = f"https://{host}/{ver}"
        print(f"[publish] host={host} token_prefix={tok[:4]}… token_len={len(tok)} user_id_len={len(self.user)}")
        self.user = self._resolve_user()

    # ---------- account resolution ----------
    def _try_get(self, path, **params):
        params["access_token"] = self.token
        r = requests.get(f"{self.base}/{path}", params=params, timeout=60)
        return r.json() if r.ok else None

    def _resolve_user(self) -> str:
        """Make sure we're posting as the Instagram business account; discover it if IG_USER_ID is wrong."""
        if self.user:
            info = self._try_get(self.user, fields="id,username")
            if info and info.get("username"):
                print(f"[publish] IG_USER_ID ok -> @{info['username']}")
                return info["id"]
            # Maybe it's the Facebook Page ID: ask the Page for its linked IG account.
            page = self._try_get(self.user, fields="name,instagram_business_account{id,username}")
            if page and page.get("instagram_business_account"):
                ig = page["instagram_business_account"]
                print(f"[publish] IG_USER_ID is the Page '{page.get('name')}'; using its IG account "
                      f"@{ig.get('username')} ({ig['id']}). Update the IG_USER_ID secret to {ig['id']}.")
                return ig["id"]
        if "instagram.com" in self.base:
            me = self._try_get("me", fields="user_id,username")
            if me and me.get("user_id"):
                print(f"[publish] using @{me.get('username')} ({me['user_id']}) from the token")
                return str(me["user_id"])
        else:
            # Page token: the token itself is the Page.
            me = self._try_get("me", fields="name,instagram_business_account{id,username}")
            if me and me.get("instagram_business_account"):
                ig = me["instagram_business_account"]
                print(f"[publish] using @{ig.get('username')} ({ig['id']}) linked to Page '{me.get('name')}'")
                return ig["id"]
            # User token: scan the Pages this user manages.
            pages = self._try_get("me/accounts", fields="name,instagram_business_account{id,username}", limit=100)
            found = [p["instagram_business_account"] | {"page": p.get("name")}
                     for p in (pages or {}).get("data", []) if p.get("instagram_business_account")]
            match = [a for a in found if (a.get("username") or "").lower() == self.want_handle] or \
                    (found if len(found) == 1 else [])
            if match:
                ig = match[0]
                print(f"[publish] found @{ig.get('username')} ({ig['id']}) via Page '{ig['page']}'. "
                      f"Set the IG_USER_ID secret to {ig['id']}.")
                return ig["id"]
            if found:
                listing = ", ".join(f"@{a.get('username')}={a['id']}" for a in found)
                raise SystemExit(f"Several IG accounts on this token, none named @{self.want_handle}: {listing}")
        self._diagnose()
        raise SystemExit(
            "Couldn't find an Instagram business account for this token. Check that @"
            f"{self.want_handle} is a Professional account linked to the Reel Gore Facebook Page, and that the "
            "token has instagram_basic, instagram_content_publish, pages_show_list, pages_read_engagement."
        )

    def _diagnose(self):
        """Print what the token can actually see, so setup problems are obvious in the log."""
        def raw(path, **params):
            params["access_token"] = self.token
            try:
                r = requests.get(f"{self.base}/{path}", params=params, timeout=60)
                return r.json()
            except Exception as e:
                return {"error": str(e)}
        me = raw("me", fields="id,name")
        print(f"[diagnose] token belongs to: {me.get('name')} (error: {me.get('error', {}).get('message') if isinstance(me.get('error'), dict) else me.get('error')})")
        perms = raw("me/permissions").get("data", [])
        granted = sorted(p["permission"] for p in perms if p.get("status") == "granted")
        print(f"[diagnose] granted permissions: {', '.join(granted) or 'none visible'}")
        need = {"instagram_basic", "instagram_content_publish", "pages_show_list", "pages_read_engagement"}
        if perms and need - set(granted):
            print(f"[diagnose] MISSING permissions: {', '.join(sorted(need - set(granted)))}")
        pages = raw("me/accounts", fields="name,instagram_business_account{id,username}", limit=100)
        if "error" in pages:
            print(f"[diagnose] me/accounts error: {pages['error']}")
        for p in pages.get("data", []):
            ig = p.get("instagram_business_account")
            print(f"[diagnose] Page '{p.get('name')}' -> " + (f"@{ig.get('username')} ({ig['id']})" if ig else "NO linked Instagram account"))
        if not pages.get("data"):
            print("[diagnose] token can see no Pages. Re-authorize the app and tick the Reel Gore Page + @reelgore26.")

    def _post(self, path, **data):
        data["access_token"] = self.token
        r = requests.post(f"{self.base}/{path}", data=data, timeout=60)
        if not r.ok:
            raise RuntimeError(f"IG {path} failed: {r.status_code} {r.text}")
        return r.json()

    def _get(self, path, **params):
        params["access_token"] = self.token
        r = requests.get(f"{self.base}/{path}", params=params, timeout=60)
        r.raise_for_status()
        return r.json()

    def _wait(self, cid, tries=30):
        for _ in range(tries):
            st = self._get(cid, fields="status_code").get("status_code")
            if st == "FINISHED":
                return
            if st in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"container {cid} status {st}")
            time.sleep(5)
        raise TimeoutError(f"container {cid} never finished")

    # ---------- Instagram Audio API (licensed music for Reels) ----------
    def search_audio(self, query: str | None = None, audio_type: str = "music") -> list[dict]:
        """GET /ig_audio. No query = Instagram's trending audio. Requires a Facebook Login (EAA) token."""
        params = {"audio_type": audio_type, "user_id": self.user, "access_token": self.token}
        if query:
            params["search_query"] = query[:100]
        r = requests.get(f"{self.base}/ig_audio", params=params, timeout=60)
        if not r.ok:
            raise RuntimeError(f"ig_audio failed: {r.status_code} {r.text}")
        body = r.json()
        items = body.get("data", body if isinstance(body, list) else [])
        out = []
        for it in items:
            aid = it.get("id") or it.get("audio_id") or it.get("audio_asset_id")
            if not aid:
                continue
            title = it.get("title") or it.get("name") or it.get("song_name") or ""
            artist = it.get("artist") or it.get("display_artist") or it.get("artist_name") or ""
            out.append({"id": str(aid), "title": str(title), "artist": str(artist)})
        return out

    def pick_music(self, music_cfg: dict, avoid: set[str]) -> dict | None:
        """Trending track that matches horror keywords; otherwise the top result of the horror searches."""
        pinned = (os.environ.get("IG_AUDIO_ID") or "").strip()
        if pinned:
            return {"id": pinned, "title": "(pinned via IG_AUDIO_ID)", "artist": ""}
        keywords = [k.lower() for k in music_cfg.get("keywords", [])]
        try:
            trending = self.search_audio(None)
            print(f"[music] {len(trending)} trending tracks")
            for t in trending:
                text = f"{t['title']} {t['artist']}".lower()
                if t["id"] not in avoid and any(k in text for k in keywords):
                    t["source"] = "trending"
                    return t
        except Exception as e:
            print(f"[music] trending lookup failed: {e}")
        for q in music_cfg.get("searches", []):
            try:
                hits = [h for h in self.search_audio(q) if h["id"] not in avoid]
            except Exception as e:
                print(f"[music] search '{q}' failed: {e}")
                continue
            if hits:
                hits[0]["source"] = f"search:{q}"
                return hits[0]
        return None

    def reel(self, video_path, caption: str, video_url: str | None = None,
             audio_id: str | None = None, music_volume: int = 100) -> tuple[str, str | None]:
        """Publish a Reel. Uploads the file directly (resumable upload); falls back to video_url.
        With audio_id, Instagram's licensed track replaces our soundtrack (video audio muted)."""
        import json as _json
        from pathlib import Path
        data = Path(video_path).read_bytes()
        ver = self.base.rsplit("/", 1)[-1]
        extra = {}
        if audio_id:
            extra["audio_configuration"] = _json.dumps(
                {"audio_id": audio_id, "audio_volume": music_volume, "video_volume": 0})

        def create(**kw):
            try:
                return self._post(f"{self.user}/media", media_type="REELS", caption=caption,
                                  share_to_feed="true", **extra, **kw)
            except RuntimeError as e:
                if not extra:
                    raise
                # Track not licensed for this account/region, etc. -> post with our own soundtrack.
                print(f"[music] Instagram rejected the track ({e}); using the generated soundtrack instead")
                extra.clear()
                return self._post(f"{self.user}/media", media_type="REELS", caption=caption,
                                  share_to_feed="true", **kw)

        try:
            c = create(upload_type="resumable")
            cid = c["id"]
            up = c.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{ver}/{cid}"
            r = requests.post(up, data=data, timeout=300, headers={
                "Authorization": f"OAuth {self.token}",
                "offset": "0",
                "file_size": str(len(data)),
            })
            if not r.ok:
                raise RuntimeError(f"upload failed: {r.status_code} {r.text}")
            print(f"[publish] reel uploaded ({len(data) // 1024} KB), container {cid}")
        except Exception as e:
            if not video_url:
                raise
            print(f"[publish] resumable upload failed ({e}); trying video_url")
            cid = create(video_url=video_url)["id"]
        self._wait(cid, tries=72)  # video processing can take a few minutes
        pub = self._post(f"{self.user}/media_publish", creation_id=cid)
        mid = pub["id"]
        self.last_reel_music = bool(extra)
        try:
            link = self._get(mid, fields="permalink").get("permalink")
        except Exception:
            link = None
        return mid, link

    def story(self, image_url: str) -> str:
        """Publish a still-image Instagram Story (stickers like links/polls can't be added through the API)."""
        c = self._post(f"{self.user}/media", media_type="STORIES", image_url=image_url)
        self._wait(c["id"])
        return self._post(f"{self.user}/media_publish", creation_id=c["id"])["id"]

    def carousel(self, image_urls: list[str], caption: str) -> tuple[str, str | None]:
        if not 2 <= len(image_urls) <= 10:
            raise ValueError("Carousel needs 2-10 images")
        children = []
        for url in image_urls:
            c = self._post(f"{self.user}/media", image_url=url, is_carousel_item="true")
            children.append(c["id"])
        for c in children:
            self._wait(c)
        parent = self._post(f"{self.user}/media", media_type="CAROUSEL",
                            children=",".join(children), caption=caption)
        self._wait(parent["id"])
        pub = self._post(f"{self.user}/media_publish", creation_id=parent["id"])
        mid = pub["id"]
        try:
            link = self._get(mid, fields="permalink").get("permalink")
        except Exception:
            link = None
        return mid, link
