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
  POST /verify_payment   -> verifikasi + potong saldo
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

import config  # noqa: F401 -- pastikan .env sudah dimuat
from verify import PalmVeinVerifier
import palm_payment_db as db
from payment_routes import payment_bp, PaymentError

app = Flask(__name__)

app.register_blueprint(payment_bp, url_prefix="/api")


MODEL_DIR  = "./model"
# Nilai ini adalah operating point lama dengan FAR sekitar 1%. Jangan ubah
# tanpa evaluasi ulang menggunakan pipeline multiframe yang sama.
THRESHOLD  = 0.2037
SCAN_FRAMES = 5
SCAN_DELAY  = 0.3
AGGREGATION = "embedding_average"
MIN_MARGIN  = 0.02
STREAM_SIZE = (640, 360)
CAMERA_SIZE = (640, 480)  # cukup untuk model 128x128, lebih ringan untuk Pi 3B
REG_TOTAL_FRAMES = 30
REG_DELAY = 0.5

db.init_db()
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
            result.get("alasan_tolak"),
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
            "detail_per_frame": result.get("detail_per_frame", []),
        })

    try:
        saldo_baru, trx = db.deduct_balance_for_payment(nama, merchant_id, jumlah)
    except PaymentError as e:
        # e.status_code: 404 kalau akun/merchant tidak ditemukan,
        # 400 kalau saldo tidak cukup -- pesan lengkap ada di e.message,
        # frontend (pay.html) bisa tampilkan langsung.
        return jsonify({
            "status": "error",
            "nama": nama,
            "jumlah": jumlah,
            "saldo": db.get_balance(nama),
            "jarak_final": jarak,
            "margin": result.get("margin"),
            "message": e.message,
            "detail_per_frame": result.get("detail_per_frame", []),
        }), e.status_code

    return jsonify({
        "status": "sukses",
        "nama": nama, "jumlah": jumlah, "saldo_baru": saldo_baru,
        "jarak_final": jarak, "margin": result.get("margin"),
        "detail_per_frame": result.get("detail_per_frame", []),
        "message": (f"Pembayaran berhasil. Saldo {nama}: Rp{saldo_baru:,.0f}").replace(",", "."),
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
            "detail_per_frame": result.get("detail_per_frame", []),
        })

    if nama == target_nama:
        return jsonify({
            "status": "error",
            "nama": nama,
            "message": "Tidak bisa mengirim saldo ke akun sendiri (yang teridentifikasi dari scan sama dengan penerima yang dipilih).",
        }), 400

    try:
        saldo_baru, trx = db.transfer_balance(nama, target_nama, jumlah)
    except PaymentError as e:
        return jsonify({
            "status": "error",
            "nama": nama,
            "target_nama": target_nama,
            "jumlah": jumlah,
            "saldo": db.get_balance(nama),
            "jarak_final": jarak,
            "margin": result.get("margin"),
            "message": e.message,
            "detail_per_frame": result.get("detail_per_frame", []),
        }), e.status_code

    return jsonify({
        "status": "sukses",
        "nama": nama, "target_nama": target_nama, "jumlah": jumlah, "saldo_baru": saldo_baru,
        "jarak_final": jarak, "margin": result.get("margin"),
        "detail_per_frame": result.get("detail_per_frame", []),
        "message": (f"Transfer berhasil. Saldo {nama}: Rp{saldo_baru:,.0f}").replace(",", "."),
    })


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

    if db.get_user_id(safe_nama) is not None:
        return jsonify({"error": f"Akun '{safe_nama}' sudah ada. Hapus/nonaktifkan akun lama lewat admin sebelum mendaftar ulang."}), 409
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

@app.route("/merchants")
def merchants():
    """Daftar merchant untuk layar pemilihan sebelum bayar (pay.html)."""
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
