# -*- coding: utf-8 -*-
"""适配器回归测试（零依赖：python -m unittest discover -s tests）。

目的：各家 AI 工具的日志格式会漂移，样本坏了要第一时间知道。
fixtures/ 里的样本全部为**人工构造的脱敏数据**，不含任何真实对话。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import aicos  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
WIN_START = datetime(2026, 10, 6)
WIN_END = datetime(2026, 10, 9)


class TestDshAdapter(unittest.TestCase):
    def setUp(self):
        self.events = aicos.collect_dsh(FIX / "dsh" / "sessions", WIN_START, WIN_END)

    def test_one_session(self):
        self.assertEqual(len(self.events), 1)
        ev = self.events[0]
        self.assertEqual(ev["tool"], "dsh")
        self.assertEqual(ev["project"], "E:\\demo\\proj")
        self.assertEqual(ev["title"], "演示会话")

    def test_prompt_not_quoted_from_noise(self):
        self.assertEqual(self.events[0]["prompts"][0]["text"], "给按钮加个加载态")

    def test_deliverable_and_todos(self):
        ev = self.events[0]
        self.assertEqual(Path(ev["deliverables"][0]["path"]).name, "app.js")
        self.assertIn("加载态", ev["deliverables"][0]["description"])
        self.assertEqual([t["status"] for t in ev["todos"]], ["completed", "completed"])

    def test_tool_counts_and_files(self):
        ev = self.events[0]
        self.assertEqual(ev["tool_counts"].get("write"), 1)
        self.assertTrue(any(p.endswith("app.js") for p in ev["files_touched"]))

    def test_outcome_collected(self):
        self.assertTrue(any("加载态" in o for o in self.events[0]["outcomes"]))


class TestClaudeAdapter(unittest.TestCase):
    def setUp(self):
        self.events = aicos.collect_claude(
            FIX / "claude" / "projects", FIX / "claude" / "history.jsonl", WIN_START, WIN_END)

    def test_session(self):
        self.assertEqual(len(self.events), 1)
        ev = self.events[0]
        self.assertEqual(ev["tool"], "claude-code")
        self.assertEqual(ev["prompts"][0]["text"], "修复时长显示0分")
        self.assertEqual(ev["tool_counts"].get("Edit"), 1)
        self.assertTrue(any(p.endswith("app.js") for p in ev["files_touched"]))


class TestCodexAdapter(unittest.TestCase):
    def setUp(self):
        self.events = aicos.collect_codex(FIX / "codex" / "sessions", WIN_START, WIN_END)

    def test_session(self):
        self.assertEqual(len(self.events), 1)
        ev = self.events[0]
        self.assertEqual(ev["session_id"], "codex-demo-1")
        self.assertEqual(ev["prompts"][0]["text"], "调研一下替代方案")
        self.assertTrue(any("替代方案" in o for o in ev["outcomes"]))
        self.assertEqual(ev["tool_counts"].get("shell"), 1)


class TestCodeBuddyAdapter(unittest.TestCase):
    def setUp(self):
        self.events = aicos.collect_codebuddy(FIX / "codebuddy", WIN_START, WIN_END)

    def test_session(self):
        self.assertEqual(len(self.events), 1)
        ev = self.events[0]
        self.assertEqual(ev["title"], "响应式改版")
        self.assertEqual(ev["prompts"][0]["text"], "把这个页面改成响应式")
        self.assertTrue(any("响应式布局" in o for o in ev["outcomes"]))
        self.assertEqual(ev["todos"][0]["status"], "completed")


class TestWorkBuddyAdapter(unittest.TestCase):
    """workbuddy.db 由测试现场构造（schema 即契约：表名/列名变了测试要红）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aicos-wb-"))
        db = self.tmp / "workbuddy.db"
        con = sqlite3.connect(db)
        con.executescript(
            """
            CREATE TABLE sessions (id TEXT, cwd TEXT, title TEXT, custom_title TEXT,
                                   status TEXT, created_at INTEGER, updated_at INTEGER);
            CREATE TABLE automations (id TEXT, name TEXT, prompt TEXT, status TEXT,
                                      schedule_type TEXT, next_run_at INTEGER, last_run_at INTEGER,
                                      cwds TEXT, rrule TEXT, scheduled_at INTEGER);
            CREATE TABLE automation_runs (thread_id TEXT, automation_id TEXT, status TEXT,
                                          read_at INTEGER, thread_title TEXT, source_cwd TEXT,
                                          runs_json TEXT, result_success INTEGER,
                                          metadata_json TEXT, created_at INTEGER);
            INSERT INTO sessions VALUES ('wb-sess-1', 'E:\\demo\\proj', 'Demo 会话', NULL,
                                        'completed', 1791400000000, 1791400160000);
            INSERT INTO automations VALUES ('auto-1', '每日汇总', '汇总今天的数据', 'ACTIVE',
                                            'recurring', NULL, NULL, NULL, NULL, NULL);
            INSERT INTO automation_runs VALUES ('auto-1:1791400200000', 'auto-1', 'ACCEPTED', NULL,
                                                '自动化汇报：今天完成了数据汇总并输出了报告。',
                                                'E:\\demo\\proj',
                                                '[{"cwd":"E:\\\\demo\\\\proj","success":true,"startedAt":1791400200000,"finishedAt":1791400260000}]',
                                                1, NULL, 1791400200000);
            """
        )
        con.commit()
        con.close()
        task_dir = self.tmp / "tasks" / "wb-sess-1"
        task_dir.mkdir(parents=True)
        (task_dir / "1.json").write_text(json.dumps({
            "subject": "写汇总脚本", "status": "completed",
            "createdAt": 1791400000000, "updatedAt": 1791400160000}), encoding="utf-8")
        self.events = aicos.collect_workbuddy(self.tmp, WIN_START, WIN_END)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_session_and_automation(self):
        tools = {e["session_id"]: e for e in self.events}
        self.assertIn("wb-sess-1", tools)
        self.assertIn("auto-1:1791400200000", tools)
        self.assertEqual(tools["wb-sess-1"]["title"], "Demo 会话")
        self.assertEqual(tools["wb-sess-1"]["todos"][0]["content"], "写汇总脚本")

    def test_automation_report_is_outcome(self):
        auto = [e for e in self.events if e["session_id"].startswith("auto-1:")][0]
        self.assertTrue(any("自动化汇报" in o for o in auto["outcomes"]))
        self.assertTrue(auto["title"].startswith("自动化任务："))

    def test_window_filter(self):
        old = aicos.collect_workbuddy(self.tmp, datetime(2020, 1, 1), datetime(2020, 1, 2))
        self.assertEqual(old, [])


