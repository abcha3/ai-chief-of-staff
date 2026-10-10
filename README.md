# AI Chief of Staff

> **让 AI 总结电脑上所有 AI 干了什么。** 跨项目、跨工具的「AI 工作履历」——今天 AI 做了哪些功能、修了哪些 bug、替你做了哪些决策，一张表看清，每条可回溯证据。

一个人同时 vibe coding N 个项目时，根本记不住 AI 都干了啥。本工具只读扫描你本机所有 AI 编程工具的会话日志 + git 记录，自动生成**每日日报**。

## 效果

| 产物 | 说明 |
|---|---|
| `out/daily-YYYY-MM-DD.html` | **主界面**：单文件网页——「AI 都做了哪些东西」总表（时间/项目/类型/内容/证据，可按类型与项目筛选），右上角一键换肤（☀️明亮 / 🍵护眼淡黄 / 🌙深色黑），手机也能看 |
| `out/daily-YYYY-MM-DD.md` | Markdown 版（适合贴 issue / 飞书 / Notion） |
| `out/decisions-YYYY-MM-DD.md` | 🧭 **决策日志**：所有 AI 替你做过的决策/取舍，按时间倒序串成时间线，每条带证据 |
| `out/weekly-YYYY-MM-DD.md` | 周报（`--days 7`）或任意区间汇总（`--days N`） |
| `out/daily-YYYY-MM-DD-llm.md` | 可选 LLM 精炼版（叙事 + 跨项目洞察） |
| `out/events.json` | 事件层原始数据，可自己接 LLM / 做统计 |

## 快速开始

```bash
python aicos.py all                       # 采集 + 生成今天的日报（md + html + 决策日志）
python aicos.py all --date 2026-10-09     # 指定日期
python aicos.py all --days 7              # 周报（含当天往前 7 天）
python aicos.py all --days 30             # 任意区间汇总
python aicos.py decisions --days 30       # 只要 30 天的 🧭 决策时间线
python aicos.py scan                      # 只采集，产 events.json
python aicos.py report --summarizer agent # 导出 summary-input.json 交给 LLM 精炼
```

> ⚠️ **隐私警告**：`out/` 里的日报/事件包含你的 prompt、文件路径和业务数据（持仓、代码、文档名……），**只在这台机器上看**；分享截图/报告前先打码。仓库的 `.gitignore` 已排除 `out/`，不会误提交。
>
> ⚠️ **数据安全**：所有采集器**只读**打开数据文件（含 SQLite 只读模式），不写入、不联网、不上传。不放心？先 `python aicos.py scan` 看 stderr 的采集日志。

依赖：Python 3.11+（解析 DeepSeek Harness 的压缩会话需 3.14+ 或 `pip install zstandard`）。**零第三方依赖、零网络请求、纯本地只读。**

## 支持的数据源

| 工具 | 读取位置 | 采集信号 |
|---|---|---|
| DeepSeek Harness | `~/.dsh/sessions` | 用户消息、AI 收尾陈述、**交付文件**、**任务清单**、**压缩摘要（含决策）**、审批原因、子代理、搜索记录 |
| Claude Code | `~/.claude/projects`、`~/.claude/history.jsonl` | 用户/助手消息、工具调用与文件改动 |
| Codex | `~/.codex/sessions` | 会话元数据、用户/助手消息 |
| Cursor / Windsurf（实验） | `%APPDATA%/*/User/workspaceStorage` | 项目归属、活动时间，尽力抽取 `state.vscdb` 里的对话 |
| Gemini CLI / opencode（实验） | `~/.gemini`、`~/.local/share/opencode` | 通用 JSON 对话收割 |
| **WorkBuddy 桌面端** | `~/.workbuddy/workbuddy.db`、`tasks/` | 会话标题/项目、**自动化任务每次运行的 AI 工作汇报**、任务清单 |
| **CodeBuddy CLI** | `~/.codebuddy/projects`、`tasks/` | 用户/助手消息、AI 标题、任务清单 |
| Aider（实验） | 各仓库 `.aider.chat.history.md` | 会话历史 |
| git（证据交叉验证） | 各仓库 `.git/logs/HEAD` | 提交时间/信息（**不需要 git.exe**，纯文件读取） |

实验性适配器采用**通用启发式**：能读出对话就抽对话，读不出至少留下"项目 + 时间 + 文件"的活动痕迹，格式不对时静默降级。
新增工具只需加一个 adapter（参考 `aicos.py` 里 `collect_*` 函数，每个约 50 行）——**欢迎贡献适配器**！

## 它长什么样（HTML 报告）

- **📝 今天干了什么**：先用一段话告诉你今天发生了什么（以你发给 AI 的消息为主线）；
- **AI 都做了哪些东西**：一张表，每行 = AI 做的一件事，按时间排序；类型徽章：`需求 交付 任务 修复 决策 调研 提交 AI陈述`；可按类型/项目筛选；
- **📎 证据列**：每行都锚定到会话文件 / 交付文件 / commit，点开可核对——AI 总结不可信？证据链兜底；
- **🎨 换肤**：明亮 / 护眼淡黄 / 深色黑，选择记在本地 localStorage。

## 设计原则

1. **本地隐私**：只读采集、不上传、不联网；你的 prompt 和代码不出这台电脑；
2. **证据链**：每条摘要可回溯（会话 ID / 文件路径 / commit sha）；
3. **用户视角**：先讲"你让 AI 做了什么、AI 交付了什么"，AI 内部叙述放最后；
4. **容错**：每工具一个适配器，日志格式漂移互不影响，单条解析失败只跳过该条。

## 路线图

- [x] MVP：多源采集 → 事件层 → md/html 日报（表格 + 换肤 + 筛选）
- [x] 🧭 决策日志视图（`decisions` 命令，任意时间跨度的决策时间线）
- [x] 周报 / 任意区间汇总（`--days N`）
- [x] 「支持所有 AI」：Cursor / Windsurf / Gemini CLI / opencode / Aider 实验性适配器
- [ ] V0.2：`--summarizer llm` 自动精炼（本地模型/API 皆可插拔）
- [ ] V0.5：SQLite 增量索引 + 语义搜索（"上次为什么改用 xx 方案"）
- [ ] V1.0：定时任务 + 推送（飞书 / 邮件 / Notion）；多机聚合

## 已知限制

- 分类（需求/交付/修复/决策…）为关键词启发式，长文本可能误判进某栏目——证据列可核对，V0.2 换 LLM 分类；
- 会话日志格式由各工具自行定义且会变化，适配器需要跟随更新（欢迎 issue/PR）。

## License

[MIT](LICENSE) ｜ 你的数据永远属于你：本工具不收集任何遥测。
