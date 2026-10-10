# AI Chief of Staff — MVP 技术方案

> 「让 AI 总结电脑上所有 AI 干了什么」— 跨项目、跨工具的 **AI 工作履历 / 每日日报**
>
> 版本：v0.1（MVP） 日期：2026-10-09

---

## 1. 目标与定位

**一句话**：自动采集本机所有 AI 编程工具的会话记录 + git 事实，产出以人为中心的日报：
「今天 AI 在哪些项目上**做了什么功能、修了什么 bug、替我做了哪些决策**，证据在哪」。

**MVP 只做三件事**（不做 dashboard、不做实时、不做多端）：

1. **采集**：扫描本机 AI 工具的本地会话存储（只读）；
2. **事件化**：把原始会话压缩成结构化事件（项目 / 类型 / 摘要 / 证据）；
3. **日报**：生成一份 Markdown 日报（可选喂给 LLM/Agent 做精炼摘要）。

**非目标（V2 再说）**：Web UI、多机同步、token 成本统计、实时提醒、写回 git。

---

## 2. 竞品差异（为什么值得做）

| 已有产品 | 以什么为中心 | 缺什么 |
|---|---|---|
| Vibe Kanban / Circus Chief / Omnara | 会话的**运行时**管理 | 不回答"今天完成了什么" |
| sniffly / claude-usage / TokenTracker / aireceipts | token / 成本 / 错误率 | 不产出"功能/修复/决策"的语义履历 |
| Unfudged（文件快照） | 文件变化**事实** | 没有语义总结 |
| beads / agent-company | 任务清单 / 组织汇报 | 不覆盖"会话里实际发生的事" |

**本项目的位置**：产出与决策（Outcome & Decision）层。三大差异化：

1. **决策日志**——"当时为什么选方案 B"只有它能回答；
2. **证据链**——每条摘要可回溯到会话 ID / 交付文件 / commit，防 AI 总结幻觉；
3. **跨工具跨项目**——一台机器上 N 个项目、M 种工具统一编年史。

---

## 3. 数据源（本机实测，2026-10-09）

| 工具 | 本地存储 | 格式 | 关键信号（已实测验证） |
|---|---|---|---|
| DeepSeek Harness | `~/.dsh/sessions/<项目>/<会话>/session.v3.jsonl.zstd` | zstd 压缩 JSONL | `session`（cwd/时间）、`session/title`、`user/message`、`assistant/message`、`tool/call`、**`deliverables/presented`**（交付文件+描述）、**`todo/write`**（任务清单）、**`compaction/summary`**（含"Primary Request and Intent / Choices made"）、`approval/asked`（原因）、`subagent/catalog`（子代理）、`web/deepseek-search-llm-request`（调研查询） |
| Claude Code | `~/.claude/projects/<编码路径>/<sessionId>.jsonl` | 明文 JSONL | `user`/`assistant` 消息、`tool_use` 块（文件路径）、`cwd`、`gitBranch`、`timestamp` |
| Claude Code | `~/.claude/history.jsonl` | 明文 JSONL | 用户 prompt 历史（display/project/sessionId） |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | 明文 JSONL | `session_meta`(cwd)、`response_item`(user/assistant 消息) |
| git（证据交叉验证） | 各仓库 `.git/logs/HEAD`（reflog） | 明文 | 提交时间/作者/信息；**无需 git.exe**（沙箱/无 git 环境也能跑） |

> 采集全部**只读**；日志格式易漂移（aireceipts 作者的教训），因此每种工具一个**适配器**，见 §5。

---

## 4. 三层管线架构

```
┌─ 事实层 (collectors) ─────────────────────────────────────┐
│ dsh.py │ claude_code.py │ codex.py │ gitfs.py             │  只读、容错、可单测
└──────────────┬───────────────────────────────────────────┘
               ▼  SessionRecord（原始但已归一）
┌─ 事件层 (events) ────────────────────────────────────────┐
│ 会话 → SessionEvent：{项目, 工具, 时间, 目标, 交付, 决策,  │
│   修复, 文件, 工具调用统计, 证据(session 路径)}            │
│  + 分类器：feature | fix | decision | research | refactor │
│  + git reflog 事件（独立来源，用于交叉验证）               │
└──────────────┬───────────────────────────────────────────┘
               ▼  events.json（可复用、可喂 LLM）
┌─ 摘要层 (report) ────────────────────────────────────────┐
│ 模式 A 启发式（默认，零依赖）：模板 + 关键词分类 + 统计    │
│ 模式 B agent：把 events.json 喂给 LLM/Agent 精炼（--summarizer agent）
│ 输出：out/daily-YYYY-MM-DD.md（日报）                     │
└──────────────────────────────────────────────────────────┘
```

**事件 schema（`events.json` 中每个 session）**：

