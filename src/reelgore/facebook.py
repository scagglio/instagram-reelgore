"""Cross-post to the Reel Gore Facebook Page: the slides as a multi-photo post, and the Reel as a Facebook Reel."""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests


class FacebookPage:
    def __init__(self, user_token: str, ig_user_id: str, ver: str = "v23.0"):
        self.base = f"https://graph.facebook.com/{ver}"
        self.ver = ver
        self.page_id, self.token, self.name = self._resolve(user_token, ig_user_id)
        print(f"[facebook] posting as Page '{self.name}' ({self.page_id})")

    # ---------- setup ----------
    def _get(self, path, token, **params):
        params["access_token"] = token
        r = requests.get(f"{self.base}/{path}", params=params, timeout=60)
        return r.json() if r.ok else {"error": r.text}

    def _resolve(self, token: str, ig_user_id: str):
        """Find the Page linked to the IG account and get a Page token (needed to post as the Page)."""
        pinned = (os.environ.get("FB_PAGE_ID") or "").strip()
        accounts = self._get("me/accounts", token, fields="id,name,access_token,instagram_business_account", limit=100)
        for p in accounts.get("data", []):
            linked = (p.get("instagram_business_account") or {}).get("id")
            if (pinned and p["id"] == pinned) or (not pinned and linked == ig_user_id):
                return p["id"], p["access_token"], p.get("name")
        # The token may already be a Page token (e.g. the never-expiring one): "me" is then the Page.
        me = self._get("me", token, fields="id,name,instagram_business_account")
        if (me.get("instagram_business_account") or {}).get("id") == ig_user_id or (pinned and me.get("id") == pinned):
            return me["id"], token, me.get("name")
        raise RuntimeError(
            "Couldn't find the Facebook Page linked to this Instagram account. "
            "The token needs pages_show_list, pages_read_engagement and pages_manage_posts "
            f"(me/accounts said: {accounts.get('error') or 'no matching Page'})."
        )

    def _post(self, path, **data):
        data["access_token"] = self.token
        r = requests.post(f"{self.base}/{path}", data=data, timeout=120)
        if not r.ok:
            raise RuntimeError(f"FB {path} failed: {r.status_code} {r.text}")
        return r.json()

    # ---------- posts ----------
    def photos(self, image_urls: list[str], message: str) -> str:
        """Multi-photo feed post: upload each photo unpublished, then attach them all to one post."""
        ids = []
        for url in image_urls:
            ids.append(self._post(f"{self.page_id}/photos", url=url, published="false")["id"])
        data = {"message": message}
        for i, pid in enumerate(ids):
            data[f"attached_media[{i}]"] = f'{{"media_fbid":"{pid}"}}'
        post = self._post(f"{self.page_id}/feed", **data)
        print(f"[facebook] photo post published: {post['id']}")
        return post["id"]

    def photo_story(self, image_url: str) -> str:
        """Facebook Page Story from a still image: upload unpublished, then publish it as a story."""
        photo = self._post(f"{self.page_id}/photos", url=image_url, published="false")
        story = self._post(f"{self.page_id}/photo_stories", photo_id=photo["id"])
        sid = story.get("post_id") or story.get("id") or photo["id"]
        print(f"[facebook] story published: {sid}")
        return sid

    def reel(self, video_path: Path, description: str) -> str:
        """Facebook Reels publishing: start -> upload bytes -> finish (publish)."""
        data = Path(video_path).read_bytes()
        start = self._post(f"{self.page_id}/video_reels", upload_phase="start")
        vid = start["video_id"]
        up = start.get("upload_url") or f"https://rupload.facebook.com/video-upload/{self.ver}/{vid}"
        r = requests.post(up, data=data, timeout=300, headers={
            "Authorization": f"OAuth {self.token}",
            "offset": "0",
            "file_size": str(len(data)),
        })
        if not r.ok:
            raise RuntimeError(f"FB reel upload failed: {r.status_code} {r.text}")
        self._post(f"{self.page_id}/video_reels", upload_phase="finish", video_id=vid,
                   video_state="PUBLISHED", description=description)
        # Processing is async; wait briefly so the log shows whether it went live.
        for _ in range(24):
            st = self._get(vid, self.token, fields="status").get("status", {})
            phase = (st.get("video_status") or "").lower()
            if phase in ("ready", "published"):
                break
            if phase == "error":
                raise RuntimeError(f"FB reel processing error: {st}")
            time.sleep(5)
        print(f"[facebook] reel published: {vid}")
        return vid
