"""
reset_all.py — Reset total sistem palm vein payment.
Mengosongkan:
  1. Semua data user/account/transaction/scan_log di PostgreSQL
  2. File reference_embeddings.npz (biometrik)

TIDAK menyentuh:
  - Model .tflite (embedding network hasil training) -- tidak perlu diulang
  - transaction_types (data lookup statis)

Jalankan SETELAH Flask app dihentikan, supaya tidak ada proses lain yang
sedang pegang reference_embeddings.npz di memori.

Cara pakai:
    python reset_all.py               # akan minta konfirmasi dulu
    python reset_all.py --yes         # skip konfirmasi (hati-hati!)
"""

import sys
import subprocess
import numpy as np
from datetime import datetime

MODEL_DIR = "./model"
REFERENCE_PATH = f"{MODEL_DIR}/reference_embeddings.npz"
EMBEDDING_DIM = 128  # SESUAIKAN kalau dimensi embedding model kamu bukan 128

DB_HOST = "127.0.0.1"
DB_USER = "admin"
DB_NAME = "payment"


def backup_database():
    filename = f"backup_sebelum_reset_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
    print(f"[1/4] Backup database ke {filename} ...")
    with open(filename, "w") as f:
        result = subprocess.run(
            ["pg_dump", "-h", DB_HOST, "-U", DB_USER, DB_NAME],
            stdout=f, stderr=subprocess.PIPE, text=True
        )
    if result.returncode != 0:
        print("  GAGAL backup database:", result.stderr)
        print("  Reset dibatalkan demi keamanan.")
        sys.exit(1)
    print("  OK.")


def backup_embeddings():
    import shutil, os
    if os.path.exists(REFERENCE_PATH):
        backup_path = REFERENCE_PATH + f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy(REFERENCE_PATH, backup_path)
        print(f"[2/4] Backup embedding ke {backup_path}")
    else:
        print("[2/4] File reference_embeddings.npz belum ada, skip backup.")


def reset_database():
    print("[3/4] Reset tabel users (CASCADE)...")
    result = subprocess.run(
        ["psql", "-h", DB_HOST, "-U", DB_USER, "-d", DB_NAME,
         "-c", "TRUNCATE TABLE users RESTART IDENTITY CASCADE;"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("  GAGAL reset database:", result.stderr)
        sys.exit(1)
    print("  OK. Semua user, account, transaction, scan_log, palm_biometrics, "
          "biometric_frames, merchants sudah kosong.")


def reset_embeddings():
    print("[4/4] Reset reference_embeddings.npz...")
    np.savez(REFERENCE_PATH, names=np.array([]), vectors=np.array([]).reshape(0, EMBEDDING_DIM))
    print(f"  OK. {REFERENCE_PATH} sekarang kosong (0 orang terdaftar).")


def main():
    skip_confirm = "--yes" in sys.argv

    print("=" * 60)
    print("RESET TOTAL — Palm Vein Payment System")
    print("=" * 60)
    print("Ini akan MENGHAPUS semua user, saldo, riwayat transaksi,")
    print("dan referensi biometrik. Model .tflite TIDAK terpengaruh.")
    print()

    if not skip_confirm:
        jawaban = input("Ketik 'RESET' (huruf besar) untuk melanjutkan: ")
        if jawaban != "RESET":
            print("Dibatalkan.")
            sys.exit(0)

    backup_database()
    backup_embeddings()
    reset_database()
    reset_embeddings()

    print()
    print("Selesai. Silakan jalankan ulang Flask dan registrasi user dari /register.")


if __name__ == "__main__":
    main()
