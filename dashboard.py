"""校招岗位看板 —— 本地 Web 界面。

一个轻量 Flask 应用，读取 jobs.db，提供：
    - 按公司/关键词/城市/投递状态筛选
    - 分页浏览
    - 一键标记「已投递」
    - 直达投递链接

启动：
    ./.venv/Scripts/python.exe dashboard.py
然后浏览器打开 http://127.0.0.1:5000

只读本地数据库，不采集。采集由 main.py 负责，两者共用同一个 jobs.db。
"""
from __future__ import annotations

import sys

# Windows 控制台默认 GBK，打印中文会崩。强制 UTF-8。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import yaml
from flask import Flask, redirect, render_template_string, request, url_for

from jobwatch.storage import Storage


def _db_path() -> str:
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}).get("db_path", "jobs.db")
    except FileNotFoundError:
        return "jobs.db"


app = Flask(__name__)
DB_PATH = _db_path()
PAGE_SIZE = 50


PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>校招岗位看板</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #c9d1d9; --muted: #8b949e; --link: #58a6ff;
    --accent: #238636; --accent-hover: #2ea043; --applied: #6e7681;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 14px; line-height: 1.5;
  }
  .wrap { max-width: 1200px; margin: 0 auto; padding: 24px 20px; }
  h1 { font-size: 18px; font-weight: 600; margin: 0 0 4px; }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 20px; }
  .stats { color: var(--muted); font-size: 13px; }
  .stats b { color: var(--text); font-weight: 600; }

  form.filters {
    display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
    padding: 16px; background: var(--surface);
    border: 1px solid var(--border); border-radius: 8px; margin: 16px 0;
  }
  input, select {
    background: var(--bg); color: var(--text);
    border: 1px solid var(--border); border-radius: 6px;
    padding: 6px 10px; font-size: 14px; font-family: inherit;
  }
  input:focus, select:focus { outline: none; border-color: var(--link); }
  input[type=text] { min-width: 160px; }
  button {
    background: var(--accent); color: #fff; border: 1px solid rgba(240,246,252,0.1);
    border-radius: 6px; padding: 6px 14px; font-size: 14px; cursor: pointer;
    font-family: inherit;
  }
  button:hover { background: var(--accent-hover); }
  a.reset { color: var(--muted); text-decoration: none; padding: 6px 4px; }
  a.reset:hover { color: var(--text); }

  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th {
    text-align: left; font-weight: 600; font-size: 12px; color: var(--muted);
    padding: 8px 10px; border-bottom: 1px solid var(--border);
  }
  td { padding: 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
  tr:hover td { background: rgba(177,186,196,0.04); }
  .title a { color: var(--link); text-decoration: none; font-weight: 500; }
  .title a:hover { text-decoration: underline; }
  .company { color: var(--text); white-space: nowrap; }
  .meta { color: var(--muted); font-size: 13px; white-space: nowrap; }
  .cat { color: var(--muted); font-size: 13px; }
  .new {
    display: inline-block; font-size: 11px; font-weight: 600;
    color: var(--accent-hover); border: 1px solid var(--accent);
    border-radius: 4px; padding: 0 5px; margin-right: 6px; vertical-align: 1px;
  }
  tr.done .title a { color: var(--applied); }
  tr.done td { opacity: 0.65; }

  .mark {
    background: transparent; color: var(--muted);
    border: 1px solid var(--border); padding: 4px 10px; font-size: 13px;
  }
  .mark:hover { color: var(--text); border-color: var(--muted); background: transparent; }
  .mark.done { color: var(--accent-hover); border-color: var(--accent); }

  .pager { display: flex; gap: 8px; align-items: center; margin-top: 20px; color: var(--muted); }
  .pager a {
    color: var(--link); text-decoration: none; border: 1px solid var(--border);
    border-radius: 6px; padding: 5px 12px;
  }
  .pager a:hover { border-color: var(--link); }
  .pager .disabled { color: var(--applied); border-color: var(--border); padding: 5px 12px; }
  .empty { color: var(--muted); padding: 40px; text-align: center; }
</style>
</head>
<body>
<div class="wrap">
  <h1>校招岗位看板</h1>
  <div class="sub">共 <b>{{ stats.total }}</b> 个岗位 · 近 {{ stats.recent_days }} 天新增 <b>{{ stats.recent }}</b> 个 · 已标记投递 <b>{{ stats.applied }}</b> 个 · {{ company_summary }}</div>

  <form class="filters" method="get">
    <select name="company">
      <option value="">全部公司</option>
      {% for c in companies %}
      <option value="{{ c }}" {% if c == f.company %}selected{% endif %}>{{ c }}</option>
      {% endfor %}
    </select>
    <input type="text" name="keyword" placeholder="岗位关键词" value="{{ f.keyword }}">
    <input type="text" name="city" placeholder="城市" value="{{ f.city }}">
    <select name="applied">
      <option value="" {% if f.applied == '' %}selected{% endif %}>全部状态</option>
      <option value="0" {% if f.applied == '0' %}selected{% endif %}>未投递</option>
      <option value="1" {% if f.applied == '1' %}selected{% endif %}>已投递</option>
    </select>
    <select name="days">
      <option value="" {% if f.days == '' %}selected{% endif %}>不限时间</option>
      <option value="1" {% if f.days == '1' %}selected{% endif %}>最近 1 天</option>
      <option value="3" {% if f.days == '3' %}selected{% endif %}>最近 3 天</option>
      <option value="7" {% if f.days == '7' %}selected{% endif %}>最近 7 天</option>
    </select>
    <select name="sort">
      <option value="publish" {% if f.sort == 'publish' or f.sort == '' %}selected{% endif %}>按发布时间</option>
      <option value="recent" {% if f.sort == 'recent' %}selected{% endif %}>按入库时间</option>
      <option value="company" {% if f.sort == 'company' %}selected{% endif %}>按公司</option>
    </select>
    <button type="submit">筛选</button>
    <a class="reset" href="{{ url_for('index') }}">重置</a>
  </form>

  {% if jobs %}
  <table>
    <thead>
      <tr>
        <th>岗位</th><th>公司</th><th>城市</th><th>分类</th><th>发布</th><th></th>
      </tr>
    </thead>
    <tbody>
      {% for j in jobs %}
      <tr class="{{ 'done' if j.applied else '' }}">
        <td class="title">
          {% if j.is_new %}<span class="new">NEW</span>{% endif %}
          <a href="{{ j.url }}" target="_blank" rel="noopener">{{ j.title }}</a>
        </td>
        <td class="company">{{ j.company }}</td>
        <td class="meta">{{ j.city }}</td>
        <td class="cat">{{ j.category }}</td>
        <td class="meta">{{ j.publish_at }}</td>
        <td>
          <form method="post" action="{{ url_for('toggle') }}" style="margin:0">
            <input type="hidden" name="company" value="{{ j.company }}">
            <input type="hidden" name="job_id" value="{{ j.job_id }}">
            <input type="hidden" name="applied" value="{{ 0 if j.applied else 1 }}">
            <input type="hidden" name="qs" value="{{ qs }}">
            <button class="mark {{ 'done' if j.applied else '' }}" type="submit">
              {{ '已投' if j.applied else '标记' }}
            </button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <div class="pager">
    {% if page > 1 %}
      <a href="{{ page_url(page - 1) }}">← 上一页</a>
    {% else %}
      <span class="disabled">← 上一页</span>
    {% endif %}
    <span>第 {{ page }} / {{ total_pages }} 页</span>
    {% if page < total_pages %}
      <a href="{{ page_url(page + 1) }}">下一页 →</a>
    {% else %}
      <span class="disabled">下一页 →</span>
    {% endif %}
  </div>
  {% else %}
  <div class="empty">没有符合条件的岗位。</div>
  {% endif %}
</div>
</body>
</html>
"""


def _filters() -> dict:
    return {
        "company": request.args.get("company", "").strip(),
        "keyword": request.args.get("keyword", "").strip(),
        "city": request.args.get("city", "").strip(),
        "applied": request.args.get("applied", "").strip(),
        "days": request.args.get("days", "").strip(),
        "sort": request.args.get("sort", "").strip(),
    }


@app.route("/")
def index():
    f = _filters()
    page = max(1, int(request.args.get("page", 1) or 1))
    # days 转成整数；"" 或非法值当作 0(不限)
    try:
        days = int(f["days"]) if f["days"] else 0
    except ValueError:
        days = 0
    sort = f["sort"] or "publish"
    store = Storage(DB_PATH)
    try:
        total = store.count_where(
            f["company"], f["keyword"], f["city"], f["applied"], days
        )
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, total_pages)
        jobs = store.query(
            company=f["company"], keyword=f["keyword"], city=f["city"],
            applied=f["applied"], days=days, sort=sort,
            limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE,
        )
        stats = store.stats()
        companies = store.companies()
    finally:
        store.close()

    # 给"最近1天入库"的岗位打 NEW 标记（视觉高亮，呼应"第一时间发现"）
    from datetime import datetime, timedelta
    new_cutoff = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    for j in jobs:
        j["is_new"] = (j.get("first_seen") or "") >= new_cutoff

    company_summary = " · ".join(f"{k} {v}" for k, v in stats["by_company"].items())
    # 当前筛选条件的 query string，供翻页/标记后回到原视图
    from urllib.parse import urlencode
    qs = urlencode({k: v for k, v in f.items() if v})

    def page_url(p: int) -> str:
        params = {k: v for k, v in f.items() if v}
        params["page"] = p
        return url_for("index") + "?" + urlencode(params)

    return render_template_string(
        PAGE, jobs=jobs, stats=stats, companies=companies, f=f,
        page=page, total_pages=total_pages, company_summary=company_summary,
        qs=qs, page_url=page_url,
    )


@app.route("/toggle", methods=["POST"])
def toggle():
    company = request.form.get("company", "")
    job_id = request.form.get("job_id", "")
    applied = request.form.get("applied", "0") == "1"
    qs = request.form.get("qs", "")
    store = Storage(DB_PATH)
    try:
        store.set_applied(company, job_id, applied)
    finally:
        store.close()
    return redirect(url_for("index") + ("?" + qs if qs else ""))


if __name__ == "__main__":
    print("看板已启动 → http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
