import copy
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from filelock import FileLock

from symbiopulse.core.auto import _scan_workspace, ensure_workspace_ready, schedule_workspace_refresh
from symbiopulse.core.config import SymbioConfig
from symbiopulse.core.genome import MAX_RELATIONS_PER_FILE, SymbioWorkspace
from symbiopulse.engines.olfactory import OlfactoryEngine
from symbiopulse.engines.resonator import ResonatorEngine
from symbiopulse.indexing.path_filter import PathFilter, ScanBudgetExceeded


class TestBoundedQueryPath(unittest.TestCase):
    def test_snapshot_open_does_not_scan_when_index_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = SymbioWorkspace(temp_dir)
            workspace.init_workspace()

            with patch.object(OlfactoryEngine, "scan") as scan:
                opened, status = ensure_workspace_ready(temp_dir, scan_if_missing=False)

            scan.assert_not_called()
            self.assertEqual(opened.scent_map, {})
            self.assertEqual(status["index_state"], "warming_up")

    def test_memory_read_does_not_decay_relations_or_write_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = SymbioWorkspace(temp_dir)
            workspace.init_workspace()
            workspace.strengthen_synapse("fix query latency", "src/query.py")
            workspace.strengthen_relation("src/query.py", "src/store.py")
            relations_before = copy.deepcopy(workspace.relations)

            with patch.object(workspace, "save_state") as save_state:
                memory = workspace.get_o1_memory("fix query latency")

            self.assertIsNotNone(memory)
            self.assertEqual(workspace.relations, relations_before)
            save_state.assert_not_called()

    def test_reader_does_not_wait_for_writer_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = SymbioWorkspace(temp_dir)
            workspace.init_workspace()
            writer_lock = FileLock(workspace.lock_file)
            writer_lock.acquire()
            try:
                started = time.perf_counter()
                SymbioWorkspace(temp_dir).load_state()
                elapsed = time.perf_counter() - started
            finally:
                writer_lock.release()

            self.assertLess(elapsed, 0.1)


