"""哔哩哔哩(B站)校招官网适配器。

为什么这家用浏览器(Playwright)而不是 httpx：
    B站校招接口 jobs.bilibili.com/api/campus/position/positionList 虽是公开
    JSON API，但要求动态的 x-csrf + lunar-id 请求头和 ajSessionId 会话凭证，
    都由页面 JS 实时生成。纯 httpx 直接打会被拒(code=-101 ajSessionId不能为空)。
    因此和字节同策略：让真实浏览器打开页面、自己带齐凭证发请求，我们拦截返回的
    JSON。代价是不能在 GitHub Actions 云环境稳定跑(needs_browser=True)，本地运行。

策略要点：
    - 列表默认按发布时间倒序，最新岗位在前。拦截首屏 + 翻前 N 页即可覆盖新增。
    - 返回 data.list[]，含 positionName/positionTypeName/workLocation/pushTime。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, List

from ..models import Job
from .base import BaseAdapter

POSITION_URL = "https://jobs.bilibili.com/campus/positions"
API_MARK = "/api/campus/position/positionList"
DETAIL_URL = "https://jobs.bilibili.com/campus/positions/{job_id}"


class BilibiliAdapter(BaseAdapter):
    name = "bilibili"
    display = "B站"

    def __init__(
        self,
        timeout: float = 30.0,
        max_pages: int = 3,
        headless: bool = True,
        page_pause: float = 1.2,
    ) -> None:
        super().__init__(timeout=timeout)
        self.max_pages = max_pages
        self.headless = headless
        self.page_pause = page_pause

    def fetch(self) -> List[Job]:
        from playwright.sync_api import sync_playwright

        raw_jobs: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=self.headless)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
            )
            page = context.new_page()

            def on_response(resp) -> None:
                if API_MARK not in resp.url:
                    return
                try:
                    data = resp.json()
                except Exception:
                    return
                items = (data or {}).get("data", {}).get("list") or []
                for post in items:
                    pid = str(post.get("id", ""))
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        raw_jobs.append(post)

            page.on("response", on_response)

            page.goto(POSITION_URL, timeout=self.timeout * 1000)
            self._wait_for_jobs(raw_jobs, min_count=1)

            for _ in range(self.max_pages - 1):
                before = len(raw_jobs)
                if not self._go_next_page(page):
                    break
                time.sleep(self.page_pause)
                self._wait_for_jobs(raw_jobs, min_count=before + 1)

            browser.close()

        return [self._to_job(p) for p in raw_jobs]

    def _wait_for_jobs(self, raw_jobs: list, min_count: int, tries: int = 20) -> None:
        for _ in range(tries):
            if len(raw_jobs) >= min_count:
                return
            time.sleep(0.3)

    def _go_next_page(self, page) -> bool:
        """点击「下一页」。B站分页用 .pagination 里的 next 按钮。"""
        for sel in ("li[title='下一页']", ".atsx-pagination-next", ".pagination-next"):
            btn = page.query_selector(sel)
            if btn is None:
                continue
            cls = btn.get_attribute("class") or ""
            if "disabled" in cls:
                return False
            try:
                btn.click()
                return True
            except Exception:
                continue
        return False

    def _to_job(self, post: dict[str, Any]) -> Job:
        job_id = str(post.get("id") or "")

        city = ""
        wl = post.get("workLocation")
        if isinstance(wl, str):
            city = wl
        elif isinstance(wl, list):
            city = "/".join(str(x) for x in wl if x)

        publish_at = ""
        pt = post.get("pushTime")
        if isinstance(pt, (int, float)) and pt > 0:
            try:
                publish_at = datetime.fromtimestamp(pt / 1000).strftime("%Y-%m-%d %H:%M")
            except Exception:
                publish_at = ""
        elif isinstance(pt, str):
            publish_at = pt

        return Job(
            company=self.display,
            job_id=job_id,
            title=(post.get("positionName") or "").strip(),
            city=city,
            category=post.get("positionTypeName") or "",
            url=DETAIL_URL.format(job_id=job_id),
            publish_at=publish_at,
            raw=post,
        )
