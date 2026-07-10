"""通知器。

支持三种渠道，用 config.yaml 的 notify.channel 选择：
    - console : 命令行打印(默认，用于调试)
    - serverchan : Server酱(方糖)，微信推送，需要 sendkey
    - pushplus : PushPlus，微信推送，需要 token

Server酱 和 PushPlus 都是免费、无需自建服务器、扫码即用的微信推送服务：
    - Server酱: https://sct.ftqq.com  登录后拿 SendKey
    - PushPlus: https://www.pushplus.plus  登录后拿 token

新增渠道只要再写一个 Notifier 子类并在 build_notifier 里注册即可。
"""
from __future__ import annotations

import abc

import httpx

from .models import Job


def _format_text(jobs: list[Job], overflow: int = 0) -> tuple[str, str]:
    """把岗位列表格式化成 (标题, Markdown正文)。

    overflow>0 时在标题和正文里提示"还有 N 条未展示"。
    """
    shown = len(jobs)
    total = shown + overflow
    title = f"发现 {total} 个新岗位" if overflow else f"发现 {shown} 个新岗位"
    header = f"### 发现 {total} 个新岗位（本次展示最新 {shown} 条）\n" if overflow \
        else f"### 发现 {shown} 个新岗位\n"
    lines = [header]
    for i, job in enumerate(jobs, 1):
        lines.append(f"**{i}. {job.company} | {job.title}**")
        if job.city:
            lines.append(f"- 城市：{job.city}")
        if job.category:
            lines.append(f"- 分类：{job.category}")
        if job.publish_at:
            lines.append(f"- 发布：{job.publish_at}")
        lines.append(f"- [立即投递]({job.url})\n")
    if overflow:
        lines.append(f"\n> 另有 {overflow} 条较早的新岗位已入库，可查看数据库或看板。")
    return title, "\n".join(lines)


class BaseNotifier(abc.ABC):
    @abc.abstractmethod
    def notify(self, jobs: list[Job], overflow: int = 0) -> None:
        raise NotImplementedError


class ConsoleNotifier(BaseNotifier):
    """把新岗位打印到控制台。"""

    def notify(self, jobs: list[Job], overflow: int = 0) -> None:
        if not jobs:
            print("本轮没有发现新岗位。")
            return
        total = len(jobs) + overflow
        print(f"\n{'='*60}")
        print(f"发现 {total} 个新岗位！" + (f"（展示最新 {len(jobs)} 条）" if overflow else ""))
        print(f"{'='*60}")
        for i, job in enumerate(jobs, 1):
            print(f"\n[{i}] {job.company} | {job.title}")
            if job.city:
                print(f"    城市: {job.city}")
            if job.category:
                print(f"    分类: {job.category}")
            if job.publish_at:
                print(f"    发布: {job.publish_at}")
            print(f"    投递: {job.url}")
        if overflow:
            print(f"\n另有 {overflow} 条较早的新岗位已入库。")
        print(f"\n{'='*60}\n")


class ServerChanNotifier(BaseNotifier):
    """Server酱(方糖)微信推送。"""

    def __init__(self, sendkey: str) -> None:
        self.sendkey = sendkey
        self.url = f"https://sctapi.ftqq.com/{sendkey}.send"

    def notify(self, jobs: list[Job], overflow: int = 0) -> None:
        if not jobs:
            print("本轮没有发现新岗位。")
            return
        title, body = _format_text(jobs, overflow)
        try:
            resp = httpx.post(
                self.url,
                data={"title": title, "desp": body},
                timeout=15,
            )
            ok = resp.status_code == 200 and resp.json().get("code") == 0
            print(f"[Server酱] 推送{'成功' if ok else '失败'}: {resp.text[:120]}")
        except Exception as e:
            print(f"[Server酱] 推送异常: {e}")


class PushPlusNotifier(BaseNotifier):
    """PushPlus 微信推送。"""

    def __init__(self, token: str) -> None:
        self.token = token
        self.url = "https://www.pushplus.plus/send"

    def notify(self, jobs: list[Job], overflow: int = 0) -> None:
        if not jobs:
            print("本轮没有发现新岗位。")
            return
        title, body = _format_text(jobs, overflow)
        try:
            resp = httpx.post(
                self.url,
                json={
                    "token": self.token,
                    "title": title,
                    "content": body,
                    "template": "markdown",
                },
                timeout=15,
            )
            ok = resp.status_code == 200 and resp.json().get("code") == 200
            print(f"[PushPlus] 推送{'成功' if ok else '失败'}: {resp.text[:120]}")
        except Exception as e:
            print(f"[PushPlus] 推送异常: {e}")


def build_notifier(cfg: dict) -> BaseNotifier:
    """按 config 的 notify 段构造通知器。缺配置时回退到 console。

    key 的读取优先级：环境变量 > config.yaml。
    这样在 GitHub Actions 里把 key 放进 Secrets(注入为环境变量)即可，
    绝不把 key 明文写进仓库。本地调试仍可直接写在 config 里。
    """
    import os

    notify_cfg = cfg.get("notify", {})
    channel = (os.environ.get("NOTIFY_CHANNEL") or notify_cfg.get("channel") or "console").lower()

    if channel == "serverchan":
        key = (os.environ.get("SERVERCHAN_SENDKEY") or notify_cfg.get("serverchan_sendkey", "")).strip()
        if key:
            return ServerChanNotifier(key)
        print("[!] notify.channel=serverchan 但未配置 sendkey，回退到 console")
    elif channel == "pushplus":
        token = (os.environ.get("PUSHPLUS_TOKEN") or notify_cfg.get("pushplus_token", "")).strip()
        if token:
            return PushPlusNotifier(token)
        print("[!] notify.channel=pushplus 但未配置 token，回退到 console")

    return ConsoleNotifier()
