-- Jalankan SEKALI pada database PostgreSQL yang sudah memakai
-- migration_simplified_schema_new.sql. Script ini tidak menghapus transaksi.
BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL;
ALTER TABLE palm_templates ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

-- Nama merupakan identifier aplikasi saat ini. Bersihkan duplikat secara
-- manual sebelum menjalankan indeks ini bila statement gagal.
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_nama ON users (nama);
CREATE INDEX IF NOT EXISTS idx_users_active ON users (is_active);

CREATE TABLE IF NOT EXISTS biometric_attempts (
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
CREATE INDEX IF NOT EXISTS idx_biometric_attempts_created_at ON biometric_attempts (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_biometric_attempts_matched ON biometric_attempts (matched);

-- Log mentah setiap pemindaian untuk evaluasi eksperimen. `vector_distance`
-- adalah jarak Euclidean embedding scan terhadap kandidat terdekat.
CREATE TABLE IF NOT EXISTS scan_logs (
    scan_log_id            BIGSERIAL PRIMARY KEY,
    candidate_user_id      INT NULL REFERENCES users(user_id),
    candidate_name         VARCHAR(100),
    vector_distance        DOUBLE PRECISION,
    second_vector_distance DOUBLE PRECISION,
    margin                 REAL,
    threshold              REAL NOT NULL,
    matched                BOOLEAN NOT NULL,
    purpose                VARCHAR(20) NOT NULL CHECK (purpose IN ('payment', 'transfer', 'topup')),
    frame_count            SMALLINT,
    rejection_reason       TEXT,
    created_at             TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_scan_logs_created_at ON scan_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scan_logs_purpose ON scan_logs (purpose);

COMMIT;
