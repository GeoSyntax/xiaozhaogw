"""通知器。

支持四种渠道，用 config.yaml 的 notify.channel 选择：
    - console : 命令行打印(默认，用于调试)
    - serverchan : Server酱(方糖)，微信推送，需要 sendkey
    - pushplus : PushPlus，微信推送，需要 token
    - telegram : Telegram Bot 推送，需要 bot_token + chat_id

Server酱 和 PushPlus 都是免费、无需自建服务器、扫码即用的微信推送服务：
    - Server酱: https://sct.ftqq.com  登录后拿 SendKey
    - PushPlus: https://www.pushplus.plus  登录后拿 token

Telegram：找 @BotFather 建 bot 拿 bot_token，找 @userinfobot 拿你的 chat_id。
    注意 Telegram API 国内需代理才能访问，但 GitHub Actions 海外 IP 可直连，
    所以云端自动跑 + TG 推送这条链路无需任何代理。

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


class TelegramNotifier(BaseNotifier):
    """Telegram Bot 推送。

    bot_token 找 @BotFather 建 bot 拿；chat_id 找 @userinfobot 拿。
    Telegram sendMessage 单条正文上限 4096 字符，超长自动分段发送。
    """

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def notify(self, jobs: list[Job], overflow: int = 0) -> None:
        if not jobs:
            print("本轮没有发现新岗位。")
            return
        title, body = _format_text(jobs, overflow)
        # Telegram 支持 Markdown，但对特殊字符敏感易 400，这里用纯文本最稳
        full = f"{title}\n\n{body}"
        chunks = self._split(full, limit=4000)
        for idx, chunk in enumerate(chunks, 1):
            try:
                resp = httpx.post(
                    self.url,
                    json={
                        "chat_id": self.chat_id,
                        "text": chunk,
                        "disable_web_page_preview": True,
                    },
                    timeout=15,
                )
                ok = resp.status_code == 200 and resp.json().get("ok") is True
                tag = f"[Telegram {idx}/{len(chunks)}]"
                print(f"{tag} 推送{'成功' if ok else '失败'}: {resp.text[:120]}")
            except Exception as e:
                print(f"[Telegram] 推送异常: {e}")

    @staticmethod
    def _split(text: str, limit: int = 4000) -> list[str]:
        """按行把长文本切成不超过 limit 字符的段，尽量不从行中间断开。"""
        chunks: list[str] = []
        cur = ""
        for line in text.split("\n"):
            # 单行就超长(极少见)，硬切
            if len(line) > limit:
                if cur:
                    chunks.append(cur)
                    cur = ""
                for i in range(0, len(line), limit):
                    chunks.append(line[i : i + limit])
                continue
            if len(cur) + len(line) + 1 > limit:
                chunks.append(cur)
                cur = line
            else:
                cur = f"{cur}\n{line}" if cur else line
        if cur:
            chunks.append(cur)
        return chunks


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
    elif channel == "telegram":
        token = (os.environ.get("TELEGRAM_BOT_TOKEN") or notify_cfg.get("telegram_bot_token", "")).strip()
        chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or notify_cfg.get("telegram_chat_id", "")).strip()
        if token and chat_id:
            return TelegramNotifier(token, chat_id)
        print("[!] notify.channel=telegram 但未配置 bot_token/chat_id，回退到 console")

    return ConsoleNotifier()
