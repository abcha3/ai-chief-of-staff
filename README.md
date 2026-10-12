<p align="right">
  <b>简体中文</b> | <a href="README.en.md">English</a>
</p>

<div align="center">

# 🗂️ AI 工作日报 · AI Chief of Staff

### 自动总结你电脑上**所有 AI** 都干了什么 —— 日报 / 周报 / 任意区间，条条带证据

**AI daily report / weekly report generator** —— 扫描 Claude Code、Codex、WorkBuddy 等 AI 工具的会话日志和 git 记录，
生成一份人能看懂的「AI 工作汇报」：谁、做成了什么功能、修了什么 bug、替你做了什么决定。

[![Python](https://img.shields.io/badge/Python-3.14%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Release](https://img.shields.io/github/v/release/abcha3/ai-daily-report)](https://github.com/abcha3/ai-daily-report/releases)
[![Tests](https://img.shields.io/badge/tests-21%20passed-brightgreen)](tests/)

**数据源：** DeepSeek Harness · Claude Code · Codex · WorkBuddy · CodeBuddy · Cursor · Windsurf · Gemini CLI · Aider · git reflog

</div>

---

## 😩 你是不是也这样

- 同时开着 5、6 个 AI 干不同的项目，**三天后就想不起来它们到底做成了什么**
- 想复盘「AI 替我做过哪些决定」，只能翻几十万字的会话记录
- 项目太多，某个 AI 修的 bug、上的功能，完全没有一份**能看的工作总结**

这个工具就是干这个的：**一条命令，把所有 AI 的工作日志变成一份带证据的日报/周报。**

## 📸 报告长什么样

单文件 HTML，浏览器直接打开，三套皮肤（护眼淡黄 / 明亮 / 深色），可筛选可打印：

```markdown
## 🎯 近 30 天，每个 AI 完成了哪些重要功能（先看这里）

### Upward｜『晚记』上线：记账 + 日历 + 周复盘，修好时长 bug
*2 处修复 · 16 条提交 · 📁 E:\AIProject\Upward*
- 修好『填了内容却显示 0 分』的时长 bug
- 记一笔支持富文本（加粗/字号/颜色/表情）
- 三套配色可切换（明亮/护眼淡黄/深色黑）

### Walk｜『行迹』轨迹分享图工具：拖入 GPX 就能出图
*86 份交付 · 28 处修复 · 6 条提交 · 📁 E:\AIProject\Walk*
- 主界面支持拖放 GPX、切换版式、导出分享图
- 长卷/方帖两种版式都能出成品
```

每个 AI 一个**大字标题**（它最主要干成了什么）+ 小字细节 + 📁 路径锚点；下面还有：

| 区块 | 内容 |
|---|---|
| 📊 统计与图表 | 类型分布环形图、项目对比条形图、每日/每小时产出柱状图 |
| 📋 明细表 | 每行 = AI 做的一件事，可按类型/项目筛选、按时间排序 |
| 📎 证据列 | 每行锚定会话文件 / 交付文件 / commit，点开可核对——AI 总结不可信？证据链兜底 |
| 🧭 决策日志 | 单独产出：AI 替你做的技术选型/产品取舍，时间线 + 证据 |

## ⚡ 30 秒上手

```bash
git clone https://github.com/abcha3/ai-daily-report.git
cd ai-daily-report

python aicos.py all                       # 今天的日报（md + html + 决策日志）
python aicos.py all --days 7              # 周报
python aicos.py all --days 30             # 任意区间汇总
python aicos.py report --date 2026-10-11  # 回看某一天
```

产物在 `out/` 目录，`daily-*.html` 双击就能看。需要 Python 3.14+（或 `pip install zstandard`）；纯标准库、只读、不联网。缺哪个数据源自动跳过。

> 也可以装成 Agent 技能（推荐）：把 `SKILL.md`、`aicos.py`、`aicos_html.py` 放进 `~/.agents/skills/ai-chief-of-staff/`，
> 然后直接问你的 AI：**「总结一下我今天 AI 都干了啥」**。

## 🧠 工作原理（三层管线）

```
事实层（只读采集）           事件层                摘要层
┌─────────────────┐    ┌──────────────┐    ┌──────────────────┐
│ DeepSeek Harness │    │              │    │ 大字标题 + 小字    │
│ Claude Code      │──▶ │ events.json  │──▶ │ 图表 / 明细表      │
│ Codex / WorkBuddy│    │ （结构化事件） │ │ 决策日志           │
│ CodeBuddy / git  │    │              │    │ md + HTML 报告     │
└─────────────────┘    └──────────────┘    └──────────────────┘
```

- **程序负责保真**：只筛选和清洗 AI 自己的工作记录（任务清单/交付描述/提交信息），不编造、不改写事实
- **Agent 负责说人话**（技能模式）：AI 读 `events.json` 后把摘要改写成大白话，写进 `out/summary.json`，
  再用 `--summary` 注入报告——「修复 AuthManager 缺少 login_user」变成「修好登录态丢失的问题」

```bash
python aicos.py report --summary out/summary.json   # 把 AI 写的人话摘要注入报告
```

## 🔒 隐私与安全

- 采集器**只读**你的日志目录（SQLite 也用只读模式打开），不修改任何项目文件，不联网
- ⚠️ `out/` 产物包含你的会话内容摘要和文件路径，**别直接公开上传**；分享前先过一遍
- 发现日志里有硬编码密钥等安全问题，技能模式下 AI 会主动提醒你

## 🧪 测试

各家 AI 工具的日志格式会变，`tests/fixtures/` 存有人工构造的脱敏样本，哪个适配器坏了测试就红：

```bash
python -m unittest discover -s tests   # 21 个用例
```

## 🗺 Roadmap

- [ ] `--summarizer llm`：不通过 Agent、直接调用 LLM API 精炼摘要
- [ ] 更多适配器：更多 AI 编程工具的会话格式
- [ ] 周报邮件/飞书推送

## 📄 License

[MIT](LICENSE) ｜ 用了觉得好用，给个 ⭐ Star 让更多人看到
