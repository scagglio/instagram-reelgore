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
        raise SystemExit(
            "Couldn't find an Instagram business account for this token. Check that @"
            f"{self.want_handle} is a Professional account linked to the Reel Gore Facebook Page, and that the "
            "token has instagram_basic, instagram_content_publish, pages_show_list, pages_read_engagement."
        )

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
