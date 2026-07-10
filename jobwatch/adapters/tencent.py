"""腾讯招聘官网适配器。

为什么这家用 httpx 而不是浏览器：
    腾讯招聘接口 careers.tencent.com/tencentcareer/api/post/Query 是完全
    公开的 JSON API，无签名、无登录、无验证码，直接 GET 就能拿到结构化数据。
    这是最理想的形态——轻量、快速、能在 GitHub Actions 云环境稳定运行。

参数要点(探测得出)：
    - attrId: 1=社招, 2=校招, 3=实习。默认抓 2+3(校招+实习)。
    - pageSize 最大 200，配合 pageIndex 翻页。
    - 返回里 CategoryName 自带"技术/产品/设计..."分类，过滤很干净。
"""
from __future__ import annotations

import time
from typing import Any, List

from ..models import Job
from .base import BaseAdapter

API_URL = "https://careers.tencent.com/tencentcareer/api/post/Query"
# attrId 含义：2=校招, 3=实习, 1=社招
DEFAULT_ATTR_IDS = ["2", "3"]


class TencentAdapter(BaseAdapter):
    name = "tencent"
    display = "腾讯"

    def __init__(
        self,
        timeout: float = 15.0,
        attr_ids: list[str] | None = None,
        max_pages: int = 5,
        page_size: int = 100,
        page_pause: float = 0.4,
    ) -> None:
        super().__init__(timeout=timeout)
        # 抓哪些招聘类型：默认校招+实习
        self.attr_ids = attr_ids or list(DEFAULT_ATTR_IDS)
        # 每种类型最多翻几页(page_size 一页)，防止无限翻
        self.max_pages = max_pages
        self.page_size = page_size
        self.page_pause = page_pause

    def fetch(self) -> List[Job]:
        raw: list[dict[str, Any]] = []
        with self._client() as client:
            for attr in self.attr_ids:
                raw.extend(self._fetch_attr(client, attr))
        return [self._to_job(p) for p in raw]

    def _fetch_attr(self, client, attr: str) -> list[dict[str, Any]]:
        """抓单个招聘类型的全部岗位(翻页直到没有或到上限)。"""
        collected: list[dict[str, Any]] = []
        for page in range(1, self.max_pages + 1):
            params = {
                "timestamp": str(int(time.time() * 1000)),
                "keyword": "",
                "pageIndex": str(page),
                "pageSize": str(self.page_size),
                "language": "zh-cn",
                "area": "cn",
                "attrId": attr,
            }
            resp = client.get(API_URL, params=params)
            data = resp.json().get("Data") or {}
            posts = data.get("Posts") or []
            if not posts:
                break
            collected.extend(posts)
            # 已翻到尾页
            if len(collected) >= (data.get("Count") or 0):
                break
            time.sleep(self.page_pause)
        return collected

    def _to_job(self, post: dict[str, Any]) -> Job:
        # 招聘类型名(校招/实习/社招)拼进分类，方便上层过滤区分
        category = post.get("CategoryName") or ""
        # 城市：LocationName；跨国岗前面带 CountryName
        city = post.get("LocationName") or ""
        country = post.get("CountryName") or ""
        if country and country not in ("中国",) and country not in city:
            city = f"{country} {city}".strip()

        return Job(
            company=self.display,
            job_id=str(post.get("PostId") or post.get("RecruitPostId") or ""),
            title=(post.get("RecruitPostName") or "").strip(),
            city=city,
            category=category,
            url=post.get("PostURL") or "",
            publish_at=post.get("LastUpdateTime") or "",
            raw=post,
        )
