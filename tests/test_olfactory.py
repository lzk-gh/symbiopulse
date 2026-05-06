import unittest
import os
import shutil
from pathlib import Path
from symbiopulse.engines.olfactory import OlfactoryEngine

class TestOlfactory(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("test_project_mock")
        self.test_dir.mkdir(exist_ok=True)
        (self.test_dir / "src").mkdir(exist_ok=True)
        (self.test_dir / "src/policy_engine.py").write_text("policy evaluation workflow", encoding="utf-8")
        self.engine = OlfactoryEngine(root_dir=str(self.test_dir))

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_basic_sniffing(self):
        # Mocking scent map to test logic without LLM
        self.engine.scent_map = {
            "src": ["policy", "evaluation", "workflow"]
        }
        zones = self.engine.sniff_target_zones("Stabilize the policy evaluation workflow")
        self.assertIn("src", zones)

    def test_ignore_patterns(self):
        (self.test_dir / ".symbioignore").write_text("*.log\ntemp/", encoding="utf-8")
        (self.test_dir / "temp").mkdir(exist_ok=True)
        (self.test_dir / "error.log").write_text("error", encoding="utf-8")
        
        engine = OlfactoryEngine(root_dir=str(self.test_dir))
        self.assertTrue(engine.is_ignored("temp/file.txt"))
        self.assertTrue(engine.is_ignored("error.log"))
        self.assertFalse(engine.is_ignored("src/policy_engine.py"))

if __name__ == "__main__":
    unittest.main()
