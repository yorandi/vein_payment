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

from verify import PalmVeinVerifier
import database as db

app = Flask(__name__)

MODEL_DIR  = "./model"
THRESHOLD  = 0.30
SCAN_FRAMES = 5
SCAN_DELAY  = 0.3
AGGREGATION = "embedding_average"
MIN_MARGIN  = 0.02
STREAM_SIZE = (640, 360)
REG_TOTAL_FRAMES = 30
REG_DELAY = 0.5

db.init_db()
verifier = PalmVeinVerifier(MODEL_DIR, threshold=THRESHOLD)

picam2 = Picamera2()
video_config = picam2.create_video_configuration(main={"size": (1280, 720), "format": "RGB888"})
picam2.configure(video_config)
picam2.start()
time.sleep(1)

camera_lock = threading.Lock()

registration_state = {
    "running": False, "nama": "", "count": 0,
    "total": REG_TOTAL_FRAMES, "message": "Siap.",
}
registration_lock = threading.Lock()


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

    frames = capture_multiframe()
    result = verifier.identify_multiframe(frames, strategy=AGGREGATION, min_margin=MIN_MARGIN)
    nama  = result["nama"]
    jarak = result["jarak_final"]
    cocok = result["cocok"]

    if not cocok:
        db.log_transaction(nama, jumlah, None, "verifikasi_gagal", jarak)
        return jsonify({
            "status": "gagal_verifikasi",
            "message": f"Telapak tangan tidak dikenali ({AGGREGATION}, {SCAN_FRAMES} frame).",
            "jarak_final": jarak,
            "margin": result.get("margin"),
            "alasan_tolak": result.get("alasan_tolak"),
            "detail_per_frame": result.get("detail_per_frame", []),
        })

    saldo = db.get_balance(nama)
    if saldo is None:
        db.log_transaction(nama, jumlah, None, "akun_tidak_ditemukan", jarak)
        return jsonify({"status": "error", "message": f"Akun '{nama}' tidak ditemukan."}), 404

    if saldo < jumlah:
        db.log_transaction(nama, jumlah, saldo, "saldo_tidak_cukup", jarak)
        return jsonify({
            "status": "saldo_tidak_cukup",
            "nama": nama, "saldo": saldo, "jumlah": jumlah,
            "jarak_final": jarak, "margin": result.get("margin"),
            "message": (f"Saldo {nama} tidak cukup "
                        f"(saldo: Rp{saldo:,}, dibutuhkan: Rp{jumlah:,})").replace(",", "."),
            "detail_per_frame": result.get("detail_per_frame", []),
        })

    saldo_baru = db.deduct_balance(nama, jumlah)
    db.log_transaction(nama, jumlah, saldo_baru, "sukses", jarak)
    return jsonify({
        "status": "sukses",
        "nama": nama, "jumlah": jumlah, "saldo_baru": saldo_baru,
        "jarak_final": jarak, "margin": result.get("margin"),
        "detail_per_frame": result.get("detail_per_frame", []),
        "message": (f"Pembayaran berhasil. Saldo {nama}: Rp{saldo_baru:,}").replace(",", "."),
    })


# ----------------------------------------------------------------
# API — Identifikasi saja (untuk halaman top-up step 1)
# ----------------------------------------------------------------
@app.route("/identify_only", methods=["POST"])
def identify_only():
    frames = capture_multiframe()
    result = verifier.identify_multiframe(frames, strategy=AGGREGATION, min_margin=MIN_MARGIN)
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
    })


# ----------------------------------------------------------------
# API — Top-up saldo
# ----------------------------------------------------------------
@app.route("/topup", methods=["POST"])
def do_topup():
    data = request.get_json(silent=True) or {}
    nama = (data.get("nama") or "").strip()
    try:
        jumlah = int(data.get("jumlah", 0))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Jumlah tidak valid"}), 400

    if not nama:
        return jsonify({"status": "error", "message": "Nama tidak boleh kosong"}), 400
    if jumlah < 1000:
        return jsonify({"status": "error", "message": "Minimal top-up Rp 1.000"}), 400

    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT saldo FROM accounts WHERE nama = %s", (nama,))
    row = cur.fetchone()
    if row is None:
        cur.close(); conn.close()
        return jsonify({"status": "error", "message": f"Akun '{nama}' tidak ditemukan."}), 404

    saldo_baru = row[0] + jumlah
    cur.execute("UPDATE accounts SET saldo = %s WHERE nama = %s", (saldo_baru, nama))
    conn.commit()
    cur.close(); conn.close()

    db.log_transaction(nama, jumlah, saldo_baru, "topup", None)
    return jsonify({
        "status": "sukses",
        "nama": nama, "jumlah": jumlah, "saldo_baru": saldo_baru,
        "message": (f"Top-up Rp{jumlah:,} berhasil. Saldo baru: Rp{saldo_baru:,}").replace(",", "."),
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

    with registration_lock:
        if registration_state["running"]:
            return jsonify({"error": "Masih ada sesi registrasi yang berjalan"}), 409

    def worker():
        with registration_lock:
            registration_state.update(running=True, nama=safe_nama, count=0,
                                       message="Mengambil sampel...")
        frames = []
        for i in range(1, REG_TOTAL_FRAMES + 1):
            frames.append(capture_frame_bgr())
            with registration_lock:
                registration_state["count"] = i
            time.sleep(REG_DELAY)

        verifier.register_new_person(safe_nama, frames)
        db.seed_account(safe_nama, saldo_awal=saldo_awal)

        with registration_lock:
            registration_state.update(
                running=False,
                message=(f"'{safe_nama}' terdaftar! Saldo awal: "
                          f"Rp{saldo_awal:,}".replace(",", "."))
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

    deleted = verifier.delete_person(nama)
    if not deleted:
        return jsonify({"error": f"'{nama}' tidak ditemukan di embedding referensi"}), 404

    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM accounts WHERE nama = %s", (nama,))
    conn.commit()
    cur.close(); conn.close()

    return jsonify({"status": "ok", "message": f"'{nama}' berhasil dihapus. Silakan registrasi ulang."})


# ----------------------------------------------------------------
# API — Lainnya
# ----------------------------------------------------------------
@app.route("/balance/<nama>")
def get_balance_user(nama):
    saldo = db.get_balance(nama)
    if saldo is None:
        return jsonify({"error": "Akun tidak ditemukan"}), 404
    return jsonify({"nama": nama, "saldo": saldo})


def riwayat():
    return jsonify(db.get_recent_transactions(limit=50))

@app.route("/akun")
def akun():
    return jsonify(db.list_accounts())

@app.route("/debug_scan")
def debug_scan():
    import numpy as np
    frame_bgr = capture_frame_bgr()
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
