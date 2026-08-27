"""Regression checks untuk audit setiap scan biometrik."""

import ast
import unittest
from pathlib import Path


class ScanLogTests(unittest.TestCase):
    def test_scan_logs_schema_stores_vector_distance(self):
        source = Path("migration_scan_logs.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS scan_logs", source)
        self.assertIn("vector_distance        DOUBLE PRECISION", source)
        self.assertIn("second_vector_distance DOUBLE PRECISION", source)
        self.assertIn("ALTER TABLE scan_logs ADD COLUMN IF NOT EXISTS vector_distance", source)

    def test_each_verification_writes_scan_log(self):
        source = Path("palm_payment_db.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn("INSERT INTO scan_logs", source)
        self.assertIn("frame_count", source)

        app_source = Path("app.py").read_text(encoding="utf-8")
        ast.parse(app_source)
        self.assertIn("log_verification(result, \"payment\")", app_source)
        self.assertIn("log_verification(result, \"transfer\")", app_source)
        self.assertIn("log_verification(result, \"topup\")", app_source)


if __name__ == "__main__":
    unittest.main()
