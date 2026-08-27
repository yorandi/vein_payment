"""
app.py — VeinPay Simulasi Sistem Pembayaran Palm Vein
-------------------------------------------------------
Route:
  /           -> landing page
  /pay        -> terminal merchant (bayar)
  /topup      -> isi saldo
  /register   -> registrasi orang baru
  /history    -> riwayat transaksi

API:
  POST /verify_payment   -> verifikasi, lalu menunggu konfirmasi pengguna
  POST /confirm_payment  -> potong saldo setelah konfirmasi
  POST /verify_transfer  -> verifikasi, lalu menunggu konfirmasi pengguna
  POST /confirm_transfer -> kirim saldo setelah konfirmasi
  POST /identify_only    -> identifikasi saja (untuk topup step 1)
  POST /topup            -> tambah saldo (setelah identifikasi)
  POST /start_register   -> mulai sesi registrasi
  GET  /register_status  -> status sesi registrasi
  POST /delete_person    -> hapus registrasi
  GET  /riwayat          -> riwayat transaksi
  GET  /akun             -> daftar akun
  GET  /debug_scan       -> debug jarak embedding
  GET  /video_feed       -> MJPEG stream
"""

from flask import Flask, render_template, Response, request, jsonify
from picamera2 import Picamera2
import cv2
import time
import threading
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os

import config  # noqa: F401 -- pastikan .env sudah dimuat
from verify import PalmVeinVerifier
import palm_payment_db as db
from payment_routes import payment_bp, PaymentError

app = Flask(__name__)

app.register_blueprint(payment_bp, url_prefix="/api")


MODEL_DIR  = str(Path(__file__).resolve().with_name("model"))
# Konfigurasikan per lingkungan. Nilai 0.30 adalah operating point demo yang
# digunakan pada evaluasi pengguna saat ini; catatan FAR/FRR disimpan agar
# threshold dapat dikalibrasi ulang dari data kamera NoIR v2.
THRESHOLD  = float(os.environ.get("BIOMETRIC_THRESHOLD", "0.30"))
SCAN_FRAMES = 5
SCAN_DELAY  = 0.3
AGGREGATION = "embedding_average"
MIN_MARGIN  = 0.02
STREAM_SIZE = (640, 360)
CAMERA_SIZE = (640, 480)  # cukup untuk model 128x128, lebih ringan untuk Pi 3B
REG_TOTAL_FRAMES = 30
REG_DELAY = 0.5

db.init_db()
if not 0.0 < THRESHOLD <= 2.0:
    raise ValueError("BIOMETRIC_THRESHOLD harus lebih besar dari 0 dan maksimal 2")
verifier = PalmVeinVerifier(MODEL_DIR, threshold=THRESHOLD)

picam2 = Picamera2()
video_config = picam2.create_video_configuration(
    main={"size": CAMERA_SIZE, "format": "RGB888"}, controls={"FrameRate": 20}
)
picam2.configure(video_config)
picam2.start()
time.sleep(1)

camera_lock = threading.Lock()

registration_state = {
    "running": False, "nama": "", "count": 0,
    "total": REG_TOTAL_FRAMES, "message": "Siap.",
}
registration_lock = threading.Lock()
verifier_lock = threading.RLock()

# Token verifikasi singkat mencegah halaman top-up mengirim nama akun bebas
# setelah proses identifikasi selesai. Penyimpanan in-memory cukup untuk demo
# satu proses; token hilang secara aman saat aplikasi restart.
topup_tokens = {}
topup_token_lock = threading.Lock()
TOPUP_TOKEN_TTL_SECONDS = 60
PENDING_TRANSACTION_TTL_SECONDS = 30
pending_transactions = {}
pending_transaction_lock = threading.Lock()


def issue_topup_token(nama):
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=TOPUP_TOKEN_TTL_SECONDS)
    with topup_token_lock:
        now = datetime.now(timezone.utc)
        expired = [key for key, item in topup_tokens.items() if item["expires_at"] <= now]
        for key in expired:
            del topup_tokens[key]
        topup_tokens[token] = {"nama": nama, "expires_at": expires_at}
    return token


def consume_topup_token(token, nama):
    if not isinstance(token, str):
        return False
    with topup_token_lock:
        item = topup_tokens.pop(token, None)
    return bool(item and item["expires_at"] > datetime.now(timezone.utc) and item["nama"] == nama)


