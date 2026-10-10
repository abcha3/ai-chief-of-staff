# AI Chief of Staff

**Let AI summarize what ALL your AIs did today.**

When you vibe-code N projects in parallel, you can't remember what the AIs actually built, fixed, or decided. AI Chief of Staff scans the *local logs* of every AI tool on your machine (read-only, offline) and generates a daily report with an evidence trail.

> 中文文档见 [README.md](README.md)。Windows-first; macOS/Linux work too (missing sources are skipped gracefully).

## What you get

| Output | What it is |
|---|---|
| `out/daily-YYYY-MM-DD.html` | **Main view** — single-file webpage: "What the AIs did today" headlines + a filterable table (time / project / type / content / evidence), 3 themes (light / eye-care sepia / dark) |
| `out/daily-YYYY-MM-DD.md` | Markdown version (paste into issues / Notion) |
| `out/decisions-YYYY-MM-DD.md` | 🧭 **Decision log** — every decision/trade-off your AIs made, in reverse-chronological timeline, each with evidence |
| `out/weekly-YYYY-MM-DD.md` | Weekly (`--days 7`) or any-range rollup (`--days N`) |
| `out/events.json` | Structured events — feed it to your own LLM |

## Quick start

```bash
python aicos.py all                    # today's report (md + html + decision log)
python aicos.py all --days 7           # weekly
python aicos.py decisions --days 30    # decision timeline for the last 30 days
```

- Pure Python stdlib (3.11+; Python 3.14+ needed to read DeepSeek Harness compressed sessions, or `pip install zstandard`).
- Read-only collectors, no network, no upload. Missing tools are skipped silently.

> ⚠️ **Privacy**: `out/` contains your prompts, file paths and business data. Keep it local; redact before sharing screenshots. `.gitignore` already excludes `out/`.

## Supported tools

DeepSeek Harness · Claude Code · Codex · **WorkBuddy** (incl. automation-run reports) · **CodeBuddy** · Cursor · Windsurf · Gemini CLI · opencode · Aider · git (evidence cross-check, no git.exe needed).

Each tool has its own ~50-line adapter (`collect_*` in `aicos.py`) with graceful degradation — **adapter contributions welcome** (good first issue!).

## Design principles

1. **Local & private** — read-only, offline, your prompts never leave the machine.
2. **Evidence chain** — every summary line anchors to a session file / deliverable / commit sha. Don't trust AI summaries? Click the evidence.
3. **User perspective** — "what did the AI actually do" first; internal AI narration last.
4. **Fault-tolerant** — one broken adapter never breaks the scan.

## Install as a skill

Copy `SKILL.md`, `aicos.py`, `aicos_html.py` into your agent's skills directory (e.g. `~/.agents/skills/ai-chief-of-staff/`), then ask your agent: *"What did my AIs do today?"*

## Roadmap

- [x] MVP: multi-source scan → events → md/html report (table + themes + filters)
- [x] 🧭 Decision log view (`decisions` command)
- [x] Weekly / arbitrary range (`--days N`)
- [x] WorkBuddy / CodeBuddy / Cursor / Windsurf / Gemini CLI / opencode / Aider adapters
- [ ] V0.2: `--summarizer llm` headline & digest refinement
- [ ] V0.5: SQLite incremental index + semantic search ("why did we switch to X?")
- [ ] V1.0: scheduled runs + push (Feishu / email / Notion)

## License

MIT
