#!/usr/bin/env bash
# Jalankan pada Raspberry Pi OS Bookworm sebagai user pi, dari root proyek.
# Script tidak membuat database dan tidak menyimpan password.
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/vein_payment}"
VENV_DIR="$APP_DIR/.venv"

if [[ ! -f "$APP_DIR/app.py" ]]; then
  echo "APP_DIR tidak berisi app.py: $APP_DIR" >&2
  exit 1
fi

sudo apt update
sudo apt install -y python3-venv python3-picamera2 python3-opencv libatlas-base-dev postgresql-client

# picamera2 berasal dari apt, jadi venv harus dapat membaca system site packages.
python3 -m venv --system-site-packages "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install --extra-index-url https://www.piwheels.org/simple -r "$APP_DIR/requirements.txt"

mkdir -p "$APP_DIR/model"
if [[ ! -f "$APP_DIR/model/embedding_network.tflite" ]] || [[ ! -f "$APP_DIR/model/reference_embeddings.npz" ]]; then
  echo "Model belum tersedia. Salin embedding_network.tflite dan reference_embeddings.npz ke $APP_DIR/model/." >&2
fi

echo "Instalasi dependensi selesai. Lanjutkan dengan README bagian deployment PostgreSQL dan systemd."
