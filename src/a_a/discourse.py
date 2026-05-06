from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx


def _markdown_upload_alt(original: Any, fallback_stem: str) -> str:
    """与官方 composer 一致：alt 中去掉方括号，避免破坏 Markdown。"""
    name = fallback_stem
    if isinstance(original, str) and original.strip():
        name = original.strip()
    base = Path(name).name
    base = base.replace("[", "").replace("]", "")
    return base or "image"


class ForumClient:
    def __init__(self, base_url: str, api_key: str, client_id: str):
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={
                "User-Api-Key": api_key,
                "User-Api-Client-Id": client_id,
            },
            timeout=120.0,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    def get_json(self, path: str, **kwargs: Any) -> Any:
        r = self._http.get(path, **kwargs)
        r.raise_for_status()
        return r.json()

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        r = self._http.post(path, json=payload, headers={"Content-Type": "application/json"})
        r.raise_for_status()
        if not r.content.strip():
            return {}
        return r.json()

    def post_json_allow_status(self, path: str, payload: dict[str, Any]) -> tuple[int, Any]:
        """POST JSON；不因 HTTP 失败抛异常（用于悬赏等插件端点自定义 success/error JSON）。"""
        r = self._http.post(path, json=payload, headers={"Content-Type": "application/json"})
        if not r.content.strip():
            return r.status_code, {}
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"_raw_text": r.text[:800]}

    def put_json(self, path: str, payload: dict[str, Any]) -> Any:
        r = self._http.put(path, json=payload, headers={"Content-Type": "application/json"})
        r.raise_for_status()
        if not r.content.strip():
            return {}
        return r.json()

    def upload_image(self, file_path: Path) -> str:
        """上传本地图片，返回一条完整 Markdown 图片语法。

        优先使用接口返回的 ``short_url``（``upload://…``），与 Web 端 composer 一致，
        便于 CookedPostProcessor 解析本地 Upload，从而正确写入 topic ``image_url``。
        若仅有 ``url`` 则退化为 ``![](https?://…)``（部分站点缩略图可能仍不完整）。
        """
        with file_path.open("rb") as f:
            files = {"file": (file_path.name, f, "application/octet-stream")}
            data = {"type": "composer", "synchronous": "true"}
            r = self._http.post("/uploads.json", files=files, data=data)
        r.raise_for_status()
        body = r.json()
        short = body.get("short_url")
        if isinstance(short, str) and short.strip():
            alt = _markdown_upload_alt(body.get("original_filename"), file_path.name)
            w, h = body.get("width"), body.get("height")
            if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
                return f"![{alt}|{w}x{h}]({short.strip()})"
            return f"![{alt}]({short.strip()})"

        url = body.get("url")
        if not url:
            raise RuntimeError(f"upload failed: {body}")
        if url.startswith("//"):
            abs_url = "https:" + url
        elif url.startswith("/"):
            abs_url = self.base_url + url
        else:
            abs_url = url
        return f"![]({abs_url})"

    def current_user(self) -> dict[str, Any]:
        data = self.get_json("/session/current.json")
        return data["current_user"]

    def site(self) -> dict[str, Any]:
        """GET /site.json — 站点元数据与分类树等。"""
        return self.get_json("/site.json")

    def site_basic_info(self) -> dict[str, Any]:
        """GET /site/basic-info.json — 公开站点标题、描述等。"""
        return self.get_json("/site/basic-info.json")

    def tags_list(self) -> dict[str, Any]:
        return self.get_json("/tags.json")

    def user_summary(self, username: str) -> dict[str, Any]:
        """GET /u/{username}/summary.json — 用户发帖/回帖摘要与统计。"""
        return self.get_json(f"/u/{username}/summary.json")

    def user_card(self, username: str) -> dict[str, Any]:
        return self.get_json(f"/u/{username}.json")

    def category_slug_for_id(self, category_id: int) -> str:
        data = self.get_json("/categories.json")
        categories = data.get("category_list", {}).get("categories", [])

        def walk(cats: list[Any]) -> str | None:
            for c in cats:
                if not isinstance(c, dict):
                    continue
                if c.get("id") == category_id:
                    return str(c["slug"])
                subs = c.get("subcategory_list")
                if isinstance(subs, list):
                    found = walk(subs)
                    if found is not None:
                        return found
            return None

        slug = walk(categories)
        if slug is None:
            raise ValueError(f"category id {category_id} not found")
        return slug

    def list_topics(self, category_id: int | None) -> dict[str, Any]:
        if category_id is None:
            return self.get_json("/latest.json")
        slug = self.category_slug_for_id(category_id)
        return self.get_json(f"/c/{slug}/{category_id}.json")

    def search(self, query: str) -> dict[str, Any]:
        return self.get_json("/search.json", params={"q": query})

    def topic(self, topic_id: int) -> dict[str, Any]:
        return self.get_json(f"/t/{topic_id}.json")

    def create_bounty_topic(
        self,
        *,
        title: str,
        raw: str,
        category_id: int,
        bounty_amount: int,
        bounty_deadline: int | None = None,
        bounty_allocation_mode: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        payload: dict[str, Any] = {
            "title": title,
            "raw": raw,
            "category_id": category_id,
            "bounty_amount": bounty_amount,
        }
        if bounty_deadline is not None:
            payload["bounty_deadline"] = int(bounty_deadline)
        if bounty_allocation_mode:
            payload["bounty_allocation_mode"] = str(bounty_allocation_mode).strip()
        code, body = self.post_json_allow_status(
            "/a_a_chat-api/bounties",
            payload,
        )
        if isinstance(body, dict):
            return code, body
        return code, {}
