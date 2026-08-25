"""
Migrasi data dari payment.db (SQLite lama) ke database PostgreSQL 'payment' (skema baru).

Struktur lama:
    accounts(nama TEXT PK, saldo INTEGER)
    transactions(id, nama, jumlah, saldo_setelah, status, jarak_embedding, waktu)

Strategi migrasi:
    - accounts.nama       -> users.full_name (+ accounts baru, relasi 1:1)
    - status 'sukses' / 'saldo_tidak_cukup' DAN nama terdaftar
          -> insert ke transactions (transaksi nyata) + scan_logs (matched=True)
    - status 'verifikasi_gagal' / 'akun_tidak_ditemukan'
          -> hanya insert ke scan_logs (matched=False, transaction_id=NULL)
          -> user_id diisi HANYA jika nama sudah terdaftar (kasus False Rejection),
             kalau tidak terdaftar user_id=NULL (kasus percobaan impostor / True Rejection)

PENTING: email, phone_number, dan pin_hash tidak ada di data lama.
Script ini mengisi placeholder yang WAJIB kamu update manual setelah migrasi
(lihat bagian akhir skrip untuk daftar user yang perlu dilengkapi datanya).

Jalankan: python migrate_sqlite_to_postgres.py
"""

import sqlite3
import hashlib
import uuid
from datetime import datetime

from sqlalchemy import text
from db import engine

SQLITE_PATH = "payment.db"  # sesuaikan path kalau berbeda

# Placeholder pin default (HARUS diganti sebelum production, hanya untuk migrasi data lama)
DEFAULT_PIN_HASH = hashlib.sha256("000000".encode()).hexdigest()


def migrate():
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    scur = sqlite_conn.cursor()

    with engine.begin() as pg:  # satu transaksi besar, rollback otomatis kalau error
        # -----------------------------------------------------------
        # 1. Migrasi accounts lama -> users + accounts baru
        # -----------------------------------------------------------
        scur.execute("SELECT nama, saldo FROM accounts")
        old_accounts = scur.fetchall()

        nama_to_user_id = {}
        nama_to_account_id = {}

        print(f"Migrasi {len(old_accounts)} akun...")
        for i, row in enumerate(old_accounts, start=1):
            nama, saldo = row["nama"], row["saldo"]

            email = f"{nama.lower().replace(' ', '_')}@placeholder.local"
            phone = f"PENDING-{i:04d}"  # placeholder, wajib diganti manual
            account_number = f"PV{i:06d}"

            user_id = pg.execute(
                text("""
                    INSERT INTO users (full_name, email, phone_number, pin_hash)
                    VALUES (:full_name, :email, :phone, :pin_hash)
                    RETURNING user_id
                """),
                {"full_name": nama, "email": email, "phone": phone, "pin_hash": DEFAULT_PIN_HASH},
            ).scalar()

            account_id = pg.execute(
                text("""
                    INSERT INTO accounts (user_id, account_number, balance)
                    VALUES (:user_id, :account_number, :balance)
                    RETURNING account_id
                """),
                {"user_id": user_id, "account_number": account_number, "balance": saldo},
            ).scalar()

            nama_to_user_id[nama] = user_id
            nama_to_account_id[nama] = account_id

        # id type_id untuk 'payment' (dipakai sebagai default transaksi lama,
        # karena data lama tidak membedakan topup/transfer/payment)
        payment_type_id = pg.execute(
            text("SELECT type_id FROM transaction_types WHERE type_name = 'payment'")
        ).scalar()

        # -----------------------------------------------------------
        # 2. Migrasi transactions lama -> transactions + scan_logs baru
        # -----------------------------------------------------------
        scur.execute("SELECT id, nama, jumlah, saldo_setelah, status, jarak_embedding, waktu FROM transactions")
        old_transactions = scur.fetchall()

        n_tx_migrated = 0
        n_scan_migrated = 0

        print(f"Migrasi {len(old_transactions)} baris transaksi/log scan...")
        for row in old_transactions:
            old_id, nama, jumlah, saldo_setelah, status, jarak, waktu = row
            user_id = nama_to_user_id.get(nama)
            account_id = nama_to_account_id.get(nama)
            matched = status in ("sukses", "saldo_tidak_cukup")
            created_at = datetime.fromisoformat(waktu)

            transaction_id = None
            if matched and account_id is not None:
                new_status = "success" if status == "sukses" else "failed"
                reference_code = f"LEGACY-{old_id}-{uuid.uuid4().hex[:8]}"

                transaction_id = pg.execute(
                    text("""
                        INSERT INTO transactions
                            (account_id, type_id, amount, status, reference_code, created_at)
                        VALUES
                            (:account_id, :type_id, :amount, :status, :ref, :created_at)
                        RETURNING transaction_id
                    """),
                    {
                        "account_id": account_id,
                        "type_id": payment_type_id,
                        "amount": jumlah,
                        "status": new_status,
                        "ref": reference_code,
                        "created_at": created_at,
                    },
                ).scalar()
                n_tx_migrated += 1

            pg.execute(
                text("""
                    INSERT INTO scan_logs
                        (user_id, transaction_id, similarity_score, matched, scan_timestamp)
                    VALUES
                        (:user_id, :transaction_id, :score, :matched, :ts)
                """),
                {
                    "user_id": user_id,
                    "transaction_id": transaction_id,
                    "score": jarak,
                    "matched": matched,
                    "ts": created_at,
                },
            )
            n_scan_migrated += 1

        print()
        print("=== Ringkasan migrasi ===")
        print(f"  Users/accounts dibuat : {len(old_accounts)}")
        print(f"  Transactions dibuat   : {n_tx_migrated}")
        print(f"  Scan logs dibuat      : {n_scan_migrated}")
        print()
        print("PENTING — daftar user yang WAJIB dilengkapi email/phone asli:")
        for nama in nama_to_user_id:
            print(f"  - {nama}")

    sqlite_conn.close()


if __name__ == "__main__":
    migrate()