def issue_pending_transaction(kind, payload):
    """Buat token satu kali; tidak ada saldo yang berubah pada tahap ini."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=PENDING_TRANSACTION_TTL_SECONDS)
    with pending_transaction_lock:
        now = datetime.now(timezone.utc)
        expired = [key for key, item in pending_transactions.items() if item["expires_at"] <= now]
        for key in expired:
            del pending_transactions[key]
        pending_transactions[token] = {"kind": kind, "payload": payload, "expires_at": expires_at}
    return token


def consume_pending_transaction(token, kind):
    if not isinstance(token, str):
        return None
    with pending_transaction_lock:
        item = pending_transactions.pop(token, None)
    if not item or item["kind"] != kind or item["expires_at"] <= datetime.now(timezone.utc):
        return None
    return item["payload"]


def cancel_pending_transaction(token):
    if not isinstance(token, str):
        return False
    with pending_transaction_lock:
        return pending_transactions.pop(token, None) is not None


def capture_frame_bgr():
    with camera_lock:
        frame = picam2.capture_array()
    return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)


def capture_multiframe():
    frames = []
    for _ in range(SCAN_FRAMES):
        frames.append(capture_frame_bgr())
        time.sleep(SCAN_DELAY)
    return frames


def log_verification(result, purpose):
    """Audit non-finansial; jangan pernah mengubah keputusan verifikasi bila log gagal."""
    try:
        db.log_biometric_attempt(
            result.get("nama"), result.get("jarak_final"), result.get("margin"),
            verifier.threshold, result.get("cocok", False), purpose,
            result.get("alasan_tolak"), result.get("jarak_kandidat_kedua"), SCAN_FRAMES,
        )
    except Exception as exc:
        app.logger.error("Gagal menyimpan biometric attempt: %s", exc)


def gen_frames():
    while True:
        frame_bgr = capture_frame_bgr()
        small = cv2.resize(frame_bgr, STREAM_SIZE)
        ok, buffer = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            continue
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")
        time.sleep(0.03)


# ----------------------------------------------------------------
# Pages
# ----------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/pay")
def pay_page():
    return render_template("pay.html")

@app.route("/topup")
def topup_page():
    return render_template("topup.html")

@app.route("/register")
def register_page():
    return render_template("register.html")

@app.route("/history")
def history_page():
    return render_template("history.html")

@app.route("/merchant")
def merchant_page():
    return render_template("merchant.html")

@app.route("/transfer")
def transfer_page():
    return render_template("transfer.html")

@app.route("/video_feed")
def video_feed():
    return Response(gen_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")


# ----------------------------------------------------------------
# API — Pembayaran
# ----------------------------------------------------------------
@app.route("/verify_payment", methods=["POST"])
def verify_payment():
    data = request.get_json(silent=True) or {}
    try:
        jumlah = int(data.get("jumlah", 0))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Nominal tidak valid"}), 400
    if jumlah <= 0:
        return jsonify({"status": "error", "message": "Nominal harus lebih besar dari 0"}), 400

    merchant_id = data.get("merchant_id")
    if not merchant_id:
        return jsonify({"status": "error", "message": "Pilih merchant dulu sebelum bayar"}), 400

    frames = capture_multiframe()
    with verifier_lock:
        result = verifier.identify_multiframe(frames, strategy=AGGREGATION, min_margin=MIN_MARGIN)
    log_verification(result, "payment")
    nama  = result["nama"]
    jarak = result["jarak_final"]
    cocok = result["cocok"]

    if not cocok:
        return jsonify({
            "status": "gagal_verifikasi",
            "message": f"Telapak tangan tidak dikenali ({AGGREGATION}, {SCAN_FRAMES} frame).",
            "jarak_final": jarak,
            "margin": result.get("margin"),
            "alasan_tolak": result.get("alasan_tolak"),
        })

    return jsonify({
        "status": "menunggu_konfirmasi",
        "confirmation_token": issue_pending_transaction("payment", {
            "nama": nama, "merchant_id": merchant_id, "jumlah": jumlah,
            "jarak_final": jarak, "margin": result.get("margin"),
        }),
        "nama": nama, "jumlah": jumlah,
        "jarak_final": jarak, "margin": result.get("margin"),
        "message": "Scan dikenali. Konfirmasikan identitas sebelum saldo dipotong.",
    })


@app.route("/confirm_payment", methods=["POST"])
def confirm_payment():
    payload = consume_pending_transaction((request.get_json(silent=True) or {}).get("confirmation_token"), "payment")
    if payload is None:
        return jsonify({"status": "error", "message": "Konfirmasi tidak valid atau sudah kedaluwarsa. Scan ulang."}), 409
    try:
        saldo_baru, trx = db.deduct_balance_for_payment(payload["nama"], payload["merchant_id"], payload["jumlah"])
    except PaymentError as e:
        return jsonify({"status": "error", "message": e.message}), e.status_code
    return jsonify({
        "status": "sukses", "nama": payload["nama"], "jumlah": payload["jumlah"], "saldo_baru": saldo_baru,
        "jarak_final": payload["jarak_final"], "margin": payload["margin"],
        "message": (f"Pembayaran berhasil. Saldo {payload['nama']}: Rp{saldo_baru:,.0f}").replace(",", "."),
    })


# ----------------------------------------------------------------
# API — Transfer ke sesama user (verifikasi pengirim via palm scan)
# ----------------------------------------------------------------
@app.route("/verify_transfer", methods=["POST"])
def verify_transfer():
    data = request.get_json(silent=True) or {}
    try:
        jumlah = int(data.get("jumlah", 0))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Nominal tidak valid"}), 400
    if jumlah <= 0:
        return jsonify({"status": "error", "message": "Nominal harus lebih besar dari 0"}), 400

    target_nama = (data.get("target_nama") or "").strip()
    if not target_nama:
        return jsonify({"status": "error", "message": "Pilih penerima dulu"}), 400

    frames = capture_multiframe()
    with verifier_lock:
        result = verifier.identify_multiframe(frames, strategy=AGGREGATION, min_margin=MIN_MARGIN)
    log_verification(result, "transfer")
    nama  = result["nama"]
    jarak = result["jarak_final"]
    cocok = result["cocok"]

    if not cocok:
        return jsonify({
            "status": "gagal_verifikasi",
            "message": f"Telapak tangan tidak dikenali ({AGGREGATION}, {SCAN_FRAMES} frame).",
            "jarak_final": jarak,
            "margin": result.get("margin"),
            "alasan_tolak": result.get("alasan_tolak"),
        })

    if nama == target_nama:
        return jsonify({
            "status": "error",
            "nama": nama,
            "message": "Tidak bisa mengirim saldo ke akun sendiri (yang teridentifikasi dari scan sama dengan penerima yang dipilih).",
        }), 400

    return jsonify({
        "status": "menunggu_konfirmasi",
        "confirmation_token": issue_pending_transaction("transfer", {
            "nama": nama, "target_nama": target_nama, "jumlah": jumlah,
            "jarak_final": jarak, "margin": result.get("margin"),
        }),
        "nama": nama, "target_nama": target_nama, "jumlah": jumlah,
        "jarak_final": jarak, "margin": result.get("margin"),
        "message": "Scan dikenali. Konfirmasikan identitas sebelum saldo dikirim.",
    })


@app.route("/confirm_transfer", methods=["POST"])
def confirm_transfer():
    payload = consume_pending_transaction((request.get_json(silent=True) or {}).get("confirmation_token"), "transfer")
    if payload is None:
        return jsonify({"status": "error", "message": "Konfirmasi tidak valid atau sudah kedaluwarsa. Scan ulang."}), 409
    try:
        saldo_baru, trx = db.transfer_balance(payload["nama"], payload["target_nama"], payload["jumlah"])
    except PaymentError as e:
        return jsonify({"status": "error", "message": e.message}), e.status_code
    return jsonify({
        "status": "sukses", "nama": payload["nama"], "target_nama": payload["target_nama"],
        "jumlah": payload["jumlah"], "saldo_baru": saldo_baru,
        "jarak_final": payload["jarak_final"], "margin": payload["margin"],
        "message": (f"Transfer berhasil. Saldo {payload['nama']}: Rp{saldo_baru:,.0f}").replace(",", "."),
    })


@app.route("/cancel_pending_transaction", methods=["POST"])
def cancel_pending():
    canceled = cancel_pending_transaction((request.get_json(silent=True) or {}).get("confirmation_token"))
    return jsonify({"status": "dibatalkan" if canceled else "tidak_ditemukan"})


# ----------------------------------------------------------------
# API — Identifikasi saja (untuk halaman top-up step 1)
# ----------------------------------------------------------------
@app.route("/identify_only", methods=["POST"])
def identify_only():
    frames = capture_multiframe()
    with verifier_lock:
        result = verifier.identify_multiframe(frames, strategy=AGGREGATION, min_margin=MIN_MARGIN)
    log_verification(result, "topup")
    nama  = result["nama"]
    cocok = result["cocok"]

    saldo = db.get_balance(nama) if cocok else None
    return jsonify({
        "cocok": cocok,
        "nama": nama if cocok else None,
        "saldo": saldo,
        "jarak_final": result["jarak_final"],
        "margin": result.get("margin"),
        "alasan_tolak": result.get("alasan_tolak"),
        "verification_token": issue_topup_token(nama) if cocok else None,
    })


# ----------------------------------------------------------------
# API — Top-up saldo
# ----------------------------------------------------------------
@app.route("/topup", methods=["POST"])
def do_topup():
    data = request.get_json(silent=True) or {}
    nama = (data.get("nama") or "").strip()
    verification_token = data.get("verification_token")
    try:
        jumlah = int(data.get("jumlah", 0))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Jumlah tidak valid"}), 400

    if not nama:
        return jsonify({"status": "error", "message": "Nama tidak boleh kosong"}), 400
    if not consume_topup_token(verification_token, nama):
        return jsonify({"status": "error", "message": "Verifikasi top-up tidak valid atau sudah kedaluwarsa. Scan ulang."}), 403
    if jumlah < 1000:
        return jsonify({"status": "error", "message": "Minimal top-up Rp 1.000"}), 400

    try:
        saldo_baru, trx = db.add_balance_topup(nama, jumlah)
    except PaymentError as e:
        return jsonify({"status": "error", "message": e.message}), e.status_code

    return jsonify({
        "status": "sukses",
        "nama": nama, "jumlah": jumlah, "saldo_baru": saldo_baru,
        "message": (f"Top-up Rp{jumlah:,} berhasil. Saldo baru: Rp{saldo_baru:,.0f}").replace(",", "."),
    })

# ----------------------------------------------------------------
# API — Registrasi
# ----------------------------------------------------------------
@app.route("/start_register", methods=["POST"])
def start_register():
    data = request.get_json(silent=True) or {}
    nama = (data.get("nama") or "").strip()
    try:
        saldo_awal = int(data.get("saldo_awal", 100000))
    except (TypeError, ValueError):
        saldo_awal = 100000

    if not nama:
        return jsonify({"error": "Nama tidak boleh kosong"}), 400

    safe_nama = "".join(c for c in nama if c.isalnum() or c in ("_", "-", " ")).strip().replace(" ", "_")
    if not safe_nama:
        return jsonify({"error": "Nama tidak valid"}), 400

    if db.get_active_user_id(safe_nama) is not None:
        return jsonify({"error": f"Akun '{safe_nama}' masih aktif. Hapus/nonaktifkan akun tersebut sebelum mendaftar ulang."}), 409
    with verifier_lock:
        if verifier.has_person(safe_nama):
            return jsonify({"error": f"Template biometric '{safe_nama}' sudah ada. Jangan menimpa template yang ada."}), 409

    with registration_lock:
        if registration_state["running"]:
            return jsonify({"error": "Masih ada sesi registrasi yang berjalan"}), 409
        # Set sebelum thread dibuat agar dua request berurutan tidak dapat
        # sama-sama memulai enrollment pada verifier/file yang sama.
        registration_state.update(running=True, nama=safe_nama, count=0,
                                  total=REG_TOTAL_FRAMES, message="Menyiapkan registrasi...")

    def worker():
        with registration_lock:
            registration_state.update(running=True, nama=safe_nama, count=0,
                                       message="Mengambil sampel...")
        try:
            frames = []
            for i in range(1, REG_TOTAL_FRAMES + 1):
                frames.append(capture_frame_bgr())
                with registration_lock:
                    registration_state["count"] = i
                time.sleep(REG_DELAY)

            with verifier_lock:
                embedding_vector = verifier.register_new_person(safe_nama, frames)
            try:
                db.seed_account(safe_nama, saldo_awal=saldo_awal, embedding_vector=embedding_vector)
            except Exception:
                # Kalau pembuatan akun di database gagal (mis. nama duplikat),
                # embedding yang sudah terlanjur tersimpan di
                # reference_embeddings.npz dibatalkan lagi supaya tidak ada
                # orang yang bisa diverifikasi tapi tidak punya akun.
                with verifier_lock:
                    verifier.delete_person(safe_nama)
                raise

            with registration_lock:
                registration_state.update(
                    running=False,
                    message=(f"'{safe_nama}' terdaftar! Saldo awal: "
                              f"Rp{saldo_awal:,}".replace(",", "."))
                )
        except Exception as e:
            # PENTING: apapun yang gagal di atas, registration_state harus
            # selalu direset ke running=False -- kalau tidak, sesi registrasi
            # berikutnya akan selalu ditolak dengan error 409 sampai server
            # di-restart manual.
            with registration_lock:
                registration_state.update(
                    running=False,
                    message=f"Registrasi '{safe_nama}' gagal: {e}",
                )

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"status": "started", "nama": safe_nama})


@app.route("/register_status")
def register_status():
    with registration_lock:
        return jsonify(dict(registration_state))


@app.route("/delete_person", methods=["POST"])
def delete_person():
    data = request.get_json(silent=True) or {}
    nama = (data.get("nama") or "").strip()
    if not nama:
        return jsonify({"error": "Nama tidak boleh kosong"}), 400

    # Database lebih dulu dinonaktifkan agar transaksi audit tidak hilang.
    # Jika file embedding gagal ditulis, perubahan DB dikompensasi lagi.
    try:
        deleted = db.deactivate_account(nama)
    except Exception as e:
        return jsonify({"error": f"Gagal menonaktifkan akun di database: {e}"}), 409
    if not deleted:
        return jsonify({"error": f"Akun '{nama}' tidak ditemukan atau sudah nonaktif."}), 404

    try:
        with verifier_lock:
            verifier.delete_person(nama)
    except Exception as e:
        db.reactivate_account(nama)
        return jsonify({"error": f"Gagal menghapus template biometric; akun dipulihkan: {e}"}), 500

    return jsonify({"status": "ok", "message": f"'{nama}' dinonaktifkan. Riwayat transaksi tetap disimpan."})
# ----------------------------------------------------------------
# API — Lainnya
# ----------------------------------------------------------------
@app.route("/balance/<nama>")
def get_balance_user(nama):
    saldo = db.get_balance(nama)
    if saldo is None:
        return jsonify({"error": "Akun tidak ditemukan"}), 404
    return jsonify({"nama": nama, "saldo": saldo})


@app.route("/riwayat")
def riwayat():
    return jsonify(db.get_recent_transactions(limit=50))

@app.route("/akun")
def akun():
    return jsonify(db.list_accounts())

@app.route("/merchants", methods=["GET", "POST"])
def merchants():
    """Daftar dan tambah UMKM yang tersedia pada terminal pembayaran."""
    if request.method == "POST":
        try:
            merchant = db.create_merchant((request.get_json(silent=True) or {}).get("nama_merchant"))
        except PaymentError as exc:
            return jsonify({"status": "error", "message": exc.message}), exc.status_code
        return jsonify({"status": "sukses", "merchant": merchant}), 201
    return jsonify(db.list_merchants())

@app.route("/merchant_saldo")
def merchant_saldo():
    """Daftar merchant + saldo (derived) untuk halaman /merchant."""
    return jsonify(db.list_merchants_with_balance())

@app.route("/debug_scan")
def debug_scan():
    import numpy as np
    frame_bgr = capture_frame_bgr()
    with verifier_lock:
        if not verifier.names:
            return jsonify({"threshold_aktif": verifier.threshold, "kandidat_terdekat": None, "semua_jarak": []})
        embedding = verifier.get_embedding(frame_bgr)
        distances = np.linalg.norm(verifier.vectors - embedding, axis=1)
    hasil = sorted([
        {"nama": str(verifier.names[i]), "jarak": round(float(distances[i]), 4),
         "cocok": float(distances[i]) <= verifier.threshold}
        for i in range(len(verifier.names))
    ], key=lambda x: x["jarak"])
    return jsonify({"threshold_aktif": verifier.threshold, "kandidat_terdekat": hasil[0], "semua_jarak": hasil})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, threaded=True)
