"""Unit test ringan; tidak membutuhkan kamera atau model TFLite."""

import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    from verify import PalmVeinVerifier
except ImportError:  # lingkungan CI tanpa runtime TFLite
    PalmVeinVerifier = None


@unittest.skipIf(PalmVeinVerifier is None, "runtime TFLite tidak tersedia")
class VerifierSafetyTests(unittest.TestCase):
    def make_verifier(self, names):
        verifier = PalmVeinVerifier.__new__(PalmVeinVerifier)
        verifier.names = list(names)
        verifier.vectors = np.ones((len(names), 4), dtype=np.float32)
        verifier._reference_lock = __import__("threading").RLock()
        fd, verifier.reference_path = tempfile.mkstemp(suffix=".npz")
        os.close(fd)
        return verifier

    def test_last_template_can_be_deleted_to_safe_empty_state(self):
        verifier = self.make_verifier(["randi"])
        self.assertTrue(verifier.delete_person("randi"))
        self.assertEqual(verifier.names, [])
        self.assertEqual(verifier.vectors.shape, (0, 4))

    def test_duplicate_registration_is_rejected(self):
        verifier = self.make_verifier(["randi"])
        verifier.get_embedding = lambda frame: np.ones(4, dtype=np.float32)
        with self.assertRaises(ValueError):
            verifier.register_new_person("randi", [object()])

    def test_reference_write_is_readable(self):
        verifier = self.make_verifier(["randi", "siti"])
        verifier._save_reference()
        data = np.load(verifier.reference_path)
        self.assertEqual(data["names"].tolist(), ["randi", "siti"])

    def test_multiframe_quality_gate_is_removed_for_experiment(self):
        source = Path("verify.py").read_text(encoding="utf-8")
        self.assertNotIn("def frame_quality", source)
        self.assertNotIn("kualitas frame rendah", source)

if __name__ == "__main__":
    unittest.main()
