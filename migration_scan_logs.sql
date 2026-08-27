-- Jalankan sekali pada database yang sudah memakai migration_hardening.sql.
-- Tidak mengubah atau menghapus data lama.
BEGIN;

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

-- Bila tabel sudah dibuat oleh eksperimen/versi lama, lengkapi kolom yang
-- dipakai aplikasi baru tanpa menghapus baris log yang telah ada.
ALTER TABLE scan_logs ADD COLUMN IF NOT EXISTS candidate_user_id INT;
ALTER TABLE scan_logs ADD COLUMN IF NOT EXISTS candidate_name VARCHAR(100);
ALTER TABLE scan_logs ADD COLUMN IF NOT EXISTS vector_distance DOUBLE PRECISION;
ALTER TABLE scan_logs ADD COLUMN IF NOT EXISTS second_vector_distance DOUBLE PRECISION;
ALTER TABLE scan_logs ADD COLUMN IF NOT EXISTS margin REAL;
ALTER TABLE scan_logs ADD COLUMN IF NOT EXISTS threshold REAL;
ALTER TABLE scan_logs ADD COLUMN IF NOT EXISTS matched BOOLEAN;
ALTER TABLE scan_logs ADD COLUMN IF NOT EXISTS purpose VARCHAR(20);
ALTER TABLE scan_logs ADD COLUMN IF NOT EXISTS frame_count SMALLINT;
ALTER TABLE scan_logs ADD COLUMN IF NOT EXISTS rejection_reason TEXT;
ALTER TABLE scan_logs ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_scan_logs_created_at ON scan_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scan_logs_purpose ON scan_logs (purpose);

COMMIT;
