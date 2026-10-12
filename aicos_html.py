# -*- coding: utf-8 -*-
"""HTML 渲染器：单文件、可换肤（明亮 / 护眼淡黄 / 深色黑）、表格优先、可筛选。
与 aicos.py 同目录，被其 import；也可独立使用 render_html(data, day)。
"""
from __future__ import annotations

import html
from datetime import datetime, date, time, timedelta
from pathlib import Path

from aicos import classify, day_window  # 复用分类器与时间窗

KINDS = ["需求", "交付", "任务", "修复", "决策", "调研", "提交", "AI陈述"]
KIND_BADGE = {
    "需求": "k-ask", "交付": "k-deliver", "任务": "k-task", "修复": "k-fix",
    "决策": "k-decision", "调研": "k-research", "提交": "k-commit", "AI陈述": "k-ai",
}
KIND_COLORS = {
    "需求": "#4f46e5", "交付": "#16a34a", "任务": "#0284c7", "修复": "#dc2626",
    "决策": "#d97706", "调研": "#9333ea", "提交": "#64748b", "AI陈述": "#94a3b8",
}


def file_url(p: str) -> str:
    return "file:///" + str(p).replace("\\", "/").lstrip("/")


def svg_donut(counts: dict) -> str:
    """环形图（纯 SVG、零依赖）：条目类型分布。"""
    total = sum(counts.values()) or 1
    r, cx, cy = 54, 70, 70
    circ = 2 * 3.14159265 * r
    segs, off = [], 0.0
    for k in KINDS:
        v = counts.get(k, 0)
        if not v:
            continue
        frac = v / total
        segs.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{KIND_COLORS[k]}" '
            f'stroke-width="22" stroke-dasharray="{circ*frac:.2f} {circ*(1-frac):.2f}" '
            f'stroke-dashoffset="{-circ*off:.2f}" transform="rotate(-90 {cx} {cy})">'
            f"<title>{k} {v}</title></circle>"
        )
        off += frac
    legend = "".join(
        f'<div class="lg"><i style="background:{KIND_COLORS[k]}"></i>{k} {counts.get(k, 0)}</div>'
        for k in KINDS if counts.get(k)
    )
    return (f'<div class="chart"><div class="chart-t">类型分布</div>'
            f'<div class="donut-wrap"><svg width="140" height="140" viewBox="0 0 140 140">'
            f'{"".join(segs)}</svg><div class="donut-hole"><b>{total}</b><span>条</span></div></div>'
            f'<div class="legend">{legend}</div></div>')


