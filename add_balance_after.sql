-- Tambahan kolom balance_after (snapshot saldo pasca-transaksi, untuk riwayat/audit trail)
ALTER TABLE transactions ADD COLUMN balance_after NUMERIC(15,2);
