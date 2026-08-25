"""
payment_routes.py
------------------
Blueprint Flask untuk modul palm_payment, disesuaikan dengan skema
basis data sederhana (5 tabel): users, palm_templates, accounts,
merchants, transactions.

Satu tabel `transactions` menangani tiga jenis transaksi lewat kolom
`jenis_transaksi`: 'topup', 'payment', 'transfer'. Saldo merchant TIDAK
disimpan sebagai kolom terpisah -- dihitung (derived) dari SUM(nominal)
transaksi 'payment' milik merchant tersebut, supaya tidak ada data
redundan (konsisten dengan prinsip normalisasi yang dipakai di seluruh
skema).

Cara pakai:
    from payment_routes import payment_bp
    app.register_blueprint(payment_bp, url_prefix="/api")

Environment variables yang dibutuhkan (.env), mengikuti konfigurasi
yang sudah ada di project (koneksi TCP ke 127.0.0.1):
    DB_HOST=127.0.0.1
    DB_NAME=payment
    DB_USER=admin
    DB_PASSWORD=root
"""

import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from flask import Blueprint, jsonify, request

import config  # memuat .env sebelum koneksi database pertama

payment_bp = Blueprint("payment_bp", __name__)


# ---------------------------------------------------------------------
# Koneksi database
# ---------------------------------------------------------------------
def get_connection():
    missing = [key for key in ("DB_USER", "DB_PASSWORD") if not os.environ.get(key)]
    if missing:
        raise RuntimeError("Konfigurasi database belum lengkap: " + ", ".join(missing))
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        dbname=os.environ.get("DB_NAME", "payment"),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        port=os.environ.get("DB_PORT", "5432"),
        connect_timeout=5,
    )


@contextmanager
def db_transaction():
    """
    Context manager: buka koneksi + transaksi, otomatis COMMIT jika
    sukses, ROLLBACK jika ada exception. Selalu menutup koneksi.
    """
    conn = get_connection()
    conn.autocommit = False
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class PaymentError(Exception):
    """Error bisnis (saldo kurang, akun tidak ditemukan, dll)."""
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@payment_bp.errorhandler(PaymentError)
def handle_payment_error(err):
    return jsonify({"success": False, "error": err.message}), err.status_code


# ---------------------------------------------------------------------
# Helper query
# ---------------------------------------------------------------------
def _get_account_for_update(cur, account_id):
    """Ambil akun dengan row lock (FOR UPDATE) supaya aman dari race
    condition saat saldo diubah bersamaan."""
    cur.execute(
        "SELECT account_id, user_id, saldo FROM accounts WHERE account_id = %s FOR UPDATE",
        (account_id,),
    )
    account = cur.fetchone()
    if account is None:
        raise PaymentError(f"Akun dengan account_id={account_id} tidak ditemukan", 404)
    return account