def svg_bars(pairs, title: str, color: str = "#2563eb", horizontal: bool = False,
             full: bool = False) -> str:
    """柱状图（纯 SVG）：pairs = [(label, value)]。full=True 时独占一行（类别多时用）。"""
    if not pairs:
        return ""
    box_cls = "chart chart-wide" if full else "chart"
    if horizontal:  # 横向条形：项目对比
        w, rowh, label_w = 330, 26, 104
        maxv = max(v for _, v in pairs) or 1
        h = rowh * len(pairs) + 8
        bars = []
        for i, (lab, v) in enumerate(pairs):
            y = i * rowh + 4
            bw = max((w - label_w - 52) * v / maxv, 2)
            bars.append(
                f'<text x="0" y="{y+16}" class="bl">{html.escape(str(lab)[:11])}</text>'
                f'<rect x="{label_w}" y="{y+3}" width="{bw:.1f}" height="{rowh-10}" rx="4" '
                f'fill="{color}" opacity=".85"><title>{html.escape(str(lab))}: {v}</title></rect>'
                f'<text x="{label_w+bw+6:.1f}" y="{y+16}" class="bv">{v}</text>'
            )
        return (f'<div class="{box_cls}"><div class="chart-t">{html.escape(title)}</div>'
                f'<svg width="100%" viewBox="0 0 {w} {h}">{"".join(bars)}</svg></div>')
    # —— 纵向柱状（时间分布）：宽度随天数变大、标签抽稀，保证看清不重叠 ——
    n = len(pairs)
    w = max(380, min(n * 34, 1360))
    h = 215
    pad = 30
    maxv = max(v for _, v in pairs) or 1
    step = (w - pad * 2) / max(n, 1)
    bw = min(52, max(step * 0.62, 4))
    # 标签抽稀：按可用宽度决定每隔几根柱子标一个字
    max_labels = max(2, int((w - pad * 2) // 72))
    label_every = max(1, (n + max_labels - 1) // max_labels)
    # 最后一根柱子只在离上一个标签够远时才补标，避免两个字挤在一起
    last_ok = (n - 1) % label_every >= (label_every + 1) // 2
    show_val = step >= 22 and n <= 26
    bars = []
    for i, (lab, v) in enumerate(pairs):
        bh = (h - pad * 2 - 28) * v / maxv
        x = pad + step * i + (step - bw) / 2
        y = h - pad - 22 - bh
        short = str(lab)
        if len(short) == 10 and short[4] == "-":
            short = short[5:]                       # 2026-09-12 → 09-12（年份在标题里）
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{max(bh,2):.1f}" rx="4" '
            f'fill="{color}" opacity=".85"><title>{html.escape(str(lab))}: {v}</title></rect>'
        )
        if i % label_every == 0 or (i == n - 1 and last_ok):
            bars.append(
                f'<text x="{x+bw/2:.1f}" y="{h-pad-4}" class="bl" text-anchor="middle">'
                f'{html.escape(short)}</text>'
            )
        if show_val and v:
            bars.append(
                f'<text x="{x+bw/2:.1f}" y="{y-5:.1f}" class="bv" text-anchor="middle">{v}</text>'
            )
    return (f'<div class="{box_cls}"><div class="chart-t">{html.escape(title)}</div>'
            f'<svg width="100%" viewBox="0 0 {w} {h}">{"".join(bars)}</svg></div>')


def session_hours(data: dict) -> str:
    """AI 会话总时长（含空闲，粗口径）。"""
    total = 0.0
    for e in data.get("sessions") or []:
        try:
            t0 = datetime.fromisoformat(e["start"])
            t1 = datetime.fromisoformat(e["end"])
            total += max((t1 - t0).total_seconds(), 0)
        except Exception:
            continue
    hrs = total / 3600
    return f"{int(hrs)} 小时 {int((hrs % 1) * 60)} 分" if total else ""


def _window(data: dict, day: date):
    win = data.get("window") or {}
    try:
        return datetime.fromisoformat(win["start"]), datetime.fromisoformat(win["end"])
    except Exception:
        return day_window(day)


def build_rows(data: dict, day: date) -> list[dict]:
    win_start, win_end = _window(data, day)

    def inw(iso: str) -> bool:
        try:
            t = datetime.fromisoformat(iso)
            return win_start <= t < win_end
        except Exception:
            return False

    rows: list[dict] = []
    for e in data["sessions"]:
        proj = Path(e.get("project") or "(未知项目)").name or e.get("project") or "(未知项目)"
        ev_path = (e.get("evidence") or {}).get("session_path", "")
        for p in e.get("prompts") or []:
            if inw(p["time"]):
                rows.append({"time": p["time"], "proj": proj, "kind": "需求",
                             "text": p["text"], "ev": ev_path})
        for d in e.get("deliverables") or []:
            rows.append({"time": e.get("end") or "", "proj": proj, "kind": "交付",
                         "text": f"{Path(d.get('path', '')).name} — {d.get('description', '')}",
                         "ev": d.get("path", ev_path)})
        for t in e.get("todos") or []:
            if t.get("status") == "completed":
                rows.append({"time": e.get("end") or "", "proj": proj, "kind": "任务",
                             "text": t.get("content", ""), "ev": ev_path})
        for d in dict.fromkeys(e.get("decisions") or []):
            rows.append({"time": e.get("end") or "", "proj": proj, "kind": "决策",
                         "text": d, "ev": ev_path})
        for s in dict.fromkeys(e.get("searches") or []):
            rows.append({"time": e.get("end") or "", "proj": proj, "kind": "调研",
                         "text": s, "ev": ev_path})
        for o in e.get("outcomes") or []:
            cats = classify(o)
            kind = "修复" if "fix" in cats else ("决策" if "decision" in cats else "AI陈述")
            rows.append({"time": e.get("end") or "", "proj": proj, "kind": kind,
                         "text": o, "ev": ev_path})
    for c in data.get("git_commits") or []:
        rows.append({"time": c.get("time", ""), "proj": Path(c.get("repo", "")).name,
                     "kind": "提交", "text": f"{c.get('message', '')}", "ev": f"{c.get('repo','')}@{c.get('sha','')}"})
    rows.sort(key=lambda r: r["time"] or "")
    return rows


def build_summary(data: dict, day: date, summary: dict | None = None) -> list[str]:
    """「完成了哪些重要功能」：与 md 共用 aicos.digest_entries（同名合并/滤闲聊/Agent 注入）。"""
    from collections import defaultdict
    from aicos import digest_entries
    win_start, win_end = _window(data, day)

    def inw(iso: str) -> bool:
        try:
            t = datetime.fromisoformat(iso)
            return win_start <= t < win_end
        except Exception:
            return False

    by_proj: dict[str, list[dict]] = defaultdict(list)
    for s in data["sessions"]:
        by_proj[s.get("project") or "(未知项目)"].append(s)
    entries, skipped = digest_entries(by_proj, inw, data.get("git_commits") or [], summary)
    lines = []
    for ent in entries:
        det = "".join(f"<li>{html.escape(d)}</li>" for d in ent["details"])
        st_bits = [ent["stats"]] if ent["stats"] else []
        st_bits.append("📁 " + ent["path"])
        st = f'<div class="proj-stats">{html.escape(" · ".join(st_bits))}</div>'
        lines.append(
            f'<div class="proj"><h3><span class="proj-name">{html.escape(ent["name"])}</span>'
            f'<span class="proj-head">{html.escape(ent["headline"])}</span></h3>{st}'
            f'<ul class="proj-detail">{det}</ul></div>'
        )
    if skipped:
        lines.append(f'<div class="proj"><span class="proj-head" style="font-size:14px">'
                     f'（另有 {skipped} 个会话没留下任务/交付记录，未列出）</span></div>')
    return lines


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  --bg:#f6f7f9; --card:#ffffff; --fg:#1f2328; --muted:#6b7280; --border:#e5e7eb;
  --accent:#2563eb; --accent-soft:#dbeafe; --row-hover:#f3f4f6;
}
[data-theme="sepia"] {
  --bg:#f5eedc; --card:#fbf6e9; --fg:#4a3f2a; --muted:#8a7a55; --border:#e6d9b8;
  --accent:#a06b1f; --accent-soft:#f0e2bd; --row-hover:#f2e8cf;
}
[data-theme="dark"] {
  --bg:#16181d; --card:#1f232b; --fg:#e6e8ee; --muted:#9aa3b2; --border:#313743;
  --accent:#7aa2f7; --accent-soft:#26304a; --row-hover:#262b35;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.65 "PingFang SC","Microsoft YaHei",system-ui,sans-serif; transition:background .25s,color .25s; }
.wrap { max-width:1080px; margin:0 auto; padding:28px 20px 60px; }
header { display:flex; flex-wrap:wrap; gap:12px; align-items:center; justify-content:space-between; }
h1 { font-size:24px; margin:0; }
.sub { color:var(--muted); font-size:13px; margin:6px 0 0; }
.themes { display:flex; gap:8px; }
button { cursor:pointer; border:1px solid var(--border); background:var(--card); color:var(--fg);
  border-radius:20px; padding:7px 15px; font-size:13px; transition:all .2s; }
button:hover { border-color:var(--accent); color:var(--accent); }
button.active { background:var(--accent); border-color:var(--accent); color:#fff; }
.card { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:18px 20px; margin:18px 0; }
.summary li { margin:6px 0; }
.projects { margin-top:12px; }
.proj { margin:16px 0; padding-left:14px; border-left:3px solid var(--accent); }
.proj h3 { margin:0 0 2px; font-size:17px; line-height:1.45; }
.proj-name { color:var(--accent); background:var(--accent-soft); font-size:16px; font-weight:800;
  padding:3px 14px; border-radius:9px; margin-right:12px; letter-spacing:.3px; }
.proj-head { font-size:18px; font-weight:700; }
.proj-stats { color:var(--muted); font-size:12px; margin:2px 0 6px; }
.proj-detail { margin:4px 0 0 18px; padding:0; }
.proj-detail li { font-size:13px; color:var(--muted); margin:3px 0; line-height:1.6; }
.toolbar { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:18px 0 10px; }
.toolbar .sep { width:1px; height:22px; background:var(--border); margin:0 4px; }
select { border:1px solid var(--border); background:var(--card); color:var(--fg);
  border-radius:20px; padding:7px 12px; font-size:13px; }
table { width:100%; border-collapse:collapse; background:var(--card); border-radius:14px; overflow:hidden; }
th,td { text-align:left; padding:10px 12px; border-bottom:1px solid var(--border); font-size:13.5px; vertical-align:top; }
th { font-size:12px; color:var(--muted); font-weight:600; letter-spacing:.4px; background:var(--accent-soft); position:sticky; top:0; }
tr:hover td { background:var(--row-hover); }
td.t { white-space:nowrap; color:var(--muted); font-variant-numeric:tabular-nums; }
td.p { white-space:nowrap; }
td.c { max-width:560px; }
td.c span { display:block; max-height:3.2em; overflow:hidden; }
td.ev { color:var(--muted); font-size:11.5px; max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.badge { display:inline-block; padding:2px 10px; border-radius:12px; font-size:11.5px; white-space:nowrap; }
.k-ask{background:#eef2ff;color:#4f46e5;} .k-deliver{background:#dcfce7;color:#15803d;}
.k-task{background:#e0f2fe;color:#0369a1;} .k-fix{background:#fee2e2;color:#b91c1c;}
.k-decision{background:#fef3c7;color:#b45309;} .k-research{background:#f3e8ff;color:#7e22ce;}
.k-commit{background:#e5e7eb;color:#374151;} .k-ai{background:#f1f5f9;color:#475569;}
[data-theme="dark"] .k-ask,[data-theme="dark"] .k-deliver,[data-theme="dark"] .k-task,
[data-theme="dark"] .k-fix,[data-theme="dark"] .k-decision,[data-theme="dark"] .k-research,
[data-theme="dark"] .k-commit,[data-theme="dark"] .k-ai { filter:brightness(.8) saturate(.9); }
.stats { display:flex; flex-wrap:wrap; gap:14px; }
.stat { background:var(--accent-soft); border-radius:12px; padding:10px 18px; }
.stat b { display:block; font-size:20px; }
.stat span { color:var(--muted); font-size:12px; }
.charts { display:flex; flex-wrap:wrap; gap:16px; margin-top:14px; }
.chart { background:var(--accent-soft); border-radius:12px; padding:14px 16px; flex:1 1 300px; min-width:280px; }
.chart-wide { flex:1 1 100%; }
.chart svg { display:block; }
.chart-t { font-size:12px; color:var(--muted); margin-bottom:8px; }
.donut-wrap { position:relative; width:140px; margin:0 auto; }
.donut-hole { position:absolute; top:0; left:0; width:140px; height:140px;
  display:flex; flex-direction:column; align-items:center; justify-content:center; }
.donut-hole b { font-size:22px; }
.donut-hole span { font-size:11px; color:var(--muted); }
.legend { margin-top:10px; display:flex; flex-wrap:wrap; gap:6px 12px; justify-content:center; }
.lg { font-size:11.5px; color:var(--muted); display:flex; align-items:center; gap:5px; }
.lg i { width:10px; height:10px; border-radius:3px; display:inline-block; }
text.bl { font-size:11px; fill:var(--muted); }
text.bv { font-size:10.5px; fill:var(--fg); font-weight:600; }
th { cursor:pointer; user-select:none; }
th:hover { color:var(--accent); }
td.ev a { color:var(--accent); text-decoration:none; }
td.ev a:hover { text-decoration:underline; }
.foot { color:var(--muted); font-size:12px; margin-top:24px; }
.empty { text-align:center; color:var(--muted); padding:30px; }
@media print {
  .themes, .toolbar button, .no-print { display:none !important; }
  body { background:#fff; color:#111; }
  .card, table { break-inside:avoid; }
}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>__TITLE__</h1>
      <p class="sub">AI Chief of Staff 自动生成 ｜ 生成时间 __NOW__ ｜ 全部本地只读采集，无上传</p>
    </div>
    <div class="themes">
      <button onclick="setTheme('light')" id="t-light">☀️ 明亮</button>
      <button onclick="setTheme('sepia')" id="t-sepia">🍵 护眼淡黄</button>
      <button onclick="setTheme('dark')" id="t-dark">🌙 深色黑</button>
    </div>
  </header>

  <div class="card">
    <b>🎯 完成了哪些重要功能</b>
    <div class="chart-t" style="margin:4px 0 0">__DIGEST_NOTE__</div>
    <div class="projects">__SUMMARY__</div>
  </div>

  <div class="card">
    <b>📊 统计与图表</b>
    <div class="stats" style="margin-top:10px">__STATS__</div>
    <div class="charts">__CHARTS__</div>
  </div>

  <div class="toolbar">
    <b style="font-size:13px">AI 都做了哪些东西</b>
    <span class="sep"></span>
    <button class="kind-btn active" data-kind="全部">全部</button>
    __KIND_BTNS__
    <span class="sep"></span>
    <select id="projSel" onchange="applyFilter()">
      <option value="全部">全部项目</option>
      __PROJ_OPTS__
    </select>
    <span class="sep"></span>
    <span id="count" style="color:var(--muted);font-size:12px"></span>
    <button class="no-print" onclick="window.print()" title="导出 PDF 可在打印对话框选“另存为 PDF”">🖨 导出/打印</button>
  </div>

  <table id="tbl">
    <thead><tr>
      <th style="width:88px" onclick="sortBy(0)" title="点击排序">⏰ 时间</th>
      <th style="width:130px" onclick="sortBy(1)" title="点击排序">📁 项目</th>
      <th style="width:86px" onclick="sortBy(2)" title="点击排序">🏷️ 类型</th>
      <th onclick="sortBy(3)" title="点击排序">📝 内容</th>
      <th style="width:180px">📎 证据</th>
    </tr></thead>
    <tbody>__ROWS__</tbody>
  </table>
  <div class="empty" id="empty" style="display:none">没有符合条件的条目</div>

  <p class="foot">
    口径：按会话记录内部时间戳筛选时间窗（本地时区）。来源：DeepSeek Harness / Claude Code / Codex / Cursor 等本地会话日志 + git reflog（未用 git.exe）。
    分类为关键词启发式，可能有误判；每行「📎证据」可回溯原始会话/文件核对。
  </p>
</div>
<script>
function setTheme(t){
  document.documentElement.setAttribute('data-theme', t);
  try{ localStorage.setItem('aicos-theme', t); }catch(e){}
  ['light','sepia','dark'].forEach(function(x){
    var b=document.getElementById('t-'+x); if(b) b.className = (x===t)?'active':'';
  });
}
(function(){
  var t='light'; try{ t=localStorage.getItem('aicos-theme')||'light'; }catch(e){}
  setTheme(t);
})();
var curKind='全部';
document.querySelectorAll('.kind-btn').forEach(function(b){
  b.addEventListener('click', function(){
    curKind=b.dataset.kind;
    document.querySelectorAll('.kind-btn').forEach(function(x){x.className='kind-btn';});
    b.className='kind-btn active';
    applyFilter();
  });
});
function applyFilter(){
  var proj=document.getElementById('projSel').value;
  var rows=document.querySelectorAll('#tbl tbody tr'), n=0;
  rows.forEach(function(r){
    var ok=(curKind==='全部'||r.dataset.kind===curKind)&&(proj==='全部'||r.dataset.proj===proj);
    r.style.display=ok?'':'none'; if(ok) n++;
  });
  document.getElementById('empty').style.display=n?'none':'';
  document.getElementById('count').textContent='共 '+n+' 条';
}
var sortAsc={};
function sortBy(idx){
  var tb=document.querySelector('#tbl tbody');
  var rows=Array.prototype.slice.call(tb.querySelectorAll('tr'));
  sortAsc[idx]=!sortAsc[idx];
  rows.sort(function(a,b){
    var x=a.children[idx].getAttribute('data-v')||a.children[idx].textContent;
    var y=b.children[idx].getAttribute('data-v')||b.children[idx].textContent;
    return sortAsc[idx] ? x.localeCompare(y,'zh') : y.localeCompare(x,'zh');
  });
  rows.forEach(function(r){ tb.appendChild(r); });
}
applyFilter();
</script>
</body>
</html>
"""


def render_html(data: dict, day: date, days: int = 1, summary: dict | None = None) -> str:
    rows = build_rows(data, day)
    summary_html = build_summary(data, day, summary=summary)
    projs = sorted({r["proj"] for r in rows})
    win_start, win_end = _window(data, day)
    multi_day = (win_end - win_start).days > 1
    label = (f"AI 工作日报 · {day.isoformat()}" if days == 1
             else f"AI 工作{days}天汇总 · {win_start.date()} ~ {day.isoformat()}")

    def esc(s: str) -> str:
        return html.escape(str(s or ""))

    def ev_cell(ev: str) -> str:
        """证据列：本地文件给 file:/// 链接，可直接点开核对。"""
        if not ev:
            return ""
        target = ev.split("@")[0] if "@" in ev and not ev.startswith(("http", "C:", "/")) else ev
        if "@" in ev and (":\\" in ev or ":/" in ev):
            target = ev.split("@")[0]
        name = Path(target).name or target
        href = file_url(target) if (":\\" in ev or ":/" in ev or ev.startswith("/")) else ""
        if href:
            return f'<a href="{esc(href)}" title="{esc(ev)}">{esc(name)}</a>'
        return f'<span title="{esc(ev)}">{esc(name)}</span>'

    row_html = []
    for r in rows:
        ts = (r["time"][5:16] if multi_day else r["time"][11:16]) if r["time"] else "—"
        row_html.append(
            f'<tr data-kind="{esc(r["kind"])}" data-proj="{esc(r["proj"])}">'
            f'<td class="t" data-v="{esc(r["time"])}">{esc(ts)}</td>'
            f'<td class="p" data-v="{esc(r["proj"])}">{esc(r["proj"])}</td>'
            f'<td data-v="{esc(r["kind"])}"><span class="badge {KIND_BADGE[r["kind"]]}">{esc(r["kind"])}</span></td>'
            f'<td class="c" data-v="{esc(r["text"][:60])}" title="{esc(r["text"][:400])}">'
            f'<span>{esc(r["text"][:220])}</span></td>'
            f'<td class="ev">{ev_cell(r["ev"])}</td>'
            f"</tr>"
        )

    kind_btns = "".join(
        f'<button class="kind-btn" data-kind="{k}">{k}</button>' for k in KINDS
    )
    proj_opts = "".join(f'<option value="{esc(p)}">{esc(p)}</option>' for p in projs)

    from collections import Counter
    kc = Counter(r["kind"] for r in rows)
    hours = session_hours(data)
    stat_html = [f'<div class="stat"><b>{v}</b><span>{k}</span></div>' for k, v in kc.most_common()]
    if hours:
        stat_html.insert(0, f'<div class="stat"><b>{hours}</b><span>AI 会话时长（含空闲）</span></div>')

    # —— 图表：类型分布（环形） + 项目对比（横向条） + 时间分布（柱状） ——
    proj_counts = Counter(r["proj"] for r in rows)
    if multi_day:
        time_counts = Counter(r["time"][:10] for r in rows if r["time"])
        time_title = "每日产出"
    else:
        time_counts = Counter(r["time"][11:13] + "时" for r in rows if r["time"])
        time_title = "每小时产出"
    charts = [
        svg_donut(kc),
        svg_bars(proj_counts.most_common(8), "项目对比", color="#0ea5e9", horizontal=True),
        svg_bars(sorted(time_counts.items()), time_title, color="#8b5cf6", full=True),
    ]

    out = (HTML_TEMPLATE
           .replace("__DATE__", label)
           .replace("__TITLE__", label)
           .replace("__NOW__", datetime.now().strftime("%Y-%m-%d %H:%M"))
           .replace("__SUMMARY__", "\n".join(summary_html))
           .replace("__DIGEST_NOTE__",
                    ("✍️ 本节摘要由 <b>Agent 基于事件层改写（人话版）</b>；证据与全量记录见下方明细表。"
                     if summary else
                     "只列用户看得懂的功能与成果；内部工程细节（单测/脚手架/日志…）不进这里，全量记录见下方明细表。"))
           .replace("__KIND_BTNS__", kind_btns)
           .replace("__PROJ_OPTS__", proj_opts)
           .replace("__ROWS__", "\n".join(row_html))
           .replace("__STATS__", "".join(stat_html))
           .replace("__CHARTS__", "".join(charts)))
    return out
