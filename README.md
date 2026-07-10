# 校招岗位监控 (xiaozhaogw)

第一时间发现大厂**新上线**的技术岗，自动推送到微信。

直连各公司校招官网接口，每轮抓取和上次对比，**只推新出现的岗位**——不刷屏、不滞后。

## 支持的公司

| 公司 | 抓取方式 | 能上 GitHub Actions |
|---|---|---|
| 腾讯 | httpx 直连 | ✅ |
| 网易 | httpx 直连 | ✅ |
| 小红书 | httpx 直连 | ✅ |
| 美团 | httpx 直连 | ✅ |
| 米哈游 | httpx 直连 | ✅ |
| B站 | 浏览器(动态凭证) | ❌ 仅本地 |
| 字节跳动 | 浏览器(飞书·签名反爬) | ❌ 仅本地 |
| 蔚来 | 浏览器(飞书·签名反爬) | ❌ 仅本地 |
| 理想汽车 | 浏览器(飞书·签名反爬) | ❌ 仅本地 |

> httpx 公司轻量快速，可在云端 7×24 自动跑；浏览器公司只能本地跑（云 IP 易被风控）。
>
> 字节、蔚来、理想都建在**飞书招聘平台**上，接口完全相同，由一个通用适配器 `adapters/feishu.py` 统一支持——加一家飞书系公司只需一个几行的子类。

## 快速开始（本地）

```bash
# 1. 建虚拟环境 + 装依赖
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. 浏览器公司(字节/B站)需额外装 playwright（用系统 Chrome，无需下载内核）
.venv\Scripts\pip install playwright

# 3. 跑一轮（首次只建立基线，不推送）
.venv\Scripts\python main.py
```

Windows 控制台若中文乱码，命令前加 `PYTHONUTF8=1`。

## 配置 `config.yaml`

- **companies**：每家 `enabled: true/false` 控制是否采集
- **filter.include / exclude**：技术岗关键词，按你的方向增删
- **notify.channel**：`console`(打印) / `serverchan` / `pushplus` / `telegram`
- **notify.max_push**：单轮最多推几条（防刷屏，默认 30）

## 收通知

三选一：

- **Server酱**（微信，国内直连）：登录 https://sct.ftqq.com 拿 SendKey，`channel` 设 `serverchan`，填 `serverchan_sendkey`
- **PushPlus**（微信，国内直连）：登录 https://www.pushplus.plus 拿 token，`channel` 设 `pushplus`，填 `pushplus_token`
- **Telegram**：找 [@BotFather](https://t.me/BotFather) 发 `/newbot` 建 bot 拿 `bot_token`，找 [@userinfobot](https://t.me/userinfobot) 拿你的 `chat_id`，`channel` 设 `telegram`，填 `telegram_bot_token` + `telegram_chat_id`

> **Telegram 的网络注意**：Telegram API 国内需代理才能访问，**但 GitHub Actions 的海外 IP 可直连**。所以推荐 Telegram 走云端自动跑（本地跑 TG 推送才需要代理），微信渠道则本地/云端都能直连。

## 本地 Web 看板

除了微信推送，还能开一个本地看板浏览已抓到的所有岗位：

```bash
.venv\Scripts\python dashboard.py
```

打开 http://127.0.0.1:5000 —— 可按公司/关键词/城市/投递状态筛选、点岗位名跳投递页、一键标记「已投」。看板读的是同一个 `jobs.db`，采集在跑就能看到最新数据。

## 部署到 GitHub Actions（云端自动跑）

让 5 家 httpx 公司（腾讯/网易/小红书/美团/米哈游）在云端每 30 分钟自动跑，无需开电脑。已实测：GitHub Actions 的海外 IP 能完整直连这 5 家的国内接口，抓取条数与本地一致，无需代理。

1. **建仓库并推代码**（`jobs.db` 要一起提交，它是去重记忆）：
   ```bash
   git init && git add . && git commit -m "init"
   git branch -M main
   git remote add origin <你的仓库地址>
   git push -u origin main
   ```

2. **配 Secrets**：仓库 Settings → Secrets and variables → Actions → New secret，按渠道加：
   - 微信（Server酱）：`NOTIFY_CHANNEL`=`serverchan` + `SERVERCHAN_SENDKEY`
   - 微信（PushPlus）：`NOTIFY_CHANNEL`=`pushplus` + `PUSHPLUS_TOKEN`
   - Telegram：`NOTIFY_CHANNEL`=`telegram` + `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`

   > Telegram 在国内需代理，但 GitHub Actions 的海外 IP 能直连 Telegram API——云端跑 TG 推送反而最顺，无需任何代理。

3. **开启 Actions**：进 Actions 页，启用 workflow。可点 "Run workflow" 手动跑一次验证。

之后它每 30 分钟自动跑，发现新岗位推你（微信或 Telegram），并把 `jobs.db` 提交回仓库作为下轮的去重依据。

> **工作原理**：GitHub Actions 每次运行是全新环境，去重记忆靠"每轮把 jobs.db commit 回仓库、下轮 checkout 带回"实现。commit 带 `[skip ci]` 避免自我触发。

## 项目结构

```
config.yaml              配置：公司/关键词/推送
main.py                  入口：采集→过滤→去重→通知
dashboard.py             本地 Web 看板（浏览/筛选/标记已投）
jobwatch/
├── models.py            标准岗位结构 Job
├── storage.py           SQLite 存储 + 去重（项目核心）
├── filters.py           技术岗关键词过滤
├── notifier.py          通知：console/Server酱/PushPlus
└── adapters/
    ├── base.py          适配器基类
    ├── registry.py      公司注册表
    ├── tencent.py       腾讯（httpx）
    ├── netease.py       网易（httpx）
    ├── xiaohongshu.py   小红书（httpx）
    ├── meituan.py       美团（httpx）
    ├── mihoyo.py        米哈游（httpx）
    ├── bilibili.py      B站（浏览器）
    └── feishu.py        飞书招聘平台通用（浏览器）：字节/蔚来/理想
```

## 加一家新公司

1. 用浏览器 F12 → Network → XHR 找到该公司岗位列表接口
2. 若接口是 `POST /api/v1/search/job/posts`，说明该公司用**飞书招聘平台**
   （字节/蔚来/理想同款），在 `adapters/feishu.py` 加一个几行的子类即可，
   无需重写整套逻辑
3. 否则照 `adapters/tencent.py`(httpx) 或 `adapters/feishu.py`(浏览器) 写新适配器
4. 在 `adapters/registry.py` 登记一行
5. 在 `config.yaml` 的 `companies` 加一段