class TestBoundedMutationPath(unittest.TestCase):
    def test_feedback_uses_one_save_for_all_files_and_pairs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = SymbioWorkspace(temp_dir)
            workspace.init_workspace()

            with patch.object(
                workspace,
                "_save_sections_unlocked",
                wraps=workspace._save_sections_unlocked,
            ) as save_sections:
                workspace.record_feedback(
                    "batch feedback",
                    ["a.py", "b.py", "c.py", "d.py"],
                )

            self.assertEqual(save_sections.call_count, 1)
            self.assertEqual(save_sections.call_args.args[0], ["synapses", "relations"])
            self.assertEqual(len(workspace.relations["a.py"]), 3)

    def test_relation_degree_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = SymbioWorkspace(temp_dir)
            workspace.init_workspace()
            for index in range(MAX_RELATIONS_PER_FILE + 20):
                workspace.strengthen_relation("source.py", f"target_{index}.py", persist=False)

            self.assertLessEqual(len(workspace.relations["source.py"]), MAX_RELATIONS_PER_FILE)

    def test_stale_writers_preserve_both_updates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            SymbioWorkspace(temp_dir).init_workspace()
            first = SymbioWorkspace(temp_dir)
            second = SymbioWorkspace(temp_dir)
            first.load_state()
            second.load_state()

            first.add_dna_rule("rule-a")
            second.add_dna_rule("rule-b")

            final = SymbioWorkspace(temp_dir)
            final.load_state()
            self.assertEqual(final.dna_rules, ["rule-a", "rule-b"])

    def test_index_publish_preserves_concurrent_feedback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.py").write_text("pass", encoding="utf-8")
            (root / "b.py").write_text("pass", encoding="utf-8")
            SymbioWorkspace(temp_dir).init_workspace()
            scanner = SymbioWorkspace(temp_dir)
            scanner.load_state()

            writer = SymbioWorkspace(temp_dir)
            writer.record_feedback("connect files", ["a.py", "b.py"])
            scanner.publish_index_state({}, {}, {}, scanner.relations)

            final = SymbioWorkspace(temp_dir)
            final.load_state()
            self.assertEqual(final.relations["a.py"]["b.py"], 1.0)

    def test_atomic_save_preserves_previous_json_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = SymbioWorkspace(temp_dir)
            workspace.init_workspace()
            original = workspace.dna_file.read_text(encoding="utf-8")
            workspace.dna_rules.append("new rule")

            with patch("symbiopulse.core.genome.os.replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    workspace.save_state(["dna"])

            self.assertEqual(workspace.dna_file.read_text(encoding="utf-8"), original)
            json.loads(original)


class TestPathAndSemanticSafety(unittest.TestCase):
    def test_workspace_runtime_directories_are_excluded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("pass", encoding="utf-8")
            (root / ".worktrees" / "copy").mkdir(parents=True)
            (root / ".worktrees" / "copy" / "duplicate.py").write_text("pass", encoding="utf-8")
            (root / ".demo-node-modules-link" / "pkg").mkdir(parents=True)
            (root / ".demo-node-modules-link" / "pkg" / "duplicate.js").write_text("x", encoding="utf-8")

            path_filter = PathFilter(temp_dir)
            walked = list(path_filter.walk(100, 100, 5.0))
            zones = {relative for _, relative, _ in walked}

            self.assertIn("src", zones)
            self.assertFalse(any("worktrees" in zone for zone in zones))
            self.assertFalse(any("node-modules-link" in zone for zone in zones))

    def test_safety_boundaries_cannot_be_negated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".symbioignore").write_text("!.git/**\n!.symbio/**\n", encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "private").write_text("secret", encoding="utf-8")

            walked = list(PathFilter(temp_dir).walk(100, 100, 5.0))

            self.assertFalse(any(relative.startswith(".git") for _, relative, _ in walked))

    def test_scan_lock_makes_refresh_single_flight(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = SymbioWorkspace(temp_dir)
            workspace.init_workspace()
            lock = FileLock(workspace.scan_lock_file)
            with lock:
                status = _scan_workspace(Path(temp_dir), force=True)

            self.assertFalse(status["scan_performed"])
            self.assertEqual(status["index_state"], "indexing")

    def test_scan_budget_fails_without_publishing_partial_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("pass", encoding="utf-8")

            with self.assertRaises(ScanBudgetExceeded):
                list(PathFilter(temp_dir).walk(100, 0, 5.0))

    def test_ambient_api_key_does_not_enable_semantic_scan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = OlfactoryEngine(temp_dir)
            config = SymbioConfig(temp_dir)
            with patch.dict(os.environ, {"OPENAI_API_KEY": "ambient-secret"}):
                self.assertFalse(engine._semantic_scan_enabled(config))

    def test_existing_file_edit_refreshes_incremental_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            source = root / "src" / "service.py"
            source.write_text("def before(): pass", encoding="utf-8")
            workspace = SymbioWorkspace(temp_dir)
            workspace.init_workspace()

            first = OlfactoryEngine(temp_dir)
            scents, signatures = first.scan({}, {}, mode="full", workspace=workspace)
            source.write_text("def after(): pass", encoding="utf-8")
            workspace.fingerprints = first.fingerprint_map
            second = OlfactoryEngine(temp_dir)
            second.scan(scents, signatures, mode="standard", workspace=workspace)

            self.assertEqual(second.fingerprint_map["src"]["symbols"], ["after"])

    def test_scan_deadline_covers_file_extraction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / "src" / "service.py").write_text("def work(): pass", encoding="utf-8")
            symbio_dir = root / ".symbio"
            symbio_dir.mkdir()
            (symbio_dir / "config.json").write_text('{"scan_max_seconds": 0.01}', encoding="utf-8")
            engine = OlfactoryEngine(temp_dir)

            def slow_extract(*_):
                time.sleep(0.03)
                return [], []

            with patch.object(engine, "_extract_file_intelligence", side_effect=slow_extract):
                with self.assertRaises(ScanBudgetExceeded):
                    engine.scan({}, {}, mode="full")

    def test_large_directory_target_remains_retrievable(self):
        engine = OlfactoryEngine(".")
        files = [f"file_{index:03d}.py" for index in range(300)]
        fingerprint = engine._build_directory_fingerprint("src", files, [])

        matches = ResonatorEngine().trigger_resonance_multi(
            "file 299",
            ["src"],
            fingerprints={"src": fingerprint},
        )

        self.assertEqual(matches[0], "src/file_299.py")

    def test_force_refresh_is_queued_behind_active_scan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            started = threading.Event()
            release = threading.Event()
            calls = []

            def fake_scan(root, force=False):
                calls.append(force)
                if len(calls) == 1:
                    started.set()
                    release.wait(2)
                return {"scan_performed": True, "scan_reason": "test", "index_state": "ready"}

            with patch("symbiopulse.core.auto._scan_workspace", side_effect=fake_scan):
                schedule_workspace_refresh(temp_dir, min_interval_seconds=0)
                self.assertTrue(started.wait(1))
                queued = schedule_workspace_refresh(temp_dir, force=True, min_interval_seconds=0)
                release.set()
                deadline = time.monotonic() + 2
                while len(calls) < 2 and time.monotonic() < deadline:
                    time.sleep(0.01)

            self.assertTrue(queued["queued_force"])
            self.assertEqual(calls, [False, True])


if __name__ == "__main__":
    unittest.main()
