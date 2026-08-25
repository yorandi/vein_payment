"""Konfigurasi runtime untuk VeinPay.

Memuat file .env lokal tanpa menimpa environment yang sudah diberikan oleh
systemd/Docker. Jangan commit file .env karena berisi kredensial database.
"""

import os
from pathlib import Path


def load_local_env() -> None:
    env_file = Path(__file__).resolve().with_name(".env")
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


load_local_env()
