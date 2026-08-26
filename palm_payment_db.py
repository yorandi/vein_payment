"""
palm_payment_db.py
-------------------
Lapisan akses database untuk app.py -- MENGGANTIKAN pg_database.py
sepenuhnya. Dibangun di atas skema 5 tabel yang sama dengan
payment_routes.py (users, palm_templates, accounts, merchants,
transactions), dan reuse langsung get_connection/db_transaction/
_get_account_for_update/_validate_nominal dari sana supaya cara akses
DB (psycopg2 + row locking + rollback otomatis) konsisten di seluruh
sistem -- bukan dua implementasi terpisah seperti sebelumnya.

Perbedaan penting dibanding pg_database.py (versi lama, SQLAlchemy):
- User dicari lewat kolom users.nama (skema baru tidak punya full_name).
- Pembayaran sekarang WAJIB menyertakan merchant_id.
- Tidak ada lagi tabel scan_logs terpisah. Percobaan verifikasi yang
  GAGAL DIKENALI (nama tidak match sama sekali) tidak dicatat ke DB,
  karena tidak ada account_id valid untuk dihubungkan (kolom account_id
  di transactions bersifat NOT NULL) -- sama seperti perilaku
  /api/payment di payment_routes.py, yang juga tidak mencatat apa pun
  kalau validasi gagal sebelum baris transaksi dibuat.
"""

import pickle

from payment_routes import (
    PaymentError,
    _get_account_for_update,
    _validate_nominal,
    db_transaction,
)


def init_db():
    """Tabel sudah dibuat lewat migration_simplified_schema_new.sql --
    fungsi ini sengaja no-op, disediakan supaya app.py tidak perlu
    menghapus baris db.init_db()."""
    pass


# ---------------------------------------------------------------------
# Helper internal
# ---------------------------------------------------------------------
def _get_account_id_by_name(cur, nama):
    cur.execute(
        """
        SELECT a.account_id FROM accounts a
        JOIN users u ON u.user_id = a.user_id
            WHERE u.nama = %s AND u.is_active = TRUE
        """,
        (nama,),
    )
    row = cur.fetchone()
    if row is None:
        raise PaymentError(f"Akun '{nama}' tidak ditemukan", 404)
    return row["account_id"]


# ---------------------------------------------------------------------
# Query saldo & akun
# ---------------------------------------------------------------------
def get_user_id(nama):
    with db_transaction() as cur:
        cur.execute("SELECT user_id FROM users WHERE nama = %s", (nama,))
        row = cur.fetchone()
        return row["user_id"] if row else None


def get_active_user_id(nama):
    """Return user_id hanya bila akun aktif; dipakai sebagai preflight enrollment."""
    with db_transaction() as cur:
        cur.execute(
            "SELECT user_id FROM users WHERE nama = %s AND is_active = TRUE",
            (nama,),
        )
        row = cur.fetchone()
        return row["user_id"] if row else None


def get_balance(nama):
    """Return saldo (float) atau None kalau akun tidak ditemukan."""
    with db_transaction() as cur:
        cur.execute(
            """
            SELECT a.saldo FROM accounts a
            JOIN users u ON u.user_id = a.user_id
            WHERE u.nama = %s AND u.is_active = TRUE
            """,
            (nama,),
        )
        row = cur.fetchone()
        return float(row["saldo"]) if row else None


def list_accounts():
    """Return list of {'nama':.., 'saldo':..} untuk semua akun."""
    with db_transaction() as cur:
        cur.execute(
            """
            SELECT u.nama, a.saldo FROM accounts a
            JOIN users u ON u.user_id = a.user_id
            WHERE u.is_active = TRUE
            ORDER BY u.nama
            """
        )
        rows = cur.fetchall()
    return [{"nama": r["nama"], "saldo": float(r["saldo"])} for r in rows]


def list_merchants():
    """Return list of {'merchant_id':.., 'nama_merchant':..} untuk layar
    pemilihan merchant sebelum bayar."""
    with db_transaction() as cur:
        cur.execute("SELECT merchant_id, nama_merchant FROM merchants ORDER BY nama_merchant")
        rows = cur.fetchall()
    return [{"merchant_id": r["merchant_id"], "nama_merchant": r["nama_merchant"]} for r in rows]


