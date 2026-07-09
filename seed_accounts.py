"""
seed_accounts.py
-------------------
Mengisi saldo awal untuk setiap orang yang sudah terdaftar di
reference_embeddings.npz (hasil training siamese_network.py), supaya bisa
langsung dicoba di simulasi pembayaran.

Cara pakai:
    python seed_accounts.py --model_dir ./model --saldo_awal 100000
"""

import argparse
import os
import numpy as np
import database as db


def main(args):
    data = np.load(os.path.join(args.model_dir, "reference_embeddings.npz"), allow_pickle=True)
    names = list(data["names"])

    db.init_db()
    for nama in names:
        db.seed_account(nama, saldo_awal=args.saldo_awal)
        print(f"Akun '{nama}' disiapkan dengan saldo awal "
              f"Rp{args.saldo_awal:,}".replace(",", "."))

    print(f"\nTotal {len(names)} akun siap dipakai untuk simulasi.")
    print("Jalankan 'python app.py' untuk mulai memakai sistemnya.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_dir", default="./model")
    parser.add_argument("--saldo_awal", type=int, default=100000)
    args = parser.parse_args()
    main(args)
