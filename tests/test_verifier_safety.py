"""Unit test ringan; tidak membutuhkan kamera atau model TFLite."""

import os
import tempfile
import unittest

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

    def test_quality_metrics_accept_low_contrast_nonempty_noir_like_frame(self):
        frame = np.full((20, 20, 3), 40, dtype=np.uint8)
        frame[::2, ::2] = 45
        brightness, contrast, sharpness = PalmVeinVerifier.frame_quality(frame)
        self.assertGreater(brightness, 3)
        self.assertGreater(contrast, 2)
        self.assertGreaterEqual(sharpness, 1)


if __name__ == "__main__":
    unittest.main()
