"""Menjaga threshold demo tetap dapat dikonfigurasi lewat environment."""

import ast
import unittest
from pathlib import Path


class ThresholdConfigTests(unittest.TestCase):
    def test_threshold_reads_environment(self):
        source = Path("app.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn('os.environ.get("BIOMETRIC_THRESHOLD", "0.30")', source)


if __name__ == "__main__":
    unittest.main()
