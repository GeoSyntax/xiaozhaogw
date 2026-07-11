"""飞书招聘平台通用适配器。

一个关键发现：字节、蔚来、理想等公司的校招官网都建在飞书招聘(feishu
recruiting)平台上，用的是**完全相同**的接口：
    POST https://<host>/api/v1/search/job/posts?...&_signature=...
URL 上带一个页面 JS 实时生成的动态 `_signature`，缺了会被网关拦成 405。
纯 httpx 想复现签名要逆向 JS，极其脆弱。因此这里让真实浏览器自己打请求、
自己算签名，我们只在旁边"拦截"它返回的 JSON。

因为接口一模一样，只有域名(host)和公司名不同，所以抽象成一个基类，
各公司只是设置不同的 host —— 加一家飞书系公司 = 加一个几行的子类。

策略要点：
    - 官网默认按发布时间倒序，最新岗位在第一页。只翻前 N 页(max_pages)
      即可覆盖所有新上岗位。
    - 每条自带 recruit_type(校招/实习)，标准化时带出交给上层过滤。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, List

from ..models import Job
from .base import BaseAdapter

# 岗位数据接口路径特征(用于识别要拦截的响应)
API_MARK = "/api/v1/search/job/posts"


class FeishuAdapter(BaseAdapter):
    """飞书招聘平台通用适配器基类。子类只需设置 name/display/host。"""

    # 子类覆盖：飞书招聘门户域名，如 jobs.bytedance.com / nio.jobs.feishu.cn
    host = ""
    # 子类可覆盖：门户段。大多数校招门户是 "campus"，个别公司(如理想)用
    # 社招/全量门户 "index"。它同时决定要打开的职位页路由和详情页 URL。
    # 底层岗位接口 POST /api/v1/search/job/posts 两种门户完全一致。
    portal = "campus"

    def __init__(
        self,
        timeout: float = 30.0,
        max_pages: int = 3,
        headless: bool = True,
        page_pause: float = 1.2,
    ) -> None:
        super().__init__(timeout=timeout)
        # 每轮翻多少页(每页10条)。3页=最新30条，足够覆盖新增。
        self.max_pages = max_pages
        self.headless = headless
        # 翻页之间停顿，模拟真人 + 给接口留响应时间
        self.page_pause = page_pause

    @property
    def position_url(self) -> str:
        # campus 门户职位页是 /campus/position；index 门户职位列表在 /index
        if self.portal == "campus":
            return f"https://{self.host}/campus/position"
        return f"https://{self.host}/{self.portal}"

    def _detail_url(self, job_id: str) -> str:
        return f"https://{self.host}/{self.portal}/position/{job_id}/detail"

    def fetch(self) -> List[Job]:
        # 延迟导入：没装 playwright 也不影响其它 httpx 适配器
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

            # 拦截岗位接口的响应，把每条岗位收进 raw_jobs
            def on_response(resp) -> None:
                if API_MARK not in resp.url:
                    return
                try:
                    data = resp.json()
                except Exception:
                    return
                posts = (data or {}).get("data", {}).get("job_post_list") or []
                for post in posts:
                    pid = str(post.get("id", ""))
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        raw_jobs.append(post)

            page.on("response", on_response)

            page.goto(self.position_url, timeout=self.timeout * 1000)
            # 等第一页岗位接口回来并被 on_response 收下
            self._wait_for_jobs(raw_jobs, min_count=1)

            # 逐页翻，每翻一页等新数据进来
            for _ in range(self.max_pages - 1):
                before = len(raw_jobs)
                if not self._go_next_page(page):
                    break
                time.sleep(self.page_pause)
                self._wait_for_jobs(raw_jobs, min_count=before + 1)

            browser.close()

        return [self._to_job(post) for post in raw_jobs]

    # ---- 内部辅助 ----

    def _wait_for_jobs(self, raw_jobs: list, min_count: int, tries: int = 20) -> None:
        """轮询等待，直到已捕获岗位数达到 min_count 或超时(约6秒)。"""
        for _ in range(tries):
            if len(raw_jobs) >= min_count:
                return
            time.sleep(0.3)

    def _go_next_page(self, page) -> bool:
        """点击「下一页」。成功返回 True，没有下一页/按钮禁用返回 False。"""
        btn = page.query_selector("li[title='下一页']")
        if btn is None:
            return False
        cls = btn.get_attribute("class") or ""
        if "disabled" in cls:
            return False
        try:
            btn.click()
            return True
        except Exception:
            return False

    def _to_job(self, post: dict[str, Any]) -> Job:
        """把飞书招聘的原始岗位 JSON 转成标准 Job。"""
        job_id = str(post.get("id", ""))

        # 城市：city_info.name；有的岗位是多城市列表 city_list
        city = ""
        if isinstance(post.get("city_info"), dict):
            city = post["city_info"].get("name") or ""
        if not city and isinstance(post.get("city_list"), list):
            city = "/".join(
                c.get("name", "") for c in post["city_list"] if isinstance(c, dict)
            )

        # 分类：job_category.name
        category = ""
        if isinstance(post.get("job_category"), dict):
            category = post["job_category"].get("name") or ""

        # 招聘类型：校招 / 实习 —— 拼进分类，方便上层过滤区分
        recruit = ""
        rt = post.get("recruit_type")
        if isinstance(rt, dict):
            recruit = rt.get("name") or ""
        if recruit:
            category = f"{category}/{recruit}" if category else recruit

        # 发布时间：publish_time 是毫秒时间戳
        publish_at = ""
        pub = post.get("publish_time") or post.get("pub_time")
        if isinstance(pub, (int, float)) and pub > 0:
            try:
                publish_at = datetime.fromtimestamp(pub / 1000).strftime(
                    "%Y-%m-%d %H:%M"
                )
            except Exception:
                publish_at = ""

        return Job(
            company=self.display,
            job_id=job_id,
            title=(post.get("title") or "").strip(),
            city=city,
            category=category,
            url=self._detail_url(job_id),
            publish_at=publish_at,
            raw=post,
        )


class BytedanceAdapter(FeishuAdapter):
    name = "bytedance"
    display = "字节跳动"
    host = "jobs.bytedance.com"


class NioAdapter(FeishuAdapter):
    name = "nio"
    display = "蔚来"
    host = "nio.jobs.feishu.cn"


class LiAutoAdapter(FeishuAdapter):
    name = "liauto"
    display = "理想汽车"
    host = "li.jobs.feishu.cn"
    # 理想用社招/全量门户 /index，不是 /campus/position
    portal = "index"


class IqiyiAdapter(FeishuAdapter):
    name = "iqiyi"
    display = "爱奇艺"
    host = "careers.iqiyi.com"
    portal = "campus"
