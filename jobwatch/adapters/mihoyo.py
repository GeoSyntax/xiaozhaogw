"""米哈游(miHoYo)校招官网适配器。

为什么这家用 httpx：
    米哈游校招接口 ats.openout.mihoyo.com/ats-portal/v1/job/list 是公开 POST
    JSON API，无签名、无登录，直接打就返回数据。能上 GitHub Actions。

参数要点(探测得出)：
    - POST body: {"pageNo":N,"pageSize":N,"channelDetailIds":[1],"hireType":1}
      channelDetailIds=[1] 是校招渠道；hireType=1 有数据(2/3 为空)。
      jobNature/jobNatureId 区分全职(校招正式)与实习。
    - 返回 data.list[]，data.total 是总数，可据此翻页。
    - 每条含 title/competencyType(程序&技术类...)/addressDetailList/jobNature。
    - 详情页 URL：jobs.mihoyo.com/#/campus/position/{id}
"""
from __future__ import annotations

import time
from typing import Any, List

from ..models import Job
from .base import BaseAdapter

API_URL = "https://ats.openout.mihoyo.com/ats-portal/v1/job/list"
DETAIL_URL = "https://jobs.mihoyo.com/#/campus/position/{job_id}"


class MihoyoAdapter(BaseAdapter):
    name = "mihoyo"
    display = "米哈游"

    def __init__(
        self,
        timeout: float = 15.0,
        channel_detail_ids: list[int] | None = None,
        hire_type: int = 1,
        page_size: int = 50,
        max_pages: int = 15,
        page_pause: float = 0.4,
    ) -> None:
        super().__init__(timeout=timeout)
        # 校招渠道；探测得知 [1] 是校招
        self.channel_detail_ids = channel_detail_ids or [1]
        self.hire_type = hire_type
        self.page_size = page_size
        self.max_pages = max_pages
        self.page_pause = page_pause

    def _client(self):
        import httpx

        from .base import DEFAULT_HEADERS

        headers = dict(DEFAULT_HEADERS)
        headers["Content-Type"] = "application/json"
        headers["Origin"] = "https://jobs.mihoyo.com"
        headers["Referer"] = "https://jobs.mihoyo.com/"
        return httpx.Client(headers=headers, timeout=self.timeout)

    def fetch(self) -> List[Job]:
        raw: list[dict[str, Any]] = []
        with self._client() as client:
            for page in range(1, self.max_pages + 1):
                body = {
                    "pageNo": page,
                    "pageSize": self.page_size,
                    "channelDetailIds": self.channel_detail_ids,
                    "hireType": self.hire_type,
                }
                resp = client.post(API_URL, json=body)
                data = resp.json().get("data") or {}
                items = data.get("list") or []
                if not items:
                    break
                raw.extend(items)
                if len(raw) >= (data.get("total") or 0):
                    break
                time.sleep(self.page_pause)
        return [self._to_job(p) for p in raw]

    def _to_job(self, post: dict[str, Any]) -> Job:
        job_id = str(post.get("id") or "")

        # addressDetailList 是 [{addressDetail:...}, ...]，拼成多城市
        city = ""
        al = post.get("addressDetailList")
        if isinstance(al, list):
            city = "/".join(
                a.get("addressDetail", "")
                for a in al
                if isinstance(a, dict) and a.get("addressDetail")
            )

        # competencyType 是职类(程序&技术类/美术&表现类...)；招聘性质拼进分类
        category = post.get("competencyType") or ""
        nature = post.get("jobNature") or ""
        if nature:
            category = f"{category}/{nature}" if category else nature

        return Job(
            company=self.display,
            job_id=job_id,
            title=(post.get("title") or "").strip(),
            city=city,
            category=category,
            url=DETAIL_URL.format(job_id=job_id),
            publish_at="",  # 接口未提供发布时间字段
            raw=post,
        )
