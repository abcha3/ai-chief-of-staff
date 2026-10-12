#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Chief of Staff — MVP
跨工具、跨项目的「AI 工作履历」采集与日报生成。

用法：
    python aicos.py all    --date 2026-10-09     # 采集 + 生成日报
    python aicos.py scan   --out out             # 只产 events.json
    python aicos.py report --date 2026-10-09     # 只产日报（读取 events.json）

纯标准库；zstd 解压优先 compression.zstd（Py3.14+），回退 zstandard 包。
所有数据源均为只读；产物仅落在 --out 目录。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zlib
from collections import Counter, defaultdict
from datetime import datetime, date, time, timedelta
from pathlib import Path

# Windows 控制台默认 GBK，统一按 UTF-8 输出，避免日志乱码
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ----------------------------------------------------------------------------
# 基础工具
# ----------------------------------------------------------------------------

def _out(msg: str) -> None:
    print(msg, file=sys.stderr)


def zstd_decompress(data: bytes) -> bytes:
    try:
        from compression.zstd import decompress  # Python 3.14+
        return decompress(data)
    except ImportError:
        pass
    import zstandard  # 可选依赖
    return zstandard.ZstdDecompressor().decompress(data)


def parse_iso(ts: str) -> datetime | None:
    try:
        # 统一转成「本地时区、naive」，与 ms_to_dt / git reflog 口径一致
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except Exception:
        return None


def ms_to_dt(ms: int | float) -> datetime | None:
    try:
        return datetime.fromtimestamp(ms / 1000.0)
    except Exception:
        return None


