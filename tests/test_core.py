# -*- coding: utf-8 -*-
"""核心单测：分词 / 存储 / 查重 / 覆盖 / 检索打分 / 强化 / 日志 / 简报。"""
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))


class CoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="eai_test_"))
        os.environ["EAI_HOME"] = str(self.tmp)
        from eai import util
        util.ensure_dirs()
        from eai.store import MemoryStore
        self.store = MemoryStore(self.tmp / "memory" / "memory.db")

    def tearDown(self):
        try:
            self.store.close()
        except Exception:
            pass
        os.environ.pop("EAI_HOME", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------- 分词 ----------

    def test_bigram(self):
        from eai.util import seg_text
        self.assertEqual(seg_text("记忆系统"), "记忆 忆系 系统")
        self.assertEqual(seg_text("信息"), "信息")
        self.assertEqual(seg_text("书"), "书")
        self.assertIn("turbotrain", seg_text("TurboTrain 训练"))
        self.assertIn("训练", seg_text("TurboTrain 训练"))
        self.assertEqual(seg_text(""), "")

    # ---------- 存储 ----------

    def test_add_merge_dedupe(self):
        r1 = {"kind": "fact", "text": "主人的训练机是 5090。", "title": "训练机", "importance": 0.6}
        a = self.store.add(dict(r1))
        self.assertEqual(a["action"], "inserted")
        b = self.store.add(dict(r1))
        self.assertEqual(b["action"], "merged")
        self.assertEqual(b["id"], a["id"])
        n = self.store.conn.execute("SELECT COUNT(*) c FROM memories").fetchone()["c"]
        self.assertEqual(n, 1)

    def test_supersede(self):
        a = self.store.add({"kind": "fact", "text": "训练机叫 win-l7okduteets。"})
        s = self.store.supersede(a["id"], {"kind": "fact", "text": "训练机改名了，现在叫 5090-box。"})
        old = self.store.get(a["id"])
        self.assertEqual(old["status"], "archived")
        self.assertEqual(old["superseded_by"], s["id"])
        new = self.store.get(s["id"])
        self.assertEqual(new["supersedes"], a["id"])

    def test_empty_text_rejected(self):
        with self.assertRaises(ValueError):
            self.store.add({"kind": "fact", "text": "   "})

    def test_new_id_unique_in_bulk(self):
        from eai.util import new_id
        ids = [new_id() for _ in range(3000)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_merge_no_content_loss(self):
        # 互不包含的两条文本合并 → 拼接，谁的信息都不丢（2026-10-15 回归修复）
        a = self.store.add({"kind": "fact", "text": "旧条：改图后要做视觉检查。"})
        self.store.merge(a["id"], {"kind": "fact", "text": "新条：改图要一张一张来。"})
        merged = self.store.get(a["id"])["text"]
        self.assertIn("视觉检查", merged)
        self.assertIn("一张一张", merged)

    # ---------- 检索 ----------

    def test_search_cn(self):
        self.store.add({"kind": "project", "scope": "示例项目",
                        "text": "示例项目论文投了某期刊，正在审稿修改。", "title": "论文投稿"})
        self.store.add({"kind": "fact", "text": "明天天气多云。", "title": "天气"})
        hits = self.store.search("论文 审稿", k=5)
        self.assertTrue(hits)
        self.assertIn("审稿", hits[0][0]["text"])
        self.assertEqual(self.store.search("完全不存在的内容xyzabc", k=3), [])
        self.assertIsInstance(self.store.search("and or not near", k=3), list)
        self.assertIsInstance(self.store.search("书", k=3), list)

    def test_search_or_fallback(self):
        self.store.add({"kind": "fact", "text": "系统自称管家。", "title": "管家"})
        self.store.add({"kind": "fact", "text": "模型是引擎。", "title": "引擎"})
        hits = self.store.search("管家 引擎", k=5)
        self.assertGreaterEqual(len(hits), 1)

    def test_recall_order_and_reinforce(self):
        now = datetime.now()
        old_ts = (now - timedelta(days=100)).strftime("%Y-%m-%d %H:%M:%S")
        self.store.add({"kind": "fact", "text": "训练进度记录。", "importance": 0.5, "ts": old_ts},
                       dedupe=False)
        self.store.add({"kind": "fact", "text": "训练进度记录。", "importance": 0.9}, dedupe=False)
        from eai import recall as recall_mod
        hits = recall_mod.recall(self.store, "训练进度", k=5, reinforce=False)
        self.assertEqual(len(hits), 2)
        self.assertGreater(hits[0]["importance"], hits[1]["importance"])
        mid = hits[0]["id"]
        before = self.store.get(mid)["use_count"]
        self.store.reinforce(mid)
        after = self.store.get(mid)
        self.assertEqual(after["use_count"], before + 1)
        self.assertGreater(after["importance"], hits[0]["importance"])
        self.assertLessEqual(after["importance"], 1.0)

    def test_recall_reinforces_by_default(self):
        self.store.add({"kind": "preference", "text": "主人要求汇报用大白话。", "importance": 0.9})
        from eai import recall as recall_mod
        hits = recall_mod.recall(self.store, "汇报 大白话", k=3)
        self.assertTrue(hits)
        self.assertEqual(self.store.get(hits[0]["id"])["use_count"], 1)

    # ---------- 日志 ----------

    def test_journal_append_only(self):
        from eai import journal
        journal.journal_append({"type": "note", "summary": "第一条"})
        journal.journal_append({"type": "note", "summary": "第二条"})
        t = journal.journal_tail(5)
        self.assertEqual(len(t), 2)
        self.assertEqual(t[-1]["summary"], "第二条")

    # ---------- 简报 ----------

    def test_brief_builds(self):
        ident = self.tmp / "memory" / "core" / "identity.md"
        ident.write_text("# 我是谁\n我是主人的管家。\n守则：诚实。", encoding="utf-8")
        self.store.add({"kind": "correction", "text": "汇报禁术语堆砌。", "importance": 0.9})
        self.store.add({"kind": "project", "scope": "示例项目", "text": "示例项目在做审稿修改。",
                        "importance": 0.6})
        from eai.session_brief import build_brief
        b = build_brief(project="示例项目", store=self.store)
        self.assertIn("管家简报", b)
        self.assertIn("汇报禁术语堆砌", b)
        self.assertTrue(len(b) < 4000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