```json
{
  "tool": "dsh | claude-code | codex",
  "session_id": "…",
  "project": "E:\\AIProject\\Guitar",
  "title": "会话标题",
  "start": "2026-10-09T06:36:06+08:00",
  "end": "2026-10-09T14:16:12+08:00",
  "prompts": ["用户目标/指令（截断）…"],
  "outcomes": ["AI 的收尾陈述…"],
  "deliverables": [{"path": "…", "description": "…"}],
  "todos": [{"content": "…", "status": "completed"}],
  "decisions": ["compaction 摘要中的决策句 …"],
  "files_touched": ["src/xx.ts", "…"],
  "tool_counts": {"write": 12, "pwsh": 30},
  "approvals": ["escalate sandbox … 原因"],
  "categories": ["feature", "decision"],
  "evidence": {"session_path": "…", "source": "dsh"}
}
```

**分类器规则（MVP 用关键词，V1 换 LLM）**：
`fix`（修复/bug/报错/error/crash/异常…）、`decision`（为什么/方案/选型/架构/决定/取舍/改为/放弃…）、
`research`（调研/搜索/对比/评测/review…）、`refactor`（重构/清理/整理…）、其余 → `feature`。

---

## 5. 模块与代码结构（MVP：单文件 CLI，纯标准库）

```
AI Chief of Staff/
├── TECH_PLAN.md          # 本文档
├── README.md             # 使用说明
├── aicos.py              # MVP 全部逻辑（stdlib-only，Python 3.11+，zstd 需 3.14 或 zstandard）
│   ├── adapters: DSH / ClaudeCode / Codex / GitReflog（各自 parse()，坏文件跳过并告警）
│   ├── classify()        # 关键词分类
│   ├── build_events()    # 事实层 → 事件层
│   ├── render_report()   # 事件层 → 日报 Markdown
│   └── CLI: scan | report | all
└── out/
    ├── events.json       # 事件层产物（可喂 LLM）
    └── daily-*.md        # 日报
```

**设计要点**：
- **纯标准库**：`json/glob/datetime/zlib`；zstd 解压优先 `compression.zstd`（Py3.14+），回退 `zstandard` 包，都没有则跳过 DSH 并告警；
- **git 不依赖 git.exe**：直接解析 `.git/logs/HEAD` reflog（本机沙箱实测 git.exe 被拒，纯文件读取可绕过，还免安装）；
- **容错**：任何一条记录解析失败只跳过该条；适配器独立，格式漂移互不影响（这是本赛道最大维护风险，见 §8）；
- **时间口径**：按**记录内时间戳**过滤"今天"（00:00–24:00 本地时区），不看文件 mtime（跨夜会话不漏不重）。

## 6. 日报形态（模板）

```markdown
# AI 工作日报 · 2026-10-09
## 一眼看全        ← 项目×(会话/产出/提交/分类) 表格
## 项目 A          ← 今日目标 / ✅完成 / 🐛修复 / 🧭决策 / 📁涉及文件 / 📎证据
## 项目 B …
## 跨项目统计      ← 会话数、消息数、工具调用、交付文件、commit
## 附录：数据来源与口径（可信度说明）
```

每条摘要**必须**带证据锚点（会话 ID/文件路径/commit sha），这条规则同样写进 LLM 精炼的 prompt。

## 7. 隐私与安全

- 全部**本地只读**，不上传任何 prompt/代码；产出仅落在 `out/`；
- 日报默认**不含原文长引用**，只留截断摘要 + 证据路径（要原文自己点开）；
- 后续如加云同步/LLM 云端精炼：默认关闭、显式 opt-in、可配置脱敏（密钥/路径/人名）——借鉴 TokenTracker "绝不读 prompt" 的信任叙事。

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| 各家日志格式频繁变更 | 每工具一个适配器 + "样本文件回归测试"；解析失败降级为统计行而非崩溃 |
| AI 摘要幻觉（说做了实际没做） | 证据链强制：摘要必须引用 deliverables / 文件 / commit；git reflog 交叉验证 |
| 隐私敏感 | 默认本地；输出截断；不回传 |
| 留存/新鲜感消退 | 长期价值锚在"可搜索决策库"，日报只是入口（V2：`aicos search "为什么用SQLite"`） |
| 官方工具内置周报 | 壁垒=跨工具+跨项目+决策层；单一工具的周报谁都能做 |

## 9. 里程碑

- **MVP（本次）**：单机 CLI，DSH + Claude Code + Codex + git reflog，启发式日报，`events.json` 可喂 LLM ✅
- **V0.2**：LLM 精炼模式（本地模型/API 皆可插拔）；`--since/--until` 任意区间；周报；
- **V0.5**：增量索引（SQLite）+ 全文搜索（"上次为什么改用 xx 方案"）；Windows/macOS 双平台打包；
- **V1.0**：推送渠道（飞书/邮件/Notion）；决策日志独立视图；多机聚合。

## 10. MVP 使用

```bash
python aicos.py all --date 2026-10-09          # 采集+日报
python aicos.py scan --out out                 # 只产 events.json
python aicos.py report --date 2026-10-09       # 只产日报
# 可选参数：--claude-dir / --codex-dir / --dsh-dir / --repo-root（可重复）
```
