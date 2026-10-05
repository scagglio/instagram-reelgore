"""Publish a carousel via the Instagram Graph API (content publishing)."""
from __future__ import annotations

import os
import time

import requests


class Instagram:
    def __init__(self):
        self.token = os.environ["IG_ACCESS_TOKEN"]
        self.user = os.environ["IG_USER_ID"]
        # graph.facebook.com for a Business account linked to a FB Page (Facebook Login),
        # graph.instagram.com for "Instagram API with Instagram Login".
        host = os.environ.get("IG_GRAPH_HOST", "graph.facebook.com")
        ver = os.environ.get("IG_GRAPH_VERSION", "v23.0")
        self.base = f"https://{host}/{ver}"

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
