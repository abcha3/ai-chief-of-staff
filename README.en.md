<p align="right">
  <a href="README.md">简体中文</a> | <b>English</b>
</p>

<div align="center">

# 🗂️ AI Chief of Staff — AI Work Report Generator

### Automatically summarize what **all your AI agents** did — daily / weekly / any range, every claim backed by evidence

Scan the session logs and git history of every AI coding tool on your machine, and turn them
into a human-readable work report: which features shipped, which bugs got fixed, which decisions
your AIs made for you.

[![Python](https://img.shields.io/badge/Python-3.14%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Release](https://img.shields.io/github/v/release/abcha3/ai-daily-report)](https://github.com/abcha3/ai-daily-report/releases)
[![Tests](https://img.shields.io/badge/tests-21%20passed-brightgreen)](tests/)

**Sources:** DeepSeek Harness · Claude Code · Codex · WorkBuddy · CodeBuddy · Cursor · Windsurf · Gemini CLI · Aider · git reflog

</div>

---

## 😩 Sounds familiar?

- You run 5–6 AI agents across different projects and **three days later you can't remember what they actually finished**
- You want to review "what decisions did my AIs make for me" but that means digging through hundreds of thousands of tokens of chat logs
- There is no readable work summary — just noise

This tool fixes that: **one command turns all your AI work logs into an evidence-backed report.**

## 📸 What the report looks like

A single-file HTML page — open it in a browser, three themes (eye-care sepia / light / dark), filterable, printable:

```markdown
## 🎯 What important features each AI completed (look here first)

### Upward | Journal app launched: entries + calendar + weekly review, fixed the duration bug
*2 fixes · 16 commits · 📁 E:\AIProject\Upward*
- Fixed the bug where entries showed "0 minutes"
- Rich-text entries (bold / size / color / emoji)
- Three color themes (light / eye-care / dark)

### Walk | "Walk" — GPX trail poster tool: drop a GPX, get a shareable image
*86 deliverables · 28 fixes · 6 commits · 📁 E:\AIProject\Walk*
- Drag & drop GPX, switch layouts, export share images
- Both long-scroll and square layouts produce final-quality output
```

Every AI gets a **big headline** (its main achievement) + small details + a 📁 path anchor. Below that:

| Section | What's inside |
|---|---|
| 📊 Stats & charts | Donut (event types), horizontal bars (per project), daily/hourly output bars |
| 📋 Detail table | One row = one thing an AI did; filter by type/project, sort by time |
| 📎 Evidence column | Every row anchors to a session file / deliverable / commit — don't trust AI summaries? Verify them |
| 🧭 Decision log | Separate timeline of every technical/product decision your AIs made, with evidence |

## ⚡ Quick start (30 seconds)

```bash
git clone https://github.com/abcha3/ai-daily-report.git
cd ai-daily-report

python aicos.py all                       # today's report (md + html + decision log)
python aicos.py all --days 7              # weekly
python aicos.py all --days 30             # any range
python aicos.py report --date 2026-10-11  # look back at a specific day
```

Outputs land in `out/`; open `daily-*.html` in your browser. Requires Python 3.14+ (or `pip install zstandard`).
Pure stdlib, read-only, no network. Missing data sources are skipped automatically.

> Or install it as an agent skill (recommended): copy `SKILL.md`, `aicos.py`, `aicos_html.py` into
> `~/.agents/skills/ai-chief-of-staff/`, then just ask your agent: **"What did my AIs do today?"**

## 🧠 How it works (three-layer pipeline)

```
Facts (read-only collectors)      Events              Digest
┌─────────────────┐    ┌──────────────┐    ┌──────────────────┐
│ DeepSeek Harness │    │              │    │ Big headlines     │
│ Claude Code      │──▶ │ events.json  │──▶ │ charts / table    │
│ Codex / WorkBuddy│    │  (structured)│    │ decision log      │
│ CodeBuddy / git  │    │              │    │ md + HTML report  │
└─────────────────┘    └──────────────┘    └──────────────────┘
```

- **The program keeps facts honest**: it only filters and cleans the AIs' own work records
  (todo lists / deliverable descriptions / commit messages) — never invents, never rewrites facts
- **The agent speaks human** (skill mode): the agent reads `events.json`, rewrites the digest into
  plain language, writes `out/summary.json`, then injects it with `--summary` —
  "fix: AuthManager missing login_user" becomes "fixed the login-state loss bug"

```bash
python aicos.py report --summary out/summary.json   # inject agent-written summaries
```

## 🔒 Privacy & security

- Collectors are **read-only** over your log directories (SQLite opened in read-only mode); no project files are modified; no network access
- ⚠️ `out/` contains summaries of your session content and file paths — **don't publish it as-is**
- In skill mode the agent will warn you if it spots hardcoded secrets in the logs

## 🧪 Tests

AI tool log formats change; `tests/fixtures/` holds hand-crafted sanitized samples so a broken
adapter turns the suite red:

```bash
python -m unittest discover -s tests   # 21 cases
```

## 🗺 Roadmap

- [ ] `--summarizer llm`: refine summaries by calling an LLM API directly (no agent needed)
- [ ] More adapters for more AI coding tools
- [ ] Weekly report delivery: email / Slack / Feishu push

## 📄 License

[MIT](LICENSE) ｜ If this saved you time, a ⭐ Star helps others find it
