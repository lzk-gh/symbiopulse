import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from symbiopulse.core.auto import agent_protocols, ensure_workspace_ready
from symbiopulse.core.genome import SymbioWorkspace


class TestAutoRuntime(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("test_project_auto")
        self.test_dir.mkdir(exist_ok=True)
        (self.test_dir / "src").mkdir(exist_ok=True)
        (self.test_dir / "src" / "policy_engine.py").write_text(
            "def evaluate_policy():\n    return True\n",
            encoding="utf-8",
        )

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    @patch("symbiopulse.engines.olfactory.litellm", None)
    def test_ensure_workspace_ready_scans_for_mcp_runtime(self):
        workspace, status = ensure_workspace_ready(str(self.test_dir))

        self.assertTrue(status["scan_performed"])
        self.assertIn("src", workspace.scent_map)
        self.assertIn("src", workspace.fingerprints)
        for protocol in agent_protocols():
            self.assertTrue((self.test_dir / protocol.path).exists(), protocol.path)

    def test_agent_protocols_cover_mainstream_clients(self):
        paths = {protocol.path for protocol in agent_protocols()}

        self.assertIn("AGENTS.md", paths)
        self.assertIn("CLAUDE.md", paths)
        self.assertIn("GEMINI.md", paths)
        self.assertIn(".cursor/rules/symbiopulse.mdc", paths)
        self.assertIn(".github/copilot-instructions.md", paths)

    @patch("symbiopulse.engines.olfactory.litellm", None)
    def test_reindex_prunes_stale_relations(self):
        workspace = SymbioWorkspace(cwd=str(self.test_dir))
        workspace.init_workspace()
        workspace.strengthen_relation("src/policy_engine.py", "src/deleted.py")

        workspace, _ = ensure_workspace_ready(str(self.test_dir), force_scan=True)

        self.assertEqual(workspace.relations, {})


class TestWorkspaceMemory(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("test_project_memory")
        self.test_dir.mkdir(exist_ok=True)
        self.workspace = SymbioWorkspace(cwd=str(self.test_dir))
        self.workspace.init_workspace()

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_antigen_memory_reuses_reordered_task_words(self):
        self.workspace.strengthen_synapse("stabilize policy evaluation pipeline", "src/policy_engine.py")

        memory = self.workspace.get_o1_memory("policy evaluation pipeline")

        self.assertIsNotNone(memory)
        self.assertEqual(memory.target_filepath, "src/policy_engine.py")

    def test_dna_rules_are_deduplicated(self):
        self.workspace.add_dna_rule("Route cross-module state through explicit workspace contracts")
        self.workspace.add_dna_rule("Route cross-module state through explicit workspace contracts")

        self.assertEqual(
            self.workspace.dna_rules,
            ["Route cross-module state through explicit workspace contracts"],
        )


if __name__ == "__main__":
    unittest.main()
