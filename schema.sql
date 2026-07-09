-- ============================================================
-- Skema Database: Palm Vein Payment System
-- Target: PostgreSQL 13+ di Raspberry Pi 3B (32-bit)
-- Bentuk normal: 3NF
-- ============================================================

BEGIN;

-- 1. USERS -----------------------------------------------------
CREATE TABLE users (
    user_id       SERIAL PRIMARY KEY,
    full_name     VARCHAR(100) NOT NULL,
    email         VARCHAR(120) UNIQUE NOT NULL,
    phone_number  VARCHAR(20) UNIQUE NOT NULL,
    pin_hash      VARCHAR(255) NOT NULL,        -- fallback auth (bcrypt/argon2)
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 2. PALM BIOMETRICS (embedding hasil agregasi akhir) ----------
CREATE TABLE palm_biometrics (
    biometric_id  SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    hand_side     VARCHAR(10) NOT NULL CHECK (hand_side IN ('left', 'right')),
    embedding_avg BYTEA NOT NULL,               -- hasil embedding_average, disimpan sbg binary (np.tobytes())
    enrolled_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE
);

-- 3. BIOMETRIC FRAMES (embedding mentah per-frame, sebelum agregasi)
CREATE TABLE biometric_frames (
    frame_id       SERIAL PRIMARY KEY,
    biometric_id   INTEGER NOT NULL REFERENCES palm_biometrics(biometric_id) ON DELETE CASCADE,
    embedding_raw  BYTEA NOT NULL,
    quality_score  REAL,                        -- opsional: skor kualitas frame saat capture
    captured_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 4. ACCOUNTS ----------------------------------------------------
CREATE TABLE accounts (
    account_id      SERIAL PRIMARY KEY,
    user_id         INTEGER UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,  -- 1:1 dgn users
    account_number  VARCHAR(20) UNIQUE NOT NULL,
    balance         NUMERIC(15,2) NOT NULL DEFAULT 0 CHECK (balance >= 0),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 5. TRANSACTION TYPES (lookup table) ---------------------------
CREATE TABLE transaction_types (
    type_id    SERIAL PRIMARY KEY,
    type_name  VARCHAR(30) UNIQUE NOT NULL   -- topup, transfer, payment, withdrawal
);

INSERT INTO transaction_types (type_name) VALUES
    ('topup'), ('transfer'), ('payment'), ('withdrawal');

-- 6. MERCHANTS ----------------------------------------------------
CREATE TABLE merchants (
    merchant_id    SERIAL PRIMARY KEY,
    merchant_name  VARCHAR(100) NOT NULL,
    category       VARCHAR(50),
    account_id     INTEGER UNIQUE REFERENCES accounts(account_id) ON DELETE SET NULL
);

-- 7. TRANSACTIONS ---------------------------------------------------
CREATE TABLE transactions (
    transaction_id         SERIAL PRIMARY KEY,
    account_id             INTEGER NOT NULL REFERENCES accounts(account_id),
    destination_account_id INTEGER REFERENCES accounts(account_id),  -- NULL kalau topup/withdrawal
    type_id                INTEGER NOT NULL REFERENCES transaction_types(type_id),
    amount                 NUMERIC(15,2) NOT NULL CHECK (amount > 0),
    status                 VARCHAR(20) NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending', 'success', 'failed')),
    reference_code         VARCHAR(40) UNIQUE NOT NULL,
    created_at             TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 8. SCAN LOGS (untuk evaluasi FAR/FRR/EER di bab evaluasi skripsi) --
CREATE TABLE scan_logs (
    log_id            SERIAL PRIMARY KEY,
    user_id           INTEGER REFERENCES users(user_id),  -- NULL kalau tidak ada match
    transaction_id    INTEGER REFERENCES transactions(transaction_id),
    similarity_score  REAL NOT NULL,
    matched           BOOLEAN NOT NULL,
    scan_timestamp    TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ============================================================
-- Index untuk performa query (penting di Pi 3B yg resource terbatas)
-- ============================================================
CREATE INDEX idx_transactions_account ON transactions(account_id);
CREATE INDEX idx_transactions_dest_account ON transactions(destination_account_id);
CREATE INDEX idx_palm_biometrics_user ON palm_biometrics(user_id);
CREATE INDEX idx_biometric_frames_biometric ON biometric_frames(biometric_id);
CREATE INDEX idx_scan_logs_user ON scan_logs(user_id);

COMMIT;
