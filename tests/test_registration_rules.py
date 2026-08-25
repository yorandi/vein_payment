"""Regression test untuk aturan preflight registrasi tanpa database/camera."""

import ast
import unittest
from pathlib import Path


class RegistrationRuleTests(unittest.TestCase):
    def test_application_checks_only_active_user_before_reenrollment(self):
        source = Path("app.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn("db.get_active_user_id(safe_nama)", source)
        self.assertNotIn("if db.get_user_id(safe_nama) is not None", source)


if __name__ == "__main__":
    unittest.main()
