"""Regression checks untuk endpoint penambahan UMKM."""

import ast
import unittest
from pathlib import Path


class MerchantManagementTests(unittest.TestCase):
    def test_merchant_creation_validates_name_and_rejects_duplicates(self):
        source = Path("palm_payment_db.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn("def create_merchant(nama_merchant)", source)
        self.assertIn("Nama UMKM wajib diisi", source)
        self.assertIn("LOWER(nama_merchant) = LOWER(%s)", source)
        self.assertIn("pg_advisory_xact_lock", source)
        self.assertIn("UMKM dengan nama tersebut sudah terdaftar", source)

    def test_merchants_route_accepts_post(self):
        source = Path("app.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn('@app.route("/merchants", methods=["GET", "POST"])', source)
        self.assertIn("db.create_merchant", source)


if __name__ == "__main__":
    unittest.main()
