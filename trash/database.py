"""
database.py
-------------
Helper SQLite untuk menyimpan saldo akun dan riwayat transaksi simulasi
sistem pembayaran palm vein. Dipakai oleh app.py.

CATATAN: ini database SIMULASI lokal untuk keperluan skripsi/demo. Saldo
di sini adalah data dummy, tidak terhubung ke sistem keuangan sungguhan
apa pun.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "payment.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            nama TEXT PRIMARY KEY,
            saldo INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama TEXT,
            jumlah INTEGER,
            saldo_setelah INTEGER,
            status TEXT NOT NULL,
            jarak_embedding REAL,
            waktu TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def seed_account(nama, saldo_awal=100000):
    """Membuat akun baru kalau belum ada (dipakai saat seeding awal)."""
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO accounts (nama, saldo) VALUES (?, ?)",
        (nama, saldo_awal),
    )
    conn.commit()
    conn.close()


def get_balance(nama):
    conn = get_connection()
    row = conn.execute("SELECT saldo FROM accounts WHERE nama = ?", (nama,)).fetchone()
    conn.close()
    return row["saldo"] if row else None


def deduct_balance(nama, jumlah):
    """Mengurangi saldo. Mengembalikan saldo baru, atau None kalau akun tidak ada."""
    conn = get_connection()
    row = conn.execute("SELECT saldo FROM accounts WHERE nama = ?", (nama,)).fetchone()
    if row is None:
        conn.close()
        return None
    saldo_baru = row["saldo"] - jumlah
    conn.execute("UPDATE accounts SET saldo = ? WHERE nama = ?", (saldo_baru, nama))
    conn.commit()
    conn.close()
    return saldo_baru


def log_transaction(nama, jumlah, saldo_setelah, status, jarak_embedding):
    conn = get_connection()
    conn.execute(
        """INSERT INTO transactions (nama, jumlah, saldo_setelah, status, jarak_embedding, waktu)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (nama, jumlah, saldo_setelah, status, jarak_embedding,
         datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def get_recent_transactions(limit=30):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM transactions ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_accounts():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM accounts ORDER BY nama").fetchall()
    conn.close()
    return [dict(r) for r in rows]
