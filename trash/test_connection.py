"""
Script untuk menguji koneksi ke database PostgreSQL 'payment'.
Jalankan: python test_connection.py
"""

from sqlalchemy import text
from db import engine, DB_HOST, DB_PORT, DB_NAME, DB_USER


def test_connection():
    print(f"Mencoba koneksi ke {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME} ...")
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version();")).scalar()
            print("✓ Koneksi berhasil")
            print(f"  PostgreSQL version: {version}")

            # cek tabel yang ada di schema public
            result = conn.execute(text("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name;
            """))
            tables = [row[0] for row in result]
            print(f"  Jumlah tabel ditemukan: {len(tables)}")
            for t in tables:
                print(f"    - {t}")

            # cek isi transaction_types sebagai sanity check data awal
            result = conn.execute(text("SELECT type_name FROM transaction_types ORDER BY type_id;"))
            types = [row[0] for row in result]
            print(f"  transaction_types: {types}")

    except Exception as e:
        print("✗ Koneksi gagal")
        print(f"  Error: {e}")


if __name__ == "__main__":
    test_connection()