def _get_account_id_by_user(cur, user_id):
    cur.execute("SELECT account_id FROM accounts WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    if row is None:
        raise PaymentError(f"Akun untuk user_id={user_id} tidak ditemukan", 404)
    return row["account_id"]


def _validate_nominal(nominal):
    """
    Validasi terpusat untuk field nominal supaya konsisten di semua
    endpoint. Menerima int/float (bukan string, bool, None, NaN, dsb.)
    dan mengembalikan nominal yang sudah divalidasi.
    """
    if nominal is None:
        raise PaymentError("nominal wajib diisi")
    # bool adalah subclass dari int di Python -- tolak eksplisit supaya
    # True/False tidak lolos jadi 1/0.
    if isinstance(nominal, bool) or not isinstance(nominal, (int, float)):
        raise PaymentError("nominal harus berupa angka")
    if isinstance(nominal, float) and (nominal != nominal):  # NaN check
        raise PaymentError("nominal tidak valid")
    if nominal <= 0:
        raise PaymentError("nominal harus lebih besar dari 0")
    return nominal


# ---------------------------------------------------------------------
# 1. TOP UP
# ---------------------------------------------------------------------
@payment_bp.route("/topup", methods=["POST"])
def topup():
    """
    Body JSON:
        { "user_id": 1, "nominal": 50000 }
    """
    data = request.get_json(force=True) or {}
    user_id = data.get("user_id")
    nominal = data.get("nominal")

    if not user_id:
        raise PaymentError("user_id wajib diisi")
    nominal = _validate_nominal(nominal)

    with db_transaction() as cur:
        account_id = _get_account_id_by_user(cur, user_id)
        _get_account_for_update(cur, account_id)  # kunci baris

        cur.execute(
            "UPDATE accounts SET saldo = saldo + %s WHERE account_id = %s RETURNING saldo",
            (nominal, account_id),
        )
        saldo_baru = cur.fetchone()["saldo"]

        cur.execute(
            """
            INSERT INTO transactions (account_id, jenis_transaksi, nominal, status)
            VALUES (%s, 'topup', %s, 'success')
            RETURNING transaction_id, created_at
            """,
            (account_id, nominal),
        )
        trx = cur.fetchone()

    return jsonify({
        "success": True,
        "transaction_id": trx["transaction_id"],
        "saldo_baru": str(saldo_baru),
        "created_at": trx["created_at"].isoformat(),
    })


# ---------------------------------------------------------------------
# 2. PEMBAYARAN (ke merchant) -- dipanggil SETELAH verifikasi biometrik
#    berhasil di sisi caller (lihat catatan di bawah fungsi ini)
# ---------------------------------------------------------------------
@payment_bp.route("/payment", methods=["POST"])
def payment():
    """
    Body JSON:
        { "user_id": 1, "merchant_id": 2, "nominal": 25000 }

    CATATAN INTEGRASI BIOMETRIK:
    Endpoint ini murni menangani logika saldo & pencatatan transaksi.
    Verifikasi vena telapak tangan (ekstraksi embedding 5 frame,
    pencocokan jarak Euclidean terhadap threshold 0,30) sebaiknya
    dilakukan SEBELUM endpoint ini dipanggil, pada endpoint/langkah
    verifikasi terpisah -- baru setelah verifikasi sukses, frontend
    memanggil /api/payment ini.
    """
    data = request.get_json(force=True) or {}
    user_id = data.get("user_id")
    merchant_id = data.get("merchant_id")
    nominal = data.get("nominal")

    if not user_id or not merchant_id:
        raise PaymentError("user_id dan merchant_id wajib diisi")
    nominal = _validate_nominal(nominal)

    with db_transaction() as cur:
        account_id = _get_account_id_by_user(cur, user_id)
        account = _get_account_for_update(cur, account_id)

        cur.execute("SELECT merchant_id FROM merchants WHERE merchant_id = %s", (merchant_id,))
        if cur.fetchone() is None:
            raise PaymentError(f"Merchant dengan merchant_id={merchant_id} tidak ditemukan", 404)

        if account["saldo"] < nominal:
            raise PaymentError("Saldo tidak mencukupi untuk melakukan pembayaran")

        cur.execute(
            "UPDATE accounts SET saldo = saldo - %s WHERE account_id = %s RETURNING saldo",
            (nominal, account_id),
        )
        saldo_baru = cur.fetchone()["saldo"]

        cur.execute(
            """
            INSERT INTO transactions (account_id, jenis_transaksi, merchant_id, nominal, status)
            VALUES (%s, 'payment', %s, %s, 'success')
            RETURNING transaction_id, created_at
            """,
            (account_id, merchant_id, nominal),
        )
        trx = cur.fetchone()

    return jsonify({
        "success": True,
        "transaction_id": trx["transaction_id"],
        "saldo_baru": str(saldo_baru),
        "created_at": trx["created_at"].isoformat(),
    })


# ---------------------------------------------------------------------
# 3. KIRIM SALDO (transfer antar pengguna)
# ---------------------------------------------------------------------
@payment_bp.route("/transfer", methods=["POST"])
def transfer():
    """
    Body JSON:
        { "user_id": 1, "target_user_id": 2, "nominal": 10000 }
    """
    data = request.get_json(force=True) or {}
    user_id = data.get("user_id")
    target_user_id = data.get("target_user_id")
    nominal = data.get("nominal")

    if not user_id or not target_user_id:
        raise PaymentError("user_id dan target_user_id wajib diisi")
    nominal = _validate_nominal(nominal)
    if user_id == target_user_id:
        raise PaymentError("Tidak bisa mengirim saldo ke akun sendiri")

    with db_transaction() as cur:
        account_id = _get_account_id_by_user(cur, user_id)
        target_account_id = _get_account_id_by_user(cur, target_user_id)

        # Kunci kedua baris akun dengan urutan account_id konsisten
        # (mencegah deadlock jika ada transfer berlawanan arah bersamaan)
        first_id, second_id = sorted([account_id, target_account_id])
        _get_account_for_update(cur, first_id)
        _get_account_for_update(cur, second_id)

        cur.execute("SELECT saldo FROM accounts WHERE account_id = %s", (account_id,))
        saldo_pengirim = cur.fetchone()["saldo"]
        if saldo_pengirim < nominal:
            raise PaymentError("Saldo tidak mencukupi untuk mengirim saldo")

        cur.execute(
            "UPDATE accounts SET saldo = saldo - %s WHERE account_id = %s",
            (nominal, account_id),
        )
        cur.execute(
            "UPDATE accounts SET saldo = saldo + %s WHERE account_id = %s",
            (nominal, target_account_id),
        )

        cur.execute(
            """
            INSERT INTO transactions (account_id, jenis_transaksi, target_account_id, nominal, status)
            VALUES (%s, 'transfer', %s, %s, 'success')
            RETURNING transaction_id, created_at
            """,
            (account_id, target_account_id, nominal),
        )
        trx = cur.fetchone()

        cur.execute("SELECT saldo FROM accounts WHERE account_id = %s", (account_id,))
        saldo_baru = cur.fetchone()["saldo"]

    return jsonify({
        "success": True,
        "transaction_id": trx["transaction_id"],
        "saldo_baru": str(saldo_baru),
        "created_at": trx["created_at"].isoformat(),
    })


# ---------------------------------------------------------------------
# 4. RIWAYAT TRANSAKSI
# ---------------------------------------------------------------------
@payment_bp.route("/transactions/<int:user_id>", methods=["GET"])
def transaction_history(user_id):
    with db_transaction() as cur:
        account_id = _get_account_id_by_user(cur, user_id)
        cur.execute(
            """
            SELECT transaction_id, jenis_transaksi, merchant_id,
                   target_account_id, nominal, status, created_at
            FROM transactions
            WHERE account_id = %s OR target_account_id = %s
            ORDER BY created_at DESC
            """,
            (account_id, account_id),
        )
        rows = cur.fetchall()

    riwayat = [
        {
            "transaction_id": r["transaction_id"],
            "jenis_transaksi": r["jenis_transaksi"],
            "merchant_id": r["merchant_id"],
            "target_account_id": r["target_account_id"],
            "nominal": str(r["nominal"]),
            "status": r["status"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
    return jsonify({"success": True, "riwayat": riwayat})


# ---------------------------------------------------------------------
# 5. SALDO MERCHANT (derived, bukan kolom tersimpan)
# ---------------------------------------------------------------------
@payment_bp.route("/merchant/<int:merchant_id>/saldo", methods=["GET"])
def merchant_saldo(merchant_id):
    with db_transaction() as cur:
        cur.execute("SELECT nama_merchant FROM merchants WHERE merchant_id = %s", (merchant_id,))
        merchant = cur.fetchone()
        if merchant is None:
            raise PaymentError(f"Merchant dengan merchant_id={merchant_id} tidak ditemukan", 404)

        cur.execute(
            """
            SELECT COALESCE(SUM(nominal), 0) AS total_diterima
            FROM transactions
            WHERE merchant_id = %s AND jenis_transaksi = 'payment' AND status = 'success'
            """,
            (merchant_id,),
        )
        total = cur.fetchone()["total_diterima"]

    return jsonify({
        "success": True,
        "merchant_id": merchant_id,
        "nama_merchant": merchant["nama_merchant"],
        "total_diterima": str(total),
    })