class TestGitAdapter(unittest.TestCase):
    def setUp(self):
        # .git 在 git 仓库里不能入库（嵌套仓库），样本存为 .gitfixture，测试时改名
        self.tmp = Path(tempfile.mkdtemp(prefix="aicos-git-"))
        shutil.copytree(FIX / "repo" / ".gitfixture", self.tmp / ".git")
        self.commits = aicos.collect_git([self.tmp], WIN_START, WIN_END)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reflog_parse(self):
        self.assertEqual(len(self.commits), 1)
        c = self.commits[0]
        self.assertTrue(c["message"].endswith("init: demo"))
        # 展示用短 sha（8 位）
        self.assertTrue("abcdef1234567890abcdef1234567890abcdef12".startswith(c["sha"]))
        self.assertEqual(c["sha"], "abcdef12")


class TestPipelineSmoke(unittest.TestCase):
    """端到端：采集 → 事件层 → md/html/决策日志。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="aicos-e2e-"))
        shutil.copytree(FIX / "repo" / ".gitfixture", cls.tmp / "repo" / ".git")
        wb = cls.tmp / "workbuddy"
        wb.mkdir()
        (wb / "tasks" / "wb-sess-9").mkdir(parents=True)
        con = sqlite3.connect(wb / "workbuddy.db")
        con.executescript(
            """
            CREATE TABLE sessions (id TEXT, cwd TEXT, title TEXT, custom_title TEXT,
                                   status TEXT, created_at INTEGER, updated_at INTEGER);
            CREATE TABLE automations (id TEXT, name TEXT, prompt TEXT, status TEXT,
                                      schedule_type TEXT, next_run_at INTEGER, last_run_at INTEGER,
                                      cwds TEXT, rrule TEXT, scheduled_at INTEGER);
            CREATE TABLE automation_runs (thread_id TEXT, automation_id TEXT, status TEXT,
                                          read_at INTEGER, thread_title TEXT, source_cwd TEXT,
                                          runs_json TEXT, result_success INTEGER,
                                          metadata_json TEXT, created_at INTEGER);
            """
        )
        con.commit()
        con.close()
        data = aicos.build_events(
            FIX / "dsh" / "sessions",
            FIX / "claude" / "projects", FIX / "claude" / "history.jsonl",
            FIX / "codex" / "sessions",
            [cls.tmp / "repo"],
            WIN_START, WIN_END,
        )
        # build_events 会扫真实 home 下的实验适配器；测试只验证事件层字段合法
        cls.data = data
        cls.md = aicos.render_report(data, datetime(2026, 10, 7).date(), days=1)
        cls.dec = aicos.render_decisions(data, datetime(2026, 10, 7).date(), days=1)
        from aicos_html import render_html
        cls.html = render_html(data, datetime(2026, 10, 7).date(), days=1)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_events_schema(self):
        for e in self.data["sessions"]:
            for key in ("tool", "session_id", "project", "start", "end", "prompts",
                        "outcomes", "todos", "evidence"):
                self.assertIn(key, e)

    def test_md_report(self):
        self.assertIn("完成了哪些重要功能", self.md)
        self.assertIn("proj", self.md.lower())
        self.assertIn("跨项目统计", self.md)

    def test_html_report(self):
        self.assertIn("data-theme", self.html)
        self.assertIn("class=\"chart\"", self.html)
        self.assertIn("完成了哪些重要功能", self.html)

    def test_decisions_report(self):
        self.assertIn("决策日志", self.dec)

    def test_digest_headline_short(self):
        name, headline, details, stats = aicos.digest_line(
            "E:\\demo\\proj", self.data["sessions"], lambda t: True, self.data["git_commits"])
        self.assertLessEqual(len(headline), 80)
        self.assertTrue(headline)


if __name__ == "__main__":
    unittest.main()
