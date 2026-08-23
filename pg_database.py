"""
pg_database.py — pengganti database.py (SQLite) lama.
Menyediakan fungsi dengan nama & signature yang sama, tapi implementasinya
lewat PostgreSQL via SQLAlchemy (db.py + models.py).

Cukup ganti baris import di app.py:
    import database as db          -->  import pg_database as db

Semua pemanggilan db.xxx() di app.py TIDAK PERLU diubah, kecuali
bagian /topup dan /delete_person yang tadinya pakai raw SQL manual
(lihat instruksi di chat).
"""

import uuid
from datetime import datetime

from db import SessionLocal
from models import User, Account, Transaction, TransactionType, ScanLog


def init_db():
    """Tabel sudah dibuat lewat schema.sql — fungsi ini sengaja no-op,
    disediakan supaya app.py tidak perlu menghapus baris db.init_db()."""
    pass


def _get_type_id(session, type_name):
    t = session.query(TransactionType).filter_by(type_name=type_name).first()
    if t is None:
        raise ValueError(f"transaction_type '{type_name}' tidak ditemukan di database")
    return t.type_id


def get_balance(nama):
    """Return saldo (float) atau None kalau akun tidak ditemukan."""
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.full_name == nama).first()
        if user is None or user.account is None:
            return None
        return float(user.account.balance)
    finally:
        session.close()


def deduct_balance(nama, jumlah):
    """Kurangi saldo user sebesar jumlah, return saldo baru (float)."""
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.full_name == nama).first()
        if user is None or user.account is None:
            raise ValueError(f"Akun '{nama}' tidak ditemukan")

        account = user.account
        if account.balance < jumlah:
            raise ValueError(f"Saldo '{nama}' tidak cukup")

        account.balance = account.balance - jumlah
        session.commit()
        return float(account.balance)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def add_balance(nama, jumlah):
    """Tambah saldo user sebesar jumlah (dipakai untuk topup), return saldo baru (float)."""
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.full_name == nama).first()
        if user is None or user.account is None:
            raise ValueError(f"Akun '{nama}' tidak ditemukan")

        account = user.account
        account.balance = account.balance + jumlah
        session.commit()
        return float(account.balance)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def log_transaction(nama, jumlah, saldo_setelah, status, jarak):
    """
    Mencatat hasil scan/transaksi.
    status yang didukung: 'sukses', 'saldo_tidak_cukup', 'akun_tidak_ditemukan',
    'verifikasi_gagal', 'topup'.

    - status 'sukses' / 'saldo_tidak_cukup' / 'topup'  -> insert ke transactions
    - jarak is not None                                -> insert ke scan_logs
      (jarak None berarti tidak ada scan biometrik baru di langkah ini,
       misalnya saat /topup dipanggil setelah /identify_only)
    """
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.full_name == nama).first()
        account = user.account if user else None

        matched = status in ("sukses", "saldo_tidak_cukup", "topup")
        transaction_id = None

        if matched and account is not None:
            if status == "topup":
                type_name = "topup"
                new_status = "success"
            else:
                type_name = "payment"
                new_status = "success" if status == "sukses" else "failed"

            type_id = _get_type_id(session, type_name)
            reference_code = f"TX-{uuid.uuid4().hex[:12]}"

            tx = Transaction(
                account_id=account.account_id,
                type_id=type_id,
                amount=jumlah,
                status=new_status,
                balance_after=saldo_setelah,
                reference_code=reference_code,
                created_at=datetime.now(),
            )
            session.add(tx)
            session.flush()  # supaya tx.transaction_id terisi tanpa commit dulu
            transaction_id = tx.transaction_id

        if jarak is not None:
            scan = ScanLog(
                user_id=user.user_id if user else None,
                transaction_id=transaction_id,
                similarity_score=jarak,
                matched=matched,
                scan_timestamp=datetime.now(),
            )
            session.add(scan)

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def seed_account(nama, saldo_awal=100000):
    """Buat user + account baru saat registrasi orang baru."""
    session = SessionLocal()
    try:
        existing = session.query(User).filter(User.full_name == nama).first()
        if existing is not None:
            raise ValueError(f"Akun '{nama}' sudah ada")

        # placeholder — sebaiknya diupdate manual lewat halaman admin nanti
        email = f"{nama.lower()}@placeholder.local"
        phone = f"PENDING-{uuid.uuid4().hex[:6]}"
        pin_hash = "CHANGE_ME"

        count = session.query(User).count()
        account_number = f"PV{count + 1:06d}"

        user = User(full_name=nama, email=email, phone_number=phone, pin_hash=pin_hash)
        session.add(user)
        session.flush()

        account = Account(user_id=user.user_id, account_number=account_number, balance=saldo_awal)
        session.add(account)

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def list_accounts():
    """Return list of {'nama':.., 'saldo':..} untuk semua akun."""
    session = SessionLocal()
    try:
        rows = (
            session.query(User.full_name, Account.balance)
            .join(Account, Account.user_id == User.user_id)
            .order_by(User.full_name)
            .all()
        )
        return [{"nama": nama, "saldo": float(saldo)} for nama, saldo in rows]
    finally:
        session.close()


def get_recent_transactions(limit=50):
    """
    Return list riwayat gabungan (transaksi nyata + percobaan gagal),
    diurutkan dari yang terbaru, dengan struktur field yang sama seperti
    schema SQLite lama supaya template history.html tidak perlu diubah.
    """
    session = SessionLocal()
    try:
        rows = (
            session.query(ScanLog)
            .order_by(ScanLog.scan_timestamp.desc())
            .limit(limit)
            .all()
        )

        result = []
        for row in rows:
            nama = row.user.full_name if row.user else None
            tx = row.transaction
            result.append({
                "nama": nama,
                "jumlah": float(tx.amount) if tx else None,
                "saldo_setelah": float(tx.balance_after) if (tx and tx.balance_after is not None) else None,
                "status": tx.status if tx else ("verifikasi_gagal" if nama else "akun_tidak_ditemukan"),
                "jarak_embedding": row.similarity_score,
                "waktu": row.scan_timestamp.isoformat(),
            })
        return result
    finally:
        session.close()


def delete_account(nama):
    """
    Hapus user beserta akunnya.
    CATATAN: kalau user ini punya riwayat transaksi/scan_logs, penghapusan akan
    gagal karena foreign key constraint (disengaja — supaya audit trail finansial
    tidak bisa hilang begitu saja). Untuk kasus itu, pertimbangkan menonaktifkan
    akun (mis. tambah kolom is_active di users) alih-alih menghapusnya.
    """
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.full_name == nama).first()
        if user is None:
            return False

        session.delete(user)  # cascade akan hapus account, palm_biometrics, biometric_frames
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