def clean_text(s: str, limit: int = 300) -> str:
    """去掉 bridge/app 上下文包裹等噪音，压平空白并截断。"""
    if not s:
        return ""
    s = re.sub(r"<(bridge_context|bridge_instructions|app-context)>[\s\S]*?</\1>", " ", s)
    s = re.sub(r"<(system-reminder)>[\s\S]*?</\1>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def clip(s: str, n: int) -> str:
    """截断并补省略号（不切断语义后再补）。"""
    s = clean_text(s, n + 5)
    return s[:n] + ("…" if len(s) > n else "")


GENERIC_TITLES = {"你好", "hi", "hello", "hey", "继续", "继续任务", "好了", "做", "ok", "okay",
                  "在吗", "test", "测试", "帮个忙", "帮忙"}


def session_title(ev: dict) -> str:
    """会话标题：优先会话自带标题；"你好/继续"这类无信息标题则取第一条有信息量的用户消息。"""
    t = (ev.get("title") or "").strip()
    if t and t.lower() not in GENERIC_TITLES and len(t) >= 4:
        return t
    for p in ev.get("prompts") or []:
        txt = (p.get("text") or "").strip()
        if len(txt) >= 8 and txt.lower() not in GENERIC_TITLES:
            return clip(txt, 32)
    return (ev.get("session_id") or "")[:16] or "(无标题)"


def texts_of_content(content) -> str:
    """把 message.content（str 或 block 列表）拍平成纯文本（不含 thinking/reasoning）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") in ("text", "input_text", "output_text"):
                parts.append(b.get("text") or "")
        return "\n".join(parts)
    return ""


NOISE_PREFIXES = (
    "current runtime context", "the approval policy changed", "background job ",
    "background subagent ", "this is an automatically generated checkpoint",
    "[model changed", "current dsh file policy", "system-reminder",
    "<goal_round", "<goal_complete", "<goal_blocked",
)


def is_noise(text: str) -> bool:
    """系统注入的运行时上下文/通知，不是真正的用户指令。"""
    low = (text or "").strip().lower()
    return (not low) or any(low.startswith(p) for p in NOISE_PREFIXES)


# ----------------------------------------------------------------------------
# 分类器（关键词启发式；V1 可换 LLM）
# ----------------------------------------------------------------------------

CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("fix", ["修复", "修了", "修好", "bug", "报错", "报了", "错误", "异常", "闪退", "崩溃", "不工作", "用不了",
             "失败", "fix", "fixed", "error", "crash", "broken", "issue", "排查", "调试", "debug"]),
    ("decision", ["为什么", "方案", "选型", "架构", "决定", "决策", "取舍", "权衡", "改为", "放弃", "换成",
                  "选择", "对比后", "trade-off", "decide", "decision", "chose", "instead of", "vs ",
                  "重构", "refactor"]),
    ("research", ["调研", "搜索", "搜一下", "查一下", "查查", "对比", "评测", "口碑", "分析", "研究",
                  "research", "review", "compare", "survey", "market"]),
]


def classify(text: str) -> set[str]:
    low = (text or "").lower()
    cats = set()
    for cat, kws in CATEGORY_RULES:
        if any(k.lower() in low for k in kws):
            cats.add(cat)
    return cats


# ----------------------------------------------------------------------------
# 会话事件（事实层 → 事件层）
# ----------------------------------------------------------------------------

class SessionEvent(dict):
    """dict 子类，方便直接 json.dump。"""


def new_event() -> SessionEvent:
    return SessionEvent(
        tool="", session_id="", project="", title="", start="", end="",
        prompts=[], outcomes=[], deliverables=[], todos=[], decisions=[],
        files_touched=[], tool_counts={}, approvals=[], searches=[], subagents=[],
        categories=[], evidence={},
    )


WRITING_TOOLS = {"write", "edit", "multi_edit", "multiedit", "notebookedit", "create", "apply_patch",
                 "Write", "Edit", "MultiEdit", "NotebookEdit"}


# ----------------------------------------------------------------------------
# 适配器：DeepSeek Harness
# ----------------------------------------------------------------------------

def collect_dsh(root: Path, win_start: datetime, win_end: datetime) -> list[SessionEvent]:
    events: list[SessionEvent] = []
    if not root.exists():
        return events
    for sess_file in root.glob("*/*/session.v3.jsonl*"):
        try:
            raw = sess_file.read_bytes()
            if sess_file.suffix == ".zstd" or raw[:4] == b"\x28\xb5\x2f\xfd":
                text = zstd_decompress(raw).decode("utf-8", errors="replace")
            else:
                text = raw.decode("utf-8", errors="replace")
        except Exception as e:
            _out(f"[dsh] 跳过 {sess_file}：{e}")
            continue

        ev = new_event()
        ev["tool"] = "dsh"
        ev["evidence"] = {"source": "dsh", "session_path": str(sess_file)}
        turn_last_text: dict[int, str] = {}
        first_ts = last_ts = None

        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            rtype = rec.get("type", "")
            data = rec.get("data") or {}
            ts = ms_to_dt(rec["time"]) if rec.get("time") else None
            if ts is None and rec.get("createdAt"):
                ts = ms_to_dt(rec["createdAt"])
            if ts:
                first_ts = first_ts or ts
                last_ts = max(last_ts, ts) if last_ts else ts

            if rtype == "session":
                ev["session_id"] = data.get("id") or rec.get("id") or ""
                ev["project"] = data.get("cwd") or rec.get("cwd") or ""
            elif rtype == "session/title":
                ev["title"] = data.get("title") or ""
            elif rtype == "user/message":
                t = clean_text(texts_of_content(data.get("content")))
                if t and not is_noise(t):
                    ev["prompts"].append({"time": ts.isoformat() if ts else "", "text": t})
            elif rtype == "assistant/message":
                msg = data.get("message") or {}
                t = clean_text(texts_of_content(msg.get("content")), 500)
                turn = data.get("turn") or 0
                if t:
                    turn_last_text[turn] = t
            elif rtype == "tool/call":
                name = data.get("name") or "?"
                ev["tool_counts"][name] = ev["tool_counts"].get(name, 0) + 1
                if name in WRITING_TOOLS:
                    try:
                        args = json.loads(data.get("arguments") or "{}")
                        p = args.get("file_path") or args.get("path")
                        if p:
                            ev["files_touched"].append(str(p))
                    except Exception:
                        pass
            elif rtype == "deliverables/presented":
                for f in data.get("files") or []:
                    ev["deliverables"].append({"path": f.get("path", ""), "description": f.get("description", "")})
            elif rtype == "todo/write":
                todos = [{"content": t.get("content", ""), "status": t.get("status", "")}
                         for t in (data.get("todos") or [])]
                if todos:
                    ev["todos"] = todos  # 保留最后一份任务清单
            elif rtype == "compaction/summary":
                for blk in data.get("summary") or []:
                    txt = blk.get("text", "") if isinstance(blk, dict) else ""
                    for line2 in txt.splitlines():
                        s = line2.strip().lstrip("-*").strip()
                        if s and classify(s) & {"decision"} and len(s) > 12:
                            ev["decisions"].append(clean_text(s, 240))
            elif rtype == "approval/asked":
                ev["approvals"].append(clean_text(data.get("reason", ""), 200))
            elif rtype == "subagent/catalog":
                ev["subagents"].append(data.get("label") or data.get("childId") or "")
            elif rtype in ("web/deepseek-search-llm-request", "web/search-llm-request"):
                body = data.get("body") or {}
                for m in body.get("messages") or []:
                    ev["searches"].append(clean_text(texts_of_content(m.get("content")), 160))

        if not ev["session_id"]:
            ev["session_id"] = sess_file.parent.name
        if not ev["project"]:
            ev["project"] = sess_file.parent.parent.name

        ev["start"] = first_ts.isoformat() if first_ts else ""
        ev["end"] = last_ts.isoformat() if last_ts else ""
        ev["outcomes"] = [t for _, t in sorted(turn_last_text.items())][-3:]

        # 时间窗过滤：会话与窗口有交集即纳入；窗口内记录单独标注
        if first_ts and last_ts and (last_ts < win_start or first_ts >= win_end):
            continue
        events.append(ev)
    return events


# ----------------------------------------------------------------------------
# 适配器：Claude Code
# ----------------------------------------------------------------------------

def collect_claude(root: Path, history: Path, win_start: datetime, win_end: datetime) -> list[SessionEvent]:
    events: list[SessionEvent] = []
    if root.exists():
        for f in root.glob("*/*.jsonl"):
            ev = new_event()
            ev["tool"] = "claude-code"
            ev["evidence"] = {"source": "claude-code", "session_path": str(f)}
            ev["session_id"] = f.stem
            first_ts = last_ts = None
            last_texts: list[str] = []
            try:
                for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    ts = parse_iso(rec.get("timestamp") or "")
                    if ts:
                        first_ts = first_ts or ts
                        last_ts = max(last_ts, ts) if last_ts else ts
                    rtype = rec.get("type")
                    msg = rec.get("message") or {}
                    if rtype == "user":
                        t = clean_text(texts_of_content(msg.get("content")))
                        if t and not is_noise(t):
                            ev["prompts"].append({"time": ts.isoformat() if ts else "", "text": t})
                        ev["project"] = ev["project"] or rec.get("cwd") or ""
                    elif rtype == "assistant":
                        ev["project"] = ev["project"] or rec.get("cwd") or ""
                        content = msg.get("content")
                        blocks = content if isinstance(content, list) else []
                        for b in blocks:
                            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in WRITING_TOOLS:
                                p = (b.get("input") or {}).get("file_path")
                                if p:
                                    ev["files_touched"].append(str(p))
                            if isinstance(b, dict) and b.get("type") == "tool_use":
                                ev["tool_counts"][b.get("name", "?")] = ev["tool_counts"].get(b.get("name", "?"), 0) + 1
                        t = clean_text(texts_of_content(content), 500)
                        if t and len(t) > 60:
                            last_texts.append(t)
            except Exception as e:
                _out(f"[claude] 跳过 {f}：{e}")
                continue
            ev["start"] = first_ts.isoformat() if first_ts else ""
            ev["end"] = last_ts.isoformat() if last_ts else ""
            ev["outcomes"] = last_texts[-3:]
            if first_ts and last_ts and (last_ts < win_start or first_ts >= win_end):
                continue
            if first_ts:
                events.append(ev)

    # history.jsonl：补充 prompt 史（不单独成事件，仅补到已有项目？MVP 独立小事件）
    if history.exists():
        by_sess: dict[str, SessionEvent] = {}
        try:
            for line in history.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                ts = ms_to_dt(rec.get("timestamp") or 0)
                if not ts or ts < win_start or ts >= win_end:
                    continue
                sid = rec.get("sessionId") or ""
                if sid not in by_sess:
                    ev = new_event()
                    ev["tool"] = "claude-code-history"
                    ev["session_id"] = sid
                    ev["project"] = rec.get("project") or ""
                    ev["evidence"] = {"source": "claude-code-history", "session_path": str(history)}
                    by_sess[sid] = ev
                by_sess[sid]["prompts"].append({"time": ts.isoformat(), "text": clean_text(rec.get("display", ""))})
        except Exception as e:
            _out(f"[claude-history] 跳过：{e}")
        for ev in by_sess.values():
            ev["prompts"] = [p for p in ev["prompts"] if not is_noise(p["text"])]
            if ev["prompts"]:
                events.append(ev)
    return events


# ----------------------------------------------------------------------------
# 适配器：Codex
# ----------------------------------------------------------------------------

def collect_codex(root: Path, win_start: datetime, win_end: datetime) -> list[SessionEvent]:
    events: list[SessionEvent] = []
    if not root.exists():
        return events
    for f in root.glob("**/rollout-*.jsonl"):
        ev = new_event()
        ev["tool"] = "codex"
        ev["evidence"] = {"source": "codex", "session_path": str(f)}
        first_ts = last_ts = None
        last_texts: list[str] = []
        try:
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                ts = parse_iso(rec.get("timestamp") or "")
                if ts:
                    first_ts = first_ts or ts
                    last_ts = max(last_ts, ts) if last_ts else ts
                rtype = rec.get("type")
                payload = rec.get("payload") or {}
                if rtype == "session_meta":
                    ev["session_id"] = payload.get("session_id") or payload.get("id") or ""
                    ev["project"] = payload.get("cwd") or ""
                elif rtype == "response_item" and payload.get("type") == "message":
                    role = payload.get("role")
                    t = clean_text(texts_of_content(payload.get("content")), 500)
                    if role == "user" and t and not is_noise(t):
                        ev["prompts"].append({"time": ts.isoformat() if ts else "", "text": t})
                    elif role == "assistant" and t and len(t) > 60:
                        last_texts.append(t)
                elif rtype == "response_item" and payload.get("type") in ("function_call", "local_shell_call"):
                    name = payload.get("name") or "shell"
                    ev["tool_counts"][name] = ev["tool_counts"].get(name, 0) + 1
        except Exception as e:
            _out(f"[codex] 跳过 {f}：{e}")
            continue
        ev["start"] = first_ts.isoformat() if first_ts else ""
        ev["end"] = last_ts.isoformat() if last_ts else ""
        ev["outcomes"] = last_texts[-3:]
        if first_ts and last_ts and (last_ts < win_start or first_ts >= win_end):
            continue
        if first_ts:
            events.append(ev)
    return events


# ----------------------------------------------------------------------------
# 带剪枝的目录遍历（glob('**') 在用户主目录等大树上会走几分钟，必须剪枝 + 限深）
# ----------------------------------------------------------------------------

SKIP_DIRS = {"node_modules", "__pycache__", ".venv", "venv", ".cache", "AppData",
             ".npm", ".nuget", ".gradle", ".idea", ".vs", ".vscode", "Library",
             "Applications", "Windows", "Program Files", "Program Files (x86)",
             "$RECYCLE.BIN", "System Volume Information", ".Trash", ".git",
             "dist", "build", "target", "out", ".next", ".nuxt", "coverage",
             ".tox", ".mypy_cache", ".pytest_cache", "site-packages"}


def iter_paths(root: Path, target_name: str = "", suffix: str = "",
               want_dir: bool = False, max_depth: int = 4):
    """遍历 root：产出名为 target_name 或以 suffix 结尾的条目；want_dir=True 时只找目录。"""
    stack = [(Path(root), 0)]
    while stack:
        d, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            entries = list(os.scandir(d))
        except (PermissionError, OSError):
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if want_dir and entry.name == target_name:
                        yield Path(entry.path)
                    if entry.name not in SKIP_DIRS:
                        stack.append((Path(entry.path), depth + 1))
                elif not want_dir and entry.is_file():
                    if (target_name and entry.name == target_name) or \
                            (suffix and entry.name.endswith(suffix)):
                        yield Path(entry.path)
            except OSError:
                continue


# ----------------------------------------------------------------------------
# 适配器：其它 AI 工具（实验性 · 通用启发式抽取）
# 用最少的每工具代码覆盖"电脑上所有 AI"：能读出对话就抽取对话，
# 读不出就至少留下"活动痕迹"（项目 + 时间 + 文件证据）。格式不对时静默降级。
# ----------------------------------------------------------------------------

TEXT_ROLES = {"user", "human", "assistant", "ai", "model", "agent"}


def harvest_texts(obj, out: list, budget: list, limit: int = 150) -> None:
    """递归收割 {role, text} 对话片段（通用启发式，带预算防止大文件拖垮）。"""
    if budget[0] <= 0 or len(out) >= limit:
        return
    if isinstance(obj, dict):
        budget[0] -= 1
        role = str(obj.get("role") or obj.get("type") or "").lower()
        text = obj.get("text")
        if not isinstance(text, str):
            content = obj.get("content") or obj.get("message")
            if isinstance(content, str):
                text = content
        if role in TEXT_ROLES and isinstance(text, str) and 2 < len(text) < 4000:
            out.append((role, text))
        for v in obj.values():
            harvest_texts(v, out, budget, limit)
    elif isinstance(obj, list):
        for v in obj[:200]:
            harvest_texts(v, out, budget, limit)


def _project_from_cursor_ws(dirpath: Path) -> str:
    """Cursor/Windsurf workspaceStorage/<hash>/workspace.json → 项目目录。"""
    for name in ("workspace.json", "workspaceState.json"):
        f = dirpath / name
        if f.exists():
            try:
                obj = json.loads(f.read_text(encoding="utf-8", errors="replace"))
                folder = (obj.get("folder") or "").replace("file:///", "").replace("file://", "")
                if folder:
                    return str(Path(folder))
            except Exception:
                pass
    return ""


def collect_vscode_forks(name: str, root: Path, win_start: datetime, win_end: datetime) -> list[SessionEvent]:
    """Cursor / Windsurf / VS Code fork：workspaceStorage + state.vscdb（SQLite，尽力读取对话）。"""
    events: list[SessionEvent] = []
    if not root.exists():
        return events
    for ws in root.glob("*"):
        if not ws.is_dir():
            continue
        db = ws / "state.vscdb"
        if not db.exists():
            continue
        mt = datetime.fromtimestamp(db.stat().st_mtime)
        if mt < win_start - timedelta(days=1) or mt >= win_end:
            continue
        ev = new_event()
        ev["tool"] = name
        ev["project"] = _project_from_cursor_ws(ws) or ws.name
        ev["session_id"] = ws.name
        ev["start"] = ev["end"] = mt.isoformat()
        ev["evidence"] = {"source": name, "session_path": str(db)}
        # 尽力从 SQLite 里抽对话（不同版本表名不同，取不到就只留活动痕迹）
        try:
            import sqlite3
            uri = "file:" + str(db).replace("\\", "/") + "?mode=ro"
            con = sqlite3.connect(uri, uri=True)
            try:
                tables = [r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")]
                pairs: list = []
                for tb in ("cursorDiskKV", "ItemTable", "cursorDiskKV_v2"):
                    if tb in tables:
                        try:
                            rows = con.execute(f"SELECT key, value FROM {tb} LIMIT 400").fetchall()
                        except Exception:
                            continue
                        for k, v in rows:
                            ks = str(k)
                            if not any(t in ks.lower() for t in ("composer", "chat", "prompt", "message")):
                                continue
                            if isinstance(v, bytes):
                                v = v.decode("utf-8", errors="replace")
                            try:
                                harvest_texts(json.loads(v), pairs, [20000])
                            except Exception:
                                pass
                        if pairs:
                            break
                for role, text in pairs[:60]:
                    t = clean_text(text)
                    if not t or is_noise(t):
                        continue
                    (ev["prompts"] if role in ("user", "human") else ev["outcomes"]).append(
                        {"time": ev["end"], "text": t} if role in ("user", "human") else t)
            finally:
                con.close()
        except Exception:
            pass  # SQLite 读不了就只留活动痕迹
        events.append(ev)
    return events


def collect_generic_json(name: str, root: Path, pattern: str,
                         win_start: datetime, win_end: datetime,
                         max_files: int = 40) -> list[SessionEvent]:
    """Gemini CLI / opencode 等：按 mtime 扫 JSON，通用收割对话片段。"""
    events: list[SessionEvent] = []
    if not root.exists():
        return events
    files = [f for f in iter_paths(root, suffix=".json", max_depth=5)
             if win_start - timedelta(days=1) <= datetime.fromtimestamp(f.stat().st_mtime) < win_end]
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    by_dir: dict[Path, SessionEvent] = {}
    for f in files[:max_files]:
        d = f.parent
        if d not in by_dir:
            ev = new_event()
            ev["tool"] = name
            ev["session_id"] = d.name[:24]
            ev["project"] = d.name
            ev["evidence"] = {"source": name, "session_path": str(f)}
            by_dir[d] = ev
        ev = by_dir[d]
        mt = datetime.fromtimestamp(f.stat().st_mtime)
        ev["start"] = ev["start"] or mt.isoformat()
        ev["end"] = mt.isoformat()
        try:
            obj = json.loads(f.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        pairs: list = []
        harvest_texts(obj, pairs, [20000])
        for role, text in pairs[:40]:
            t = clean_text(text)
            if not t or is_noise(t):
                continue
            if role in ("user", "human"):
                ev["prompts"].append({"time": mt.isoformat(), "text": t})
            else:
                ev["outcomes"].append(t)
    return list(by_dir.values())


def collect_aider(repo_roots: list[Path], win_start: datetime, win_end: datetime) -> list[SessionEvent]:
    """Aider：仓库内的 .aider.chat.history.md（按 mtime 过滤）。"""
    events: list[SessionEvent] = []
    for root in repo_roots:
        if not root.exists():
            continue
        for f in iter_paths(root, target_name=".aider.chat.history.md", max_depth=5):
            try:
                mt = datetime.fromtimestamp(f.stat().st_mtime)
            except Exception:
                continue
            if mt < win_start or mt >= win_end:
                continue
            ev = new_event()
            ev["tool"] = "aider"
            ev["project"] = str(f.parent)
            ev["session_id"] = f.name
            ev["start"] = ev["end"] = mt.isoformat()
            ev["evidence"] = {"source": "aider", "session_path": str(f)}
            try:
                head = f.read_text(encoding="utf-8", errors="replace")[:8000]
                ev["outcomes"].append(clean_text(head, 400))
            except Exception:
                pass
            events.append(ev)
    return events


# ----------------------------------------------------------------------------
# 适配器：git reflog（纯文件读取，不依赖 git.exe）
# ----------------------------------------------------------------------------

def collect_git(repo_roots: list[Path], win_start: datetime, win_end: datetime) -> list[dict]:
    commits: list[dict] = []
    seen: set[Path] = set()
    for root in repo_roots:
        if not root.exists():
            continue
        for gitdir in iter_paths(root, target_name=".git", want_dir=True, max_depth=4):
            if gitdir in seen:
                continue
            seen.add(gitdir)
            repo = gitdir.parent
            head_log = gitdir / "logs" / "HEAD"
            if not head_log.exists():
                continue
            try:
                for line in head_log.read_text(encoding="utf-8", errors="replace").splitlines():
                    m = re.match(r"^(\w{7,40}) (\w{7,40}) (.+?) <(.+?)> (\d+) ([+-]\d{4})\t(.*)$", line)
                    if not m:
                        continue
                    ts = datetime.fromtimestamp(int(m.group(5)))
                    if ts < win_start or ts >= win_end:
                        continue
                    commits.append({
                        "repo": str(repo), "sha": m.group(2)[:8],
                        "author": m.group(3), "time": ts.isoformat(),
                        "message": clean_text(m.group(7), 200),
                    })
            except Exception as e:
                _out(f"[git] 跳过 {repo}：{e}")
    commits.sort(key=lambda c: c["time"])
    return commits


# ----------------------------------------------------------------------------
# 事件层构建 + 日报渲染
# ----------------------------------------------------------------------------

# ----------------------------------------------------------------------------
# 适配器：WorkBuddy 桌面端 / CodeBuddy CLI（实验）
# ----------------------------------------------------------------------------

def _wb_task_todos(root: Path, evs: dict[str, SessionEvent]) -> None:
    """tasks/<uuid>/N.json —— 任务清单（subject/description/status），按 uuid 挂到会话。"""
    for f in root.glob("tasks/*/*.json"):
        try:
            j = json.loads(f.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        ev = evs.get(f.parent.name)
        if ev is None or not j.get("subject"):
            continue
        ev["todos"].append({
            "content": clean_text(j.get("subject", ""), 120),
            "status": "completed" if j.get("status") == "completed" else str(j.get("status", "")),
        })


def _overlaps(ev: SessionEvent, win_start: datetime, win_end: datetime) -> bool:
    """会话与时间窗是否有交集（无时间信息的保留）。"""
    try:
        s = datetime.fromisoformat(ev["start"]) if ev["start"] else None
        e = datetime.fromisoformat(ev["end"]) if ev["end"] else None
    except Exception:
        s = e = None
    if not s and not e:
        return True
    s, e = s or e, e or s
    return not (e < win_start or s >= win_end)


def collect_workbuddy(root: Path, win_start: datetime, win_end: datetime) -> list[SessionEvent]:
    """WorkBuddy 桌面端：workbuddy.db（sessions / automations / automation_runs）+ tasks/。
    automation_runs.thread_title 是 AI 自己的任务汇报——「干了什么」的金矿。"""
    import sqlite3
    events: list[SessionEvent] = []
    if not root.exists():
        return events
    evs: dict[str, SessionEvent] = {}
    db = root / "workbuddy.db"
    if db.exists():
        try:
            con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        except Exception as e:
            _out(f"[workbuddy] 打不开 {db}：{e}")
            con = None
        if con:
            try:
                for sid, cwd, title, ctitle, ca, ua in con.execute(
                        "SELECT id,cwd,title,custom_title,created_at,updated_at FROM sessions"):
                    ev = new_event()
                    ev["tool"] = "workbuddy"
                    ev["session_id"] = sid
                    ev["project"] = cwd or ""
                    ev["title"] = ctitle or title or ""
                    ev["start"] = ms_to_dt(ca).isoformat() if ca else ""
                    ev["end"] = ms_to_dt(ua).isoformat() if ua else ""
                    ev["evidence"] = {"source": "workbuddy", "session_path": str(db)}
                    evs[sid] = ev
                # 自动化任务的每次运行 = 一次真实 AI 工作，thread_title 是它的汇报
                for tid, aid, ttitle, cwd, runs_json, ca in con.execute(
                        "SELECT thread_id,automation_id,thread_title,source_cwd,runs_json,created_at"
                        " FROM automation_runs"):
                    name = aid
                    for nm, in con.execute("SELECT name FROM automations WHERE id=?", (aid,)):
                        name = nm or aid
                    ev = new_event()
                    ev["tool"] = "workbuddy"
                    ev["session_id"] = tid or aid
                    ev["project"] = cwd or ""
                    ev["title"] = f"自动化任务：{name}"
                    ev["evidence"] = {"source": "workbuddy", "session_path": str(db)}
                    ev["start"] = ms_to_dt(ca).isoformat() if ca else ""
                    ev["end"] = ev["start"]
                    if ttitle:
                        ev["outcomes"].append(clean_text(ttitle, 500))
                    try:
                        for r in json.loads(runs_json or "[]"):
                            s0 = ms_to_dt(r.get("startedAt")) if r.get("startedAt") else None
                            s1 = ms_to_dt(r.get("finishedAt")) if r.get("finishedAt") else None
                            if s0:
                                ev["start"] = s0.isoformat()
                            if s1:
                                ev["end"] = s1.isoformat()
                    except Exception:
                        pass
                    evs[tid or aid] = ev
            finally:
                con.close()
    _wb_task_todos(root, evs)
    for ev in evs.values():
        if _overlaps(ev, win_start, win_end):
            events.append(ev)
    return events


def collect_codebuddy(root: Path, win_start: datetime, win_end: datetime) -> list[SessionEvent]:
    """CodeBuddy CLI：projects/<编码路径>/<uuid>.jsonl（message / ai-title / cwd）+ tasks/。"""
    events: list[SessionEvent] = []
    if not root.exists():
        return events
    evs: dict[str, SessionEvent] = {}
    for f in root.glob("projects/*/*.jsonl"):
        ev = new_event()
        ev["tool"] = "codebuddy"
        ev["evidence"] = {"source": "codebuddy", "session_path": str(f)}
        first_ts = last_ts = None
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    ts = ms_to_dt(rec.get("timestamp")) if rec.get("timestamp") else None
                    if ts:
                        first_ts = first_ts or ts
                        last_ts = max(last_ts, ts) if last_ts else ts
                    ev["project"] = rec.get("cwd") or ev["project"]
                    ev["session_id"] = rec.get("sessionId") or ev["session_id"] or f.stem
                    typ = rec.get("type", "")
                    if typ == "ai-title":
                        ev["title"] = rec.get("aiTitle") or ev["title"]
                    elif typ == "message":
                        content = rec.get("content")
                        blocks = content if isinstance(content, list) else [{"text": str(content or "")}]
                        txt = clean_text(" ".join(b.get("text", "") for b in blocks
                                                  if isinstance(b, dict)), 500)
                        if rec.get("role") == "user" and txt and not is_noise(txt):
                            ev["prompts"].append({"time": ts.isoformat() if ts else "", "text": txt})
                        elif rec.get("role") == "assistant" and txt:
                            ev["outcomes"].append(txt)
        except Exception as e:
            _out(f"[codebuddy] 跳过 {f}：{e}")
            continue
        if first_ts:
            ev["start"] = first_ts.isoformat()
            ev["end"] = (last_ts or first_ts).isoformat()
        if ev["prompts"] or ev["outcomes"]:
            ev["outcomes"] = ev["outcomes"][-12:]
            evs[ev["session_id"] or f.stem] = ev
    _wb_task_todos(root, evs)
    for ev in evs.values():
        if _overlaps(ev, win_start, win_end):
            events.append(ev)
    return events


def build_events(dsh_root, claude_root, claude_history, codex_root, repo_roots,
                 win_start: datetime, win_end: datetime) -> dict:
    sessions = []
    sessions += collect_dsh(dsh_root, win_start, win_end)
    sessions += collect_claude(claude_root, claude_history, win_start, win_end)
    sessions += collect_codex(codex_root, win_start, win_end)
    # 实验性：其它 AI 工具（能读出对话就抽对话，读不出就留活动痕迹）
    appdata = Path(os.getenv("APPDATA") or "")
    home = Path.home()
    sessions += collect_workbuddy(home / ".workbuddy", win_start, win_end)
    sessions += collect_codebuddy(home / ".codebuddy", win_start, win_end)
    sessions += collect_vscode_forks("cursor", appdata / "Cursor" / "User" / "workspaceStorage", win_start, win_end)
    sessions += collect_vscode_forks("windsurf", appdata / "Windsurf" / "User" / "workspaceStorage", win_start, win_end)
    sessions += collect_generic_json("gemini-cli", home / ".gemini", "tmp/**/*.json", win_start, win_end)
    sessions += collect_generic_json("opencode", home / ".local" / "share" / "opencode", "storage/**/*.json", win_start, win_end)
    aider_roots = list(repo_roots) + [Path(s["project"]) for s in sessions if s.get("project")]
    sessions += collect_aider(aider_roots, win_start, win_end)
    for ev in sessions:
        blob = " ".join([
            ev.get("title", ""),
            " ".join(p["text"] for p in ev["prompts"]),
            " ".join(d.get("description", "") for d in ev["deliverables"]),
            " ".join(ev["outcomes"]),
        ])
        ev["categories"] = sorted(classify(blob)) or ["feature"]
        # 摘要条目（供日报分组）：prompt / 产出 / 交付 / 决策 各自打标签
    sessions.sort(key=lambda e: (e.get("project") or "", e.get("start") or ""))
    commits = collect_git(repo_roots, win_start, win_end)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window": {"start": win_start.isoformat(), "end": win_end.isoformat()},
        "sessions": sessions,
        "git_commits": commits,
    }


def _pool(evs, in_window) -> list[tuple[str, str]]:
    """条目池：以**用户发给 AI 的消息**为主线，其后才是交付/任务/AI 收尾陈述。"""
    pool: list[tuple[str, str]] = []
    for e in evs:
        for p in e["prompts"]:
            if in_window(p["time"]):
                pool.append((p["text"], "prompt"))
        for d in e["deliverables"]:
            pool.append((f"交付 `{Path(d['path']).name}`：{d['description'][:120]}", "deliverable"))
        for t in e["todos"]:
            if t.get("status") == "completed":
                pool.append((f"完成任务：{t['content'][:120]}", "todo"))
        for o in e["outcomes"]:
            pool.append((o, "outcome"))
    return pool


# 「用户看得懂的功能」启发式：功能词加分、内部工程词减分
FEATURE_MARKS = ("支持", "新增", "上线", "发布", "完成", "实现", "加入", "开放", "交付", "搞定",
                 "推出", "优化", "修复", "解决", "打通", "接入", "导出", "分享", "生成", "一键",
                 "自动", "可以", "登录", "注册", "撤回", "退回", "预览", "切换", "落地", "收工",
                 "support", "add", "implement", "launch", "release", "finish", "built", "fixed")
INTERNAL_MARKS = ("单测", "自检", "断言", "测试用例", "test", "ci", "lint", "格式化", "rename",
                  "refactor", "脚手架", "初始化", "工程骨架", "依赖", "版本号", "升级", "日志",
                  "告警", "白名单", "协议层", "变量名", "chore", "docs", "readme", "注释",
                  "snapshot", "迁移", "migration", "埋点", "打点", "纯逻辑", "工具函数", "类型体操")


def importance(text: str) -> int:
    """粗判一句话是「用户看得懂的功能」(+分) 还是「内部工程细节」(-分)。"""
    low = (text or "").lower()
    score = sum(1 for m in FEATURE_MARKS if m in low)
    score -= 2 * sum(1 for m in INTERNAL_MARKS if m in low)
    return score


def plain_phrase(s: str) -> str:
    """去掉工程黑话外壳：markdown 记号、代码标识符、文件名、里程碑编号。"""
    s = clean_text(s, 240).lstrip("# ").strip()
    s = re.sub(r"\*\*|__|~~|`[^`]*`", "", s)                          # markdown 强调/代码
    s = re.sub(r"[A-Za-z0-9_\-./\\]+\.(?:py|js|ts|tsx|jsx|json|md|kt|java|go|rs|css|html|mjs|sql|yml|yaml|toml)\b", "", s)
    s = re.sub(r"^[PpMmVv]\d[\w\-①②③④⑤⑥⑦⑧⑨]*[：:、\-）)]?\s*", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip(" -—:：·、，,　+＋*=【】")


def _trim_dangling(s: str) -> str:
    """剪掉尾巴上的悬空虚词/符号（"…抗 NaN +" / "…在可用模型列表中找到了"）。"""
    s = s.strip(" -—:：·、，,　+＋*=【】")
    while s and s[-1] in "在了的和与把被就都很是及跟给向让从由对于":
        s = s[:-1].strip(" -—:：·、，,　+＋*=【】")
    return s


def short_phrase(s: str) -> str:
    """大字标题用的简略说法：在破折号/冒号/标点边界截断，宁短勿断词。"""
    s = plain_phrase(s)
    for sep in ("—", "——", "：", "（", "(", "【"):
        i = s.find(sep)
        if i >= 6 and len(s) > 24:
            s = s[:i]
    if len(s) > 30:
        cut = max(s.rfind(c, 0, 30) for c in "，、； 　")
        s = s[:cut] if cut >= 10 else s[:30]
    return _trim_dangling(s)


def clip_sentence(s: str, limit: int = 60) -> str:
    """小字细节：在句读边界截断，宁短勿断词。"""
    s = plain_phrase(s)
    if len(s) <= limit:
        return _trim_dangling(s) if len(s) <= 30 else s
    cut = max(s.rfind(c, 0, limit) for c in "。；;，、 　")
    return (s[:cut] if cut >= 12 else s[:limit]).strip(" -—:：·、，,　")


def _looks_like_question(t: str) -> bool:
    """会话标题是疑问句时，不适合当「AI 名字」。"""
    return bool(re.search(r"[？?]|吗$|怎么|如何|为什么|能否|是否|是不是|多少|哪个", t))


def digest_line(proj: str, evs: list, in_window, commits: list[dict]) -> tuple[str, str, list[str], str]:
    """「每个 AI 完成了哪些重要功能」→ (名字, 大字标题, 小字细节[], 统计串)。
    只挑用户看得懂的功能/成果，内部工程细节（单测/脚手架/日志…）不进摘要。
    素材只取 AI 自己的工作记录（任务清单/交付描述/提交信息），不照抄用户原话。"""
    dones = [t.get("content", "") for e in evs for t in (e.get("todos") or [])
             if t.get("status") == "completed"]
    delivs = [d for e in evs for d in (e.get("deliverables") or [])]
    outcomes = [o for e in evs for o in (e.get("outcomes") or [])]
    pcommits = [c for c in commits
                if Path(c["repo"]).as_posix().lower() in Path(proj).as_posix().lower()
                or Path(proj).as_posix().lower() in Path(c["repo"]).as_posix().lower()]
    # 修复计数只看 AI 自己的工作记录（任务/收尾/交付描述），不含用户消息，避免"谈论修复"被误计
    fix_n = len([t for t in dones + outcomes + [d.get("description", "") for d in delivs]
                 if "fix" in classify(t)])
    name = Path(proj).name or proj
    # 目录名是日期串/编号（WorkBuddy 等）时，用会话标题当「AI 名字」——更像名字
    if re.match(r"^\d{4}-\d{2}-\d{2}", name) or name.isdigit() or name.lower() in ("default", "1"):
        titles = [clean_text(e.get("title", ""), 30) for e in evs if e.get("title")]
        good = [t for t in titles if not _looks_like_question(t)]
        pool = good or titles
        if pool:
            name = max(set(pool), key=pool.count)

    def strip_commit(m: str) -> str:
        m = re.sub(r"^(commit|merge|reset)(\s*\(.*?\))?[：: ]+", "", m)
        m = re.sub(r"^(feat|fix|chore|refactor|docs|test|style)(\(.*?\))?[：: ]+", "", m)
        return plain_phrase(m)

    # —— 候选条目：(重要度, 文本)，交付/功能提交权重高，内部工程细节往后排 ——
    raw: list[tuple[int, str]] = []
    for c in pcommits:
        if not c["message"].lower().startswith(("clone", "checkout")):
            t = strip_commit(c["message"])
            if t:
                raw.append((2 + importance(t), t))
    for d in delivs[:8]:
        t = plain_phrase(d.get("description", ""))
        if t:
            raw.append((3 + importance(t), t))
    for t in dones:
        t = plain_phrase(t)
        if len(t) >= 6:
            raw.append((2 + importance(t), t))
    for o in outcomes:
        first = re.split(r"[。！？\n]", clean_text(o, 400))[0]
        if len(first) > 12:
            raw.append((1 + importance(first), plain_phrase(first)))
    raw = [(w, t) for w, t in raw if len(t) >= 6]
    raw.sort(key=lambda x: -x[0])

    # 只留「用户看得懂」的条目；如果全被滤掉（纯内部工程日），退回全量
    visible = [(w, t) for w, t in raw if importance(t) >= 0]
    if len(visible) < 2:
        visible = raw

    # —— 大字标题：最重要的 1-2 件事，简略说法 ——
    headline_parts: list[str] = []
    for _, txt in visible:
        p = short_phrase(txt)
        if len(p) >= 4 and p not in headline_parts:
            headline_parts.append(p)
        if len(headline_parts) >= 2:
            break
    headline = " ＋ ".join(headline_parts)

    # —— 小字细节：标题之外、同样是「看得懂」的成果 ——
    used = set(headline_parts)
    details: list[str] = []
    for _, txt in visible:
        t = clip_sentence(txt, 60)
        if not t or t in used or short_phrase(t) in used or t in details:
            continue
        details.append(t)
        if len(details) >= 5:
            break
    if not headline and details:
        headline = short_phrase(details.pop(0))
    if not headline:
        headline = f"有 {len(evs)} 个会话，但未留下任务/交付记录"

    tail = []
    if delivs:
        tail.append(f"{len(delivs)} 份交付")
    if fix_n:
        tail.append(f"{fix_n} 处修复")
    if pcommits:
        tail.append(f"{len(pcommits)} 条提交")
    stats = " · ".join(tail)
    return name, headline, details, stats


def render_report(data: dict, day: date, days: int = 1) -> str:
    win = data.get("window") or {}
    try:
        win_start = datetime.fromisoformat(win["start"])
        win_end = datetime.fromisoformat(win["end"])
    except Exception:
        win_start, win_end = day_window(day)
    sessions = data["sessions"]
    commits = data["git_commits"]
    by_proj: dict[str, list[dict]] = defaultdict(list)
    for s in sessions:
        by_proj[s.get("project") or "(未知项目)"].append(s)

    def in_window(iso: str) -> bool:
        try:
            t = datetime.fromisoformat(iso)
            return win_start <= t < win_end
        except Exception:
            return False

    L: list[str] = []
    span_label = f"{win_start.date()} ~ {day.isoformat()}"
    title = f"AI 工作日报 · {day.isoformat()}" if days == 1 else f"AI 工作{days}天汇总 · {span_label}"
    L.append(f"# {title}")
    L.append("")
    L.append(f"> 由 AI Chief of Staff MVP 自动生成 ｜ 生成时间 {data['generated_at']} ｜ 数据源：DeepSeek Harness / Claude Code / Codex / git reflog")
    L.append("")

    def proj_commits(proj: str) -> list[dict]:
        return [c for c in commits
                if Path(c["repo"]).as_posix().lower() in Path(proj).as_posix().lower()
                or Path(proj).as_posix().lower() in Path(c["repo"]).as_posix().lower()]

    # ---------- 完成了哪些重要功能（大字标题 + 小字细节） ----------
    span = "今天" if days == 1 else f"近 {days} 天"
    L.append(f"## 🎯 {span}，每个 AI 完成了哪些重要功能（先看这里）")
    L.append("")
    L.append("> 只列用户看得懂的功能与成果；内部工程细节（单测/脚手架/日志…）不进这里，全量记录见下方明细。")
    L.append("")
    for proj, evs in sorted(by_proj.items()):
        name, headline, details, stats = digest_line(proj, evs, in_window, commits)
        L.append(f"### {name}｜{headline}")
        L.append("")
        if stats:
            L.append(f"*{stats}*")
            L.append("")
        for d in details:
            L.append(f"- {d}")
    L.append("")

    # ---------- 一眼看全 ----------
    L.append("## 一眼看全")
    L.append("")
    L.append("| 项目 | 会话 | 用户指令 | 交付文件 | 提交 | 分类 |")
    L.append("|---|---|---|---|---|---|")
    total = Counter()
    for proj, evs in sorted(by_proj.items()):
        prompts = sum(len([p for p in e["prompts"] if in_window(p["time"])]) for e in evs)
        delivs = sum(len(e["deliverables"]) for e in evs)
        pcommits = [c for c in commits if Path(c["repo"]).as_posix().lower() in Path(proj).as_posix().lower()
                    or Path(proj).as_posix().lower() in Path(c["repo"]).as_posix().lower()]
        cats = sorted({c for e in evs for c in e["categories"]})
        total["sessions"] += len(evs)
        total["prompts"] += prompts
        total["deliverables"] += delivs
        total["commits"] += len(pcommits)
        L.append(f"| {proj} | {len(evs)} | {prompts} | {delivs} | {len(pcommits)} | {' / '.join(cats)} |")
    L.append("")

    # ---------- 每项目 ----------
    for proj, evs in sorted(by_proj.items()):
        L.append(f"## {proj}")
        L.append("")
        for e in evs:
            if e.get("start") and e.get("end"):
                s, t2 = e["start"], e["end"]
                span = f"{s[11:16]}–{t2[11:16]}" if s[:10] == t2[:10] else f"{s[5:16]}→{t2[5:16]}"
            else:
                span = "时间未知"
            tool = e["tool"]
            title = session_title(e)
            L.append(f"- **[{tool}] {title}**（{span}，{e['session_id'][:20]}）")
        L.append("")

        # 条目池（逐条分类，避免会话级误判整段倾倒）
        item_pool: list[tuple[str, str]] = _pool(evs, in_window)

        # 今日目标
        prompts = [t for t, k in item_pool if k == "prompt"]
        if prompts:
            L.append("**🎯 今日目标 / 用户指令**")
            for t in list(dict.fromkeys(prompts))[:10]:
                L.append(f"- {t[:180]}")
            L.append("")

        # ✅ 完成 / 产出（交付与任务在前，AI 收尾陈述最多补 3 条）
        hard = [(t, k) for t, k in item_pool if k in ("deliverable", "todo")]
        soft = [(t, k) for t, k in item_pool if k == "outcome"]
        items = hard[:10] + soft[:3]
        if items:
            L.append("**✅ 完成与产出**")
            for txt, kind in items[:12]:
                mark = {"deliverable": "📦", "todo": "✔️", "outcome": "💬"}[kind]
                L.append(f"- {mark} {txt[:220]}")
            L.append("")

        # 🧭 决策
        decisions = [d for e in evs for d in e["decisions"]]
        decisions += [t for t, k in item_pool if k in ("prompt", "outcome") and "decision" in classify(t)]
        if decisions:
            L.append("**🧭 AI 做出的重大决策 / 架构取舍**")
            for d in list(dict.fromkeys(decisions))[:10]:
                L.append(f"- {d[:240]}")
            L.append("")

        # 🐛 修复
        fix_items = [t for t, k in item_pool if k in ("prompt", "outcome", "todo") and "fix" in classify(t)]
        if fix_items:
            L.append("**🐛 修复 / 排障**")
            for t in list(dict.fromkeys(fix_items))[:8]:
                L.append(f"- {t[:200]}")
            L.append("")

        # 🔍 调研
        searches = [s for e in evs for s in e["searches"]]
        if searches:
            L.append("**🔍 调研痕迹**")
            for s in list(dict.fromkeys(searches))[:6]:
                L.append(f"- {s}")
            L.append("")

        # 📁 涉及文件
        files = [f for e in evs for f in e["files_touched"]]
        if files:
            L.append("**📁 涉及文件（写/改）**")
            for f in list(dict.fromkeys(files))[:15]:
                L.append(f"- `{f}`")
            L.append("")

        # 📎 证据
        L.append("**📎 证据**")
        seen_paths: dict[str, int] = {}
        for e in evs:
            p = e["evidence"].get("session_path", "")
            if p:
                seen_paths[p] = seen_paths.get(p, 0) + 1
        for p, n in list(seen_paths.items())[:8]:
            L.append(f"- 会话：`{p}`" + (f"（含 {n} 个会话）" if n > 1 else ""))
        pcommits = [c for c in commits if Path(c["repo"]).as_posix().lower() in Path(proj).as_posix().lower()
                    or Path(proj).as_posix().lower() in Path(c["repo"]).as_posix().lower()]
        for c in pcommits[:10]:
            L.append(f"- commit `{c['sha']}` {c['time'][11:16]} {c['message']}")
        L.append("")

    # ---------- 统计 ----------
    all_tools = Counter()
    for e in sessions:
        all_tools.update(e.get("tool_counts") or {})
    L.append("## 跨项目统计")
    L.append("")
    L.append(f"- 会话总数：{total['sessions']}（覆盖 {len(by_proj)} 个项目）")
    dur = 0.0
    for e in sessions:
        try:
            dur += max((datetime.fromisoformat(e["end"]) - datetime.fromisoformat(e["start"])).total_seconds(), 0)
        except Exception:
            pass
    if dur:
        L.append(f"- AI 会话总时长（含空闲）：{int(dur // 3600)} 小时 {int(dur % 3600 // 60)} 分")
    L.append(f"- 用户指令数：{total['prompts']} ｜ 交付文件：{total['deliverables']} ｜ git 活动：{len(commits)} 条（归属上述项目 {total['commits']} 条）")
    top = ", ".join(f"{k}×{v}" for k, v in all_tools.most_common(10))
    L.append(f"- 工具调用 Top10：{top or '（无）'}")
    sub = [s for e in sessions for s in e.get("subagents") or []]
    if sub:
        L.append(f"- 子代理派出：{len(sub)} 次（{'；'.join(list(dict.fromkeys(sub))[:5])}）")
    L.append("")

    # ---------- 附录 ----------
    L.append("## 附录：数据来源与口径")
    L.append("")
    L.append(f"- 口径：按会话记录**内部时间戳**筛选 {span_label}（本地时区）；跨窗会话按记录逐条计。")
    L.append("- 来源：`~/.dsh/sessions`（DeepSeek Harness，zstd JSONL）、`~/.claude/projects`（Claude Code JSONL）、"
             "`~/.codex/sessions`（Codex rollout）、各仓库 `.git/logs/HEAD`（reflog，未用 git.exe）。")
    L.append("- 分类与摘要是**关键词启发式**结果，可能有误判；每条均可通过「📎证据」回溯原始会话核对。")
    L.append("- 全部本地只读处理，无任何上传。")
    return "\n".join(L)


def render_decisions(data: dict, day: date, days: int = 1) -> str:
    """🧭 决策日志视图：把所有 AI 替用户做过的决策/取舍按时间串成时间线。"""
    win = data.get("window") or {}
    try:
        win_start = datetime.fromisoformat(win["start"])
        win_end = datetime.fromisoformat(win["end"])
    except Exception:
        win_start, win_end = day_window(day)
    span_label = f"{win_start.date()} ~ {win_end.date()}"
    rows: list[tuple[str, str, str, str, str]] = []
    for e in data.get("sessions") or []:
        proj = Path(e.get("project") or "(未知项目)").name or "(未知项目)"
        ev_path = (e.get("evidence") or {}).get("session_path", "")
        for d in dict.fromkeys(e.get("decisions") or []):
            rows.append((e.get("end") or "", proj, "🧭 决策", clean_text(d, 240), ev_path))
        for o in e.get("outcomes") or []:
            if "decision" in classify(o):
                rows.append((e.get("end") or "", proj, "⚖️ 取舍/方案", clip(o, 220), ev_path))
    for c in data.get("git_commits") or []:
        if "decision" in classify(c.get("message", "")):
            rows.append((c.get("time") or "", Path(c.get("repo", "")).name, "🔀 重构/调整",
                         clean_text(c.get("message", ""), 200), f"{c.get('repo','')}@{c.get('sha','')}"))
    rows.sort(key=lambda r: r[0], reverse=True)

    L = [f"# 🧭 AI 决策日志 · {span_label}", "",
         f"> 所有 AI 替你做过的技术/产品决策与取舍，按时间倒序。共 {len(rows)} 条，每条带证据可回溯。", ""]
    cur_day = ""
    cur_proj = ""
    for ts, proj, kind, text, ev in rows:
        d = ts[:10] or "（无时间）"
        if d != cur_day:
            cur_day = d
            cur_proj = ""
            L.append(f"## {d}")
            L.append("")
        if proj != cur_proj:
            cur_proj = proj
            L.append(f"### {proj}")
            L.append("")
        L.append(f"- {ts[11:16] or '--:--'} {kind}｜{text}")
        L.append(f"  - 📎 `{ev}`")
    if not rows:
        L.append("（时间窗内没有识别到决策记录）")
    return "\n".join(L)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def day_window(day: date):
    start = datetime.combine(day, time.min)
    return start, start + timedelta(days=1)


def main() -> int:
    ap = argparse.ArgumentParser("aicos")
    ap.add_argument("command", choices=["scan", "report", "all", "decisions"],
                    help="scan=只采集；report=日报(md+html+决策日志)；all=两者；decisions=只出决策时间线")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--days", type=int, default=1,
                    help="汇总天数（含 --date 当天）；1=日报，7=周报，任意 N=区间汇总")
    ap.add_argument("--out", default="out")
    ap.add_argument("--dsh-dir", default=str(Path.home() / ".dsh" / "sessions"))
    ap.add_argument("--claude-dir", default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--claude-history", default=str(Path.home() / ".claude" / "history.jsonl"))
    ap.add_argument("--codex-dir", default=str(Path.home() / ".codex" / "sessions"))
    ap.add_argument("--repo-root", action="append", default=None,
                    help="扫描 git 仓库的根目录（可重复）；默认取会话项目公共祖先")
    ap.add_argument("--summarizer", choices=["none", "agent"], default="none",
                    help="agent=导出 summary-input.json 供 LLM/Agent 精炼")
    args = ap.parse_args()

    day = date.fromisoformat(args.date)
    days = max(1, int(args.days))
    win_end = datetime.combine(day + timedelta(days=1), time.min)
    win_start = win_end - timedelta(days=days)
    prefix = "daily" if days == 1 else ("weekly" if days == 7 else f"range-{days}d")
    base = f"{prefix}-{day.isoformat()}"
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.command in ("scan", "all"):
        data = build_events(Path(args.dsh_dir), Path(args.claude_dir), Path(args.claude_history),
                            Path(args.codex_dir), [Path(r) for r in (args.repo_root or [])],
                            win_start, win_end)
        # 未显式指定 repo-root 时，用会话项目公共祖先扫描 git 仓库
        if not args.repo_root:
            cwds = [Path(s["project"]) for s in data["sessions"] if s.get("project")]
            roots: list[Path] = []
            try:
                roots = [Path(os_path_common([str(c) for c in cwds]))] if cwds else []
            except Exception:
                # 跨盘符等无法求公共祖先：退化为每个项目目录及其上两级
                for c in cwds:
                    roots.append(c)
                    roots.append(c.parent)
                    roots.append(c.parent.parent)
            if roots:
                data["git_commits"] = collect_git(roots, win_start, win_end)
        (out_dir / "events.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        _out(f"[scan] {len(data['sessions'])} 个会话 / {len(data['git_commits'])} 条提交 → {out_dir / 'events.json'}")

    if args.command in ("report", "all", "decisions"):
        ev_file = out_dir / "events.json"
        if not ev_file.exists():
            _out(f"[report] 缺少 {ev_file}，请先运行 scan")
            return 1
        data = json.loads(ev_file.read_text(encoding="utf-8"))
        win = data.get("window") or {}
        if win.get("start") and win.get("end"):
            if not (win["start"][:10] <= day.isoformat() < win["end"][:10]):
                _out(f"[report] 警告：events.json 的采集窗口是 {win['start'][:10]} ~ {win['end'][:10]}，"
                     f"不含 {day}；请先执行 scan --date {day} --days {days}")
        # 🧭 决策日志（独立时间线视图，report/all/decisions 都产出）
        dec_name = f"decisions-{day.isoformat()}" if days == 1 else f"decisions-{day.isoformat()}-{days}d"
        dec = out_dir / f"{dec_name}.md"
        dec.write_text(render_decisions(data, day, days), encoding="utf-8")
        _out(f"[decisions] 决策日志 → {dec}")
        if args.command == "decisions":
            return 0
        md = render_report(data, day, days)
        rpt = out_dir / f"{base}.md"
        rpt.write_text(md, encoding="utf-8")
        _out(f"[report] 日报 → {rpt}")
        try:
            from aicos_html import render_html
            hfile = out_dir / f"{base}.html"
            hfile.write_text(render_html(data, day, days), encoding="utf-8")
            _out(f"[report] HTML 日报（表格+换肤）→ {hfile}")
        except Exception as e:
            _out(f"[report] HTML 生成失败：{e}")
        if args.summarizer == "agent":
            si = out_dir / "summary-input.json"
            si.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            _out(f"[report] 事件层已导出 {si}，可交给 LLM/Agent 精炼后再贴回日报")
    return 0


def os_path_common(paths: list[str]) -> str:
    import os
    return os.path.commonpath(paths)


if __name__ == "__main__":
    sys.exit(main())