def create_merchant(nama_merchant):
    """Tambah UMKM/merchant baru dan kembalikan data yang tersimpan.

    Nama dibandingkan tanpa membedakan huruf besar-kecil agar pilihan
    merchant tidak membingungkan dan tidak ada UMKM ganda.
    """
    if not isinstance(nama_merchant, str):
        raise PaymentError("Nama UMKM wajib diisi")
    nama_merchant = nama_merchant.strip()
    if not nama_merchant:
        raise PaymentError("Nama UMKM wajib diisi")
    if len(nama_merchant) > 100:
        raise PaymentError("Nama UMKM maksimal 100 karakter")

    with db_transaction() as cur:
        # Serialisasi pendaftaran nama yang sama tanpa mengubah skema DB.
        # Ini menutup race condition antara SELECT duplikasi dan INSERT.
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(LOWER(%s)))", (nama_merchant,))
        cur.execute(
            "SELECT merchant_id FROM merchants WHERE LOWER(nama_merchant) = LOWER(%s)",
            (nama_merchant,),
        )
        if cur.fetchone() is not None:
            raise PaymentError("UMKM dengan nama tersebut sudah terdaftar", 409)
        cur.execute(
            "INSERT INTO merchants (nama_merchant) VALUES (%s) RETURNING merchant_id, nama_merchant",
            (nama_merchant,),
        )
        row = cur.fetchone()
    return {"merchant_id": row["merchant_id"], "nama_merchant": row["nama_merchant"]}


