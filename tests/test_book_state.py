import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/book-companion/scripts/book_state.py"
spec = importlib.util.spec_from_file_location("book_state", SCRIPT)
book = importlib.util.module_from_spec(spec)
spec.loader.exec_module(book)


class BookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "book-a"
        self.state = book.initialize(self.root, "虚构测试书：修理一盏灯")

    def proposal(self, action, data, state=None):
        state = state if state is not None else self.state
        return book.propose(state, {"book_id": state["book_id"], "base_revision": state["revision"],
                                    "change": {"action": action, "data": data}})

    def apply(self, action, data):
        candidate = self.proposal(action, data)
        book.accept(self.state, candidate["id"], "测试作者明确采用当前指定候选")

    def outline(self):
        self.apply("outline", [{"id": "ch-01", "title": "坏掉的灯", "role": "出现具体难题"},
                               {"id": "ch-02", "title": "错误的办法", "role": "试错改变理解"},
                               {"id": "ch-03", "title": "把灯交还", "role": "选择产生后果"}])

    def chapter(self, cid="ch-01", body="虚构正文：他没有再拧开开关，而是先拔掉了插头。", stage="draft"):
        return {"chapter_id": cid, "content_type": "manuscript", "text": body,
                "stage": stage, "sources": [], "change_note": "合成测试，不取自私人作品"}

    def draft(self):
        self.outline()
        self.apply("chapter", self.chapter())

    def finalize(self):
        self.apply("finalize", {"chapter_id": "ch-01", "chapter_hash": book.current_hash(self.state, "ch-01")})

    def test_init_private_and_unique_books(self):
        other = book.initialize(Path(self.temp.name) / "book-b", "另一合成书")
        self.assertNotEqual(other["book_id"], self.state["book_id"])
        self.assertEqual(self.state["visibility"], "private")
        self.assertEqual(book.load(self.root), self.state)

    def test_existing_project_never_reinitialized(self):
        before = (self.root / book.STATE).read_bytes()
        with self.assertRaises(ValueError):
            book.initialize(self.root, "不能覆盖")
        self.assertEqual(before, (self.root / book.STATE).read_bytes())

    def test_pending_is_not_manuscript(self):
        self.outline()
        self.proposal("chapter", self.chapter())
        self.assertEqual(self.state["chapters"], {})

    def test_cross_book_request_rejected(self):
        with self.assertRaisesRegex(ValueError, "book_id"):
            book.propose(self.state, {"book_id": "another-book", "base_revision": 0,
                                      "change": {"action": "settings", "data": {"title": "串书"}}})

    def test_cross_book_candidate_not_found(self):
        c = self.proposal("settings", {"title": "甲"})
        other = book.initialize(Path(self.temp.name) / "book-b", "乙")
        with self.assertRaises(ValueError):
            book.accept(other, c["id"], "采用甲书候选")

    def test_stale_revision_rejected(self):
        self.apply("settings", {"author": "虚构测试作者"})
        with self.assertRaisesRegex(ValueError, "revision"):
            book.propose(self.state, {"book_id": self.state["book_id"], "base_revision": 0,
                                      "change": {"action": "settings", "data": {"title": "过期"}}})

    def test_stale_candidate_rejected(self):
        first = self.proposal("settings", {"title": "旧候选"})
        self.apply("settings", {"title": "新标题"})
        with self.assertRaisesRegex(ValueError, "stale"):
            book.accept(self.state, first["id"], "采用旧候选标题")
        self.assertEqual(self.state["title"], "新标题")

    def test_fingerprint_detects_out_of_band_edit(self):
        c = self.proposal("settings", {"title": "候选"})
        self.state["author"] = "外部编辑"
        with self.assertRaisesRegex(ValueError, "stale"):
            book.accept(self.state, c["id"], "采用当前标题候选")

    def test_ambiguous_confirmation_rejected(self):
        c = self.proposal("settings", {"title": "候选"})
        for reply in ["好的", "继续", "OK", "yes", ""]:
            with self.subTest(reply=reply), self.assertRaises(ValueError):
                book.accept(self.state, c["id"], reply)

    def test_accept_idempotent(self):
        c = self.proposal("settings", {"title": "采用的标题"})
        book.accept(self.state, c["id"], "采用这一个书名")
        before = copy.deepcopy(self.state)
        result = book.accept(self.state, c["id"], "再次采用同一个书名")
        self.assertTrue(result["already_accepted"])
        self.assertEqual(before, self.state)

    def test_discussion_not_chapter(self):
        self.outline()
        data = self.chapter()
        data["content_type"] = "analysis"
        with self.assertRaises(ValueError):
            self.proposal("chapter", data)

    def test_empty_or_unknown_chapter_rejected(self):
        self.outline()
        for data in [self.chapter(body=" "), self.chapter(cid="missing")]:
            with self.assertRaises(ValueError):
                self.proposal("chapter", data)

    def test_first_import_cannot_be_final_or_reviewed(self):
        self.outline()
        for stage in ["reviewed", "final"]:
            with self.assertRaises(ValueError):
                self.proposal("chapter", self.chapter(stage=stage))

    def test_three_chapters_import_and_reorder(self):
        self.outline()
        for index in range(1, 4):
            self.apply("chapter", self.chapter(cid=f"ch-0{index}", body=f"合成片段 {index}"))
        chapters_before = copy.deepcopy(self.state["chapters"])
        order = copy.deepcopy(self.state["outline"])
        order[0]["title"] = "改名不改正文"
        self.apply("outline", [order[2], order[0], order[1]])
        self.assertEqual(self.state["chapters"], chapters_before)
        exported = book.export_markdown(self.state)
        self.assertLess(exported.index("合成片段 3"), exported.index("合成片段 1"))
        self.assertIn("改名不改正文", exported)

    def test_invalid_outline_rejected(self):
        self.outline()
        for value in [self.state["outline"][:1], self.state["outline"] * 2,
                      [{"id": "../x", "title": "x", "role": "x"}]]:
            with self.assertRaises(ValueError):
                self.proposal("outline", value)

    def test_final_snapshot_survives_revision_and_rename(self):
        self.draft()
        self.finalize()
        final_before = copy.deepcopy(self.state["chapters"]["ch-01"]["finals"])
        self.apply("chapter", self.chapter(body="修订稿：新的具体行动。"))
        self.assertEqual(self.state["chapters"]["ch-01"]["stage"], "draft")
        order = copy.deepcopy(self.state["outline"])
        order[0]["title"] = "新版标题"
        self.apply("outline", order)
        self.assertEqual(final_before, self.state["chapters"]["ch-01"]["finals"])
        final_export = book.export_markdown(self.state, finals=True)
        self.assertIn("坏掉的灯", final_export)
        self.assertNotIn("新版标题", final_export)
        self.assertNotIn("修订稿", final_export)

    def test_finalize_hash_and_repeated_final_rejected(self):
        self.draft()
        with self.assertRaises(ValueError):
            self.proposal("finalize", {"chapter_id": "ch-01", "chapter_hash": "wrong"})
        self.finalize()
        with self.assertRaises(ValueError):
            self.proposal("finalize", {"chapter_id": "ch-01", "chapter_hash": book.current_hash(self.state, "ch-01")})

    def test_multiple_final_versions_retained(self):
        self.draft()
        self.finalize()
        self.apply("chapter", self.chapter(body="二版正文"))
        self.finalize()
        self.assertEqual(len(self.state["chapters"]["ch-01"]["finals"]), 2)

    def test_post_final_revision_must_be_draft(self):
        self.draft()
        self.finalize()
        with self.assertRaises(ValueError):
            self.proposal("chapter", self.chapter(stage="reviewed"))

    def test_reviewed_only_after_initial_draft(self):
        self.draft()
        self.apply("chapter", self.chapter(body="采用具体建议后的修订", stage="reviewed"))
        self.assertEqual(self.state["chapters"]["ch-01"]["stage"], "reviewed")

    def test_mode_switch_preserves_manuscript(self):
        self.draft()
        before = copy.deepcopy(self.state["chapters"])
        self.apply("settings", {"mode": "learn"})
        self.apply("settings", {"mode": "direct"})
        self.assertEqual(before, self.state["chapters"])

    def test_memory_persists_without_confirming_plan(self):
        for i in range(7):
            book.record_memory(self.state, {"book_id": self.state["book_id"], "base_revision": self.state["revision"],
                                           "note": {"hypotheses": [f"推断 {i}"], "next_step": "讨论章一"}})
        book.write(self.root, self.state)
        resumed = book.load(self.root)
        self.assertEqual(resumed["plan"], {})
        self.assertEqual(len(resumed["memory"]), 7)
        self.assertEqual(book.status(resumed)["older_memory_count"], 2)

    def test_plan_signature_changes(self):
        initial = book.outline_signature(self.state)
        self.apply("plan", {"audience": {"value": "新手", "status": "confirmed", "evidence": "作者说：写给新手"}})
        self.assertNotEqual(initial, book.outline_signature(self.state))

    def test_lock_and_symlink_protection(self):
        with book.locked(self.root):
            with self.assertRaises(ValueError):
                with book.locked(self.root):
                    pass
        outside = Path(self.temp.name) / "elsewhere"
        outside.mkdir()
        (outside / book.STATE).symlink_to(self.root / book.STATE)
        with self.assertRaises(ValueError):
            book.load(outside)

    def test_cli_roundtrip_export_and_overwrite_failure(self):
        self.draft()
        book.write(self.root, self.state)
        result = subprocess.run([sys.executable, str(SCRIPT), "status", "--book", str(self.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["book_id"], self.state["book_id"])
        target = Path(self.temp.name) / "reading.md"
        command = [sys.executable, str(SCRIPT), "export", "--book", str(self.root), "--output", str(target)]
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        before = target.read_bytes()
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)
        self.assertEqual(before, target.read_bytes())

    def test_cli_failed_accept_does_not_write(self):
        c = self.proposal("settings", {"title": "不能采用"})
        book.write(self.root, self.state)
        before = (self.root / book.STATE).read_bytes()
        result = subprocess.run([sys.executable, str(SCRIPT), "accept", "--book", str(self.root),
                                 "--candidate", c["id"], "--confirmation", "好的"], capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(before, (self.root / book.STATE).read_bytes())


if __name__ == "__main__":
    unittest.main()
