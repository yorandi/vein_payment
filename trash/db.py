import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "payment")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD")

DB_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# pool kecil karena Pi 3B RAM terbatas (1GB)
engine = create_engine(
    DB_URL,
    pool_size=5,
    max_overflow=2,
    pool_pre_ping=True,   # cek koneksi masih hidup sebelum dipakai
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    """Dependency-style generator, cocok dipakai di Flask request context."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
