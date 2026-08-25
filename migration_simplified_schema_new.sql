-- =====================================================================
-- Migrasi Skema Basis Data "payment" — Versi Sederhana (Fokus Payment)
-- Palm Vein Biometric Payment System
-- Jalankan di Raspberry Pi 3B via psql, contoh:
--   psql -h 127.0.0.1 -U <user_anda> -d payment -f migration_simplified_schema.sql
-- PERINGATAN: Script ini MENGHAPUS seluruh tabel & data lama. Pastikan
-- sudah tidak butuh data lama sebelum menjalankan (sesuai kesepakatan:
-- boleh mulai fresh).
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. Hapus seluruh tabel lama (termasuk tabel yang sudah tidak dipakai)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS topup_history CASCADE;
DROP TABLE IF EXISTS auth_logs CASCADE;
DROP TABLE IF EXISTS admin_users CASCADE;
DROP TABLE IF EXISTS merchants CASCADE;
DROP TABLE IF EXISTS accounts CASCADE;
DROP TABLE IF EXISTS palm_templates CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- ---------------------------------------------------------------------
-- 2. users — identitas dasar pengguna
-- ---------------------------------------------------------------------
CREATE TABLE users (
    user_id     SERIAL PRIMARY KEY,
    nama        VARCHAR(100) NOT NULL UNIQUE,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at  TIMESTAMP NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------
-- 3. palm_templates — embedding vena telapak tangan (1 user bisa >1 template
--    jika ingin simpan beberapa sesi pendaftaran)
-- ---------------------------------------------------------------------
CREATE TABLE palm_templates (
    template_id  SERIAL PRIMARY KEY,
    user_id      INT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    embedding    BYTEA NOT NULL,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_palm_templates_user_id ON palm_templates(user_id);

-- ---------------------------------------------------------------------
-- 4. accounts — saldo pembayaran (1 user = 1 akun)
-- ---------------------------------------------------------------------
CREATE TABLE accounts (
    account_id  SERIAL PRIMARY KEY,
    user_id     INT NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    saldo       DECIMAL(12,2) NOT NULL DEFAULT 0 CHECK (saldo >= 0)
);

-- ---------------------------------------------------------------------
-- 5. merchants — daftar merchant simulasi (cukup 1-2 untuk uji pembayaran)
-- ---------------------------------------------------------------------
CREATE TABLE merchants (
    merchant_id    SERIAL PRIMARY KEY,
    nama_merchant  VARCHAR(100) NOT NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------
-- 6. transactions — satu tabel untuk topup / payment / transfer,
--    dibedakan lewat kolom jenis_transaksi.
--    - topup    : hanya account_id + nominal terisi
--    - payment  : merchant_id ikut terisi, target_account_id NULL
--    - transfer : target_account_id ikut terisi, merchant_id NULL
-- ---------------------------------------------------------------------
CREATE TABLE transactions (
    transaction_id      SERIAL PRIMARY KEY,
    account_id           INT NOT NULL REFERENCES accounts(account_id),
    jenis_transaksi       VARCHAR(20) NOT NULL
                          CHECK (jenis_transaksi IN ('topup', 'payment', 'transfer')),
    merchant_id           INT REFERENCES merchants(merchant_id),
    target_account_id    INT REFERENCES accounts(account_id),
    nominal               DECIMAL(12,2) NOT NULL CHECK (nominal > 0),
    status                VARCHAR(20) NOT NULL DEFAULT 'success',
    created_at            TIMESTAMP NOT NULL DEFAULT NOW(),

    -- Pastikan kombinasi kolom konsisten dengan jenis_transaksi
    CONSTRAINT chk_transaction_consistency CHECK (
        (jenis_transaksi = 'topup'    AND merchant_id IS NULL     AND target_account_id IS NULL) OR
        (jenis_transaksi = 'payment'  AND merchant_id IS NOT NULL AND target_account_id IS NULL) OR
        (jenis_transaksi = 'transfer' AND merchant_id IS NULL     AND target_account_id IS NOT NULL)
    ),
    -- Tidak boleh kirim saldo ke akun sendiri
    CONSTRAINT chk_no_self_transfer CHECK (
        target_account_id IS NULL OR target_account_id <> account_id
    )
);
CREATE INDEX idx_transactions_account_id ON transactions(account_id);
CREATE INDEX idx_transactions_merchant_id ON transactions(merchant_id);
CREATE INDEX idx_transactions_target_account_id ON transactions(target_account_id);
CREATE INDEX idx_transactions_jenis ON transactions(jenis_transaksi);

-- Semua percobaan biometric dicatat agar FAR/FRR dapat dihitung dari data
-- penggunaan nyata, termasuk saat tidak ada kandidat yang cocok.
CREATE TABLE biometric_attempts (
    attempt_id        BIGSERIAL PRIMARY KEY,
    candidate_user_id INT NULL REFERENCES users(user_id),
    candidate_name    VARCHAR(100),
    distance          REAL,
    margin            REAL,
    threshold         REAL NOT NULL,
    matched           BOOLEAN NOT NULL,
    purpose           VARCHAR(20) NOT NULL CHECK (purpose IN ('payment', 'transfer', 'topup')),
    rejection_reason  TEXT,
    created_at        TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_biometric_attempts_created_at ON biometric_attempts(created_at DESC);

-- ---------------------------------------------------------------------
-- 7. Data awal (seed) — 2 merchant simulasi untuk uji coba pembayaran
-- ---------------------------------------------------------------------
INSERT INTO merchants (nama_merchant) VALUES
    ('Warung Simulasi A'),
    ('Toko Simulasi B');

COMMIT;

-- ---------------------------------------------------------------------
-- Verifikasi cepat setelah migrasi:
--   \dt                     -- lihat daftar tabel
--   \d transactions         -- lihat struktur tabel transactions
--   SELECT * FROM merchants;
-- ---------------------------------------------------------------------
