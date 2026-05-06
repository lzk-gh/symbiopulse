import unittest
import shutil
from pathlib import Path
from symbiopulse.engines.resonator import ResonatorEngine

class TestResonator(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("test_project_resonator")
        self.test_dir.mkdir(exist_ok=True)
        (self.test_dir / "scheduler").mkdir(exist_ok=True)
        (self.test_dir / "scheduler/backpressure.py").write_text(
            "def regulate_backpressure():\n    return 'queue stabilized'",
            encoding="utf-8",
        )
        self.engine = ResonatorEngine(root_dir=str(self.test_dir))

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_structural_resonance(self):
        # Intent has words from filename and content
        intent = "Regulate scheduler backpressure"
        best_match = self.engine.trigger_resonance(intent, ["scheduler"])
        self.assertEqual(best_match, "scheduler/backpressure.py")

    def test_zone_filtering(self):
        # Ensure it doesn't search outside provided zones
        best_match = self.engine.trigger_resonance("timeout", ["other_zone"])
        self.assertIsNone(best_match)

if __name__ == "__main__":
    unittest.main()
