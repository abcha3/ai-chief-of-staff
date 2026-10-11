## 🎉 First public release — 让 AI 总结电脑上所有 AI 干了什么

**English** | 中文

When you vibe-code N projects in parallel, you can't remember what the AIs actually built, fixed, or decided. AI Chief of Staff scans the *local logs* of every AI tool on your machine (read-only, offline, zero dependencies) and generates a daily report with an evidence trail.

### ✨ Highlights

- **📝 What the AIs did today** — big headline per project (what was mainly accomplished), with small-print details below
- **📊 Stats & charts** — donut (type distribution), bar charts (project comparison, hourly/daily output), pure inline SVG, three themes (light / eye-care sepia / dark)
- **🧭 Decision log** — every decision/trade-off your AIs made, reverse-chronological, each with evidence (`decisions` command, any date range)
- **🔍 Filterable table** — time / project / type / content / evidence; sortable columns; evidence links open the original session file or deliverable
- **📅 Weekly & arbitrary ranges** — `--days 7`, `--days 30`, any window
- **🧩 11 tool adapters** — DeepSeek Harness · Claude Code · Codex · WorkBuddy (incl. automation-run reports) · CodeBuddy · Cursor · Windsurf · Gemini CLI · opencode · Aider · git (no git.exe needed)

### 🚀 Quick start

```bash
python aicos.py all           # today's report (md + html + decision log)
python aicos.py all --days 7  # weekly
pip install .                 # optional: install the `aicos` CLI
```

Pure Python stdlib. Read-only collectors, no network, no upload — your prompts never leave your machine. See [README.md](../../blob/master/README.md) (中文) / [README.en.md](../../blob/master/README.en.md).

### 🛡️ Quality

- 17-case adapter regression suite (`python -m unittest discover -s tests`) with sanitized fixtures — log format drift turns the suite red
- One broken adapter never breaks the scan (graceful degradation)

### 🔮 Roadmap

- V0.2: LLM-refined headlines & digests
- V0.5: SQLite incremental index + semantic search
- V1.0: scheduled runs + push notifications

---

**中文**：同时 vibe coding 好几个项目，记不住 AI 干了啥？这个工具扫描本机所有 AI 工具的本地日志（只读、离线、零依赖），生成带证据链的工作日报：每个 AI 一个大字标题、图表统计、决策时间线、可筛选明细表。装成技能给你的 Agent 用也行。MIT 协议，欢迎提 issue / PR（适配器是 good first issue）。