def list_merchants_with_balance():
    """
    Return list of {'merchant_id', 'nama_merchant', 'total_diterima'} untuk
    halaman /merchant -- saldo tetap DERIVED (SUM transaksi 'payment'
    sukses), sama seperti /api/merchant/<id>/saldo di payment_routes.py,
    cuma diquery sekaligus buat semua merchant biar gak N+1 request.
    """
    with db_transaction() as cur:
        cur.execute(
            """
            SELECT m.merchant_id, m.nama_merchant,
                   COALESCE(SUM(t.nominal) FILTER (
                       WHERE t.jenis_transaksi = 'payment' AND t.status = 'success'
                   ), 0) AS total_diterima
            FROM merchants m
            LEFT JOIN transactions t ON t.merchant_id = m.merchant_id
            GROUP BY m.merchant_id, m.nama_merchant
            ORDER BY m.nama_merchant
            """
        )
        rows = cur.fetchall()
    return [
        {
            "merchant_id": r["merchant_id"],
            "nama_merchant": r["nama_merchant"],
            "total_diterima": float(r["total_diterima"]),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------
# Transaksi
# ---------------------------------------------------------------------
def deduct_balance_for_payment(nama, merchant_id, nominal):
    """
    Potong saldo untuk pembayaran ke merchant tertentu. Mencatat baris di
    `transactions` (jenis_transaksi='payment') hanya kalau pembayaran
    benar-benar sukses. Melempar PaymentError (dengan status_code yang
    sesuai) kalau akun/merchant tidak ditemukan atau saldo kurang.
    Return (saldo_baru: float, trx: dict).
    """
    nominal = _validate_nominal(nominal)
    if not merchant_id:
        raise PaymentError("merchant_id wajib diisi")

    with db_transaction() as cur:
        account_id = _get_account_id_by_name(cur, nama)
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

    return float(saldo_baru), trx


def add_balance_topup(nama, nominal):
    """Tambah saldo (topup) + catat transaksi. Return (saldo_baru, trx)."""
    nominal = _validate_nominal(nominal)
    with db_transaction() as cur:
        account_id = _get_account_id_by_name(cur, nama)
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

    return float(saldo_baru), trx


def transfer_balance(nama_pengirim, nama_penerima, nominal):
    """
    Kirim saldo dari nama_pengirim ke nama_penerima. Sama seperti
    /api/transfer di payment_routes.py: kunci kedua baris akun dengan
    urutan account_id konsisten (bukan urutan pengirim/penerima) supaya
    tidak deadlock kalau ada transfer berlawanan arah bersamaan.
    Return (saldo_baru_pengirim: float, trx: dict).
    """
    nominal = _validate_nominal(nominal)
    if nama_pengirim == nama_penerima:
        raise PaymentError("Tidak bisa mengirim saldo ke akun sendiri")

    with db_transaction() as cur:
        account_id = _get_account_id_by_name(cur, nama_pengirim)
        target_account_id = _get_account_id_by_name(cur, nama_penerima)

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

    return float(saldo_baru), trx


def get_recent_transactions(limit=50):
    """Riwayat gabungan topup/payment/transfer, terbaru dulu."""
    with db_transaction() as cur:
        cur.execute(
            """
            SELECT t.transaction_id, t.jenis_transaksi, t.nominal, t.status, t.created_at,
                   u.nama AS nama,
                   m.nama_merchant,
                   tu.nama AS nama_tujuan
            FROM transactions t
            JOIN accounts a ON a.account_id = t.account_id
            JOIN users u ON u.user_id = a.user_id
            LEFT JOIN merchants m ON m.merchant_id = t.merchant_id
            LEFT JOIN accounts ta ON ta.account_id = t.target_account_id
            LEFT JOIN users tu ON tu.user_id = ta.user_id
            ORDER BY t.created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    return [
        {
            "transaction_id": r["transaction_id"],
            "nama": r["nama"],
            "jenis_transaksi": r["jenis_transaksi"],
            "nama_merchant": r["nama_merchant"],
            "nama_tujuan": r["nama_tujuan"],
            "jumlah": float(r["nominal"]),
            "status": r["status"],
            "waktu": r["created_at"].isoformat(),
        }
        for r in rows
    ]


def log_biometric_attempt(candidate_name, distance, margin, threshold, matched, purpose, reason=None):
    """Simpan semua keputusan biometric, termasuk penolakan, untuk evaluasi FAR/FRR."""
    with db_transaction() as cur:
        user_id = None
        if candidate_name:
            cur.execute("SELECT user_id FROM users WHERE nama = %s", (candidate_name,))
            row = cur.fetchone()
            user_id = row["user_id"] if row else None
        cur.execute(
            """
            INSERT INTO biometric_attempts
                (candidate_user_id, candidate_name, distance, margin, threshold, matched, purpose, rejection_reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (user_id, candidate_name, distance, margin, threshold, matched, purpose, reason),
        )


# ---------------------------------------------------------------------
# Registrasi & penghapusan
# ---------------------------------------------------------------------
def seed_account(nama, saldo_awal=100000, embedding_vector=None):
    """
    Buat user + account baru, atau aktifkan kembali user yang sebelumnya
    dihapus secara soft-delete. Pada re-enrollment, saldo akun diatur ke
    saldo_awal baru dan template lama tetap nonaktif sebagai audit. Kalau
    embedding_vector diberikan (hasil rata-rata dari
    verifier.register_new_person), disimpan juga sebagai baris audit di
    palm_templates -- pencocokan biometrik aktual tetap lewat
    reference_embeddings.npz (verify.py), kolom ini murni untuk audit/
    riwayat pendaftaran.
    """
    with db_transaction() as cur:
        cur.execute(
            "SELECT user_id, is_active FROM users WHERE nama = %s FOR UPDATE",
            (nama,),
        )
        existing_user = cur.fetchone()
        if existing_user is None:
            cur.execute("INSERT INTO users (nama) VALUES (%s) RETURNING user_id", (nama,))
            user_id = cur.fetchone()["user_id"]
            cur.execute(
                "INSERT INTO accounts (user_id, saldo) VALUES (%s, %s)",
                (user_id, saldo_awal),
            )
        else:
            if existing_user["is_active"]:
                raise PaymentError(f"Akun '{nama}' sudah aktif")
            user_id = existing_user["user_id"]
            cur.execute(
                "UPDATE users SET is_active = TRUE, deleted_at = NULL WHERE user_id = %s",
                (user_id,),
            )
            cur.execute(
                "UPDATE accounts SET saldo = %s WHERE user_id = %s",
                (saldo_awal, user_id),
            )

        if embedding_vector is not None:
            cur.execute(
                "INSERT INTO palm_templates (user_id, embedding) VALUES (%s, %s)",
                (user_id, pickle.dumps(embedding_vector)),
            )

    return user_id


def delete_account(nama):
    """Kompatibilitas API lama: penghapusan fisik diganti soft-delete."""
    return deactivate_account(nama)


def deactivate_account(nama):
    """Soft-delete akun dan template audit tanpa menghapus riwayat transaksi."""
    with db_transaction() as cur:
        cur.execute(
            """
            UPDATE users
            SET is_active = FALSE, deleted_at = NOW()
            WHERE nama = %s AND is_active = TRUE
            RETURNING user_id
            """,
            (nama,),
        )
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE palm_templates SET is_active = FALSE WHERE user_id = %s", (row["user_id"],))
        return row is not None


def reactivate_account(nama):
    """Kompensasi jika penghapusan file embedding gagal."""
    with db_transaction() as cur:
        cur.execute(
            "UPDATE users SET is_active = TRUE, deleted_at = NULL WHERE nama = %s RETURNING user_id",
            (nama,),
        )
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE palm_templates SET is_active = TRUE WHERE user_id = %s", (row["user_id"],))
        return row is not None
