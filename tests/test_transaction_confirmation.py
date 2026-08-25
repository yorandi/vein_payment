"""Regression check: pengenalan biometrik tidak langsung memindahkan saldo."""

import ast
import unittest
from pathlib import Path


class TransactionConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.source = Path("app.py").read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def function_source(self, name):
        function = next(
            node for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
        return ast.get_source_segment(self.source, function)

    def test_payment_and_transfer_are_confirmed_before_balance_changes(self):
        verify_payment = self.function_source("verify_payment")
        confirm_payment = self.function_source("confirm_payment")
        verify_transfer = self.function_source("verify_transfer")
        confirm_transfer = self.function_source("confirm_transfer")

        self.assertIn('"status": "menunggu_konfirmasi"', verify_payment)
        self.assertNotIn("deduct_balance_for_payment", verify_payment)
        self.assertIn("deduct_balance_for_payment", confirm_payment)

        self.assertIn('"status": "menunggu_konfirmasi"', verify_transfer)
        self.assertNotIn("transfer_balance", verify_transfer)
        self.assertIn("transfer_balance", confirm_transfer)

    def test_confirmation_token_is_one_time_and_can_be_cancelled(self):
        self.assertIn("pending_transactions.pop(token, None)", self.function_source("consume_pending_transaction"))
        self.assertIn("pending_transactions.pop(token, None)", self.function_source("cancel_pending_transaction"))


if __name__ == "__main__":
    unittest.main()
