# Simulasi Sistem Pembayaran Palm Vein

Simulasi alur transaksi end-to-end yang mengintegrasikan model Siamese
Network (hasil proyek `palm_vein_models`) ke dalam sistem pembayaran
berbasis verifikasi telapak tangan.

> ⚠️ **Ini SIMULASI untuk keperluan skripsi/demo, BUKAN sistem pembayaran
> produksi.** Saldo & akun adalah data dummy PostgreSQL, tidak
> terhubung ke sistem keuangan sungguhan apa pun. Belum ada liveness
> detection maupun mekanisme verifikasi cadangan (PIN) -- ini langkah
> lanjutan yang sudah direncanakan tapi belum dikerjakan (lihat bagian
> "Langkah selanjutnya" di bawah).

---

## 1. Arsitektur & alur transaksi

```
[Live Camera] -> [Capture frame] -> [Enhance: CLAHE+sharpen]
       -> [Embedding Network (.tflite)] -> [Cocokkan ke reference_embeddings.npz]
       -> jarak <= threshold?
             |--- TIDAK -> transaksi gagal (dicatat di log)
             |--- YA -> cek saldo di PostgreSQL
                          |--- saldo cukup -> potong saldo, transaksi SUKSES
                          |--- saldo kurang -> transaksi gagal (dicatat di log)
```

Setiap percobaan biometric -- diterima maupun ditolak -- dicatat ke tabel
`biometric_attempts`. Mutasi saldo yang berhasil dicatat ke `transactions`.
Log ini dipakai untuk menghitung FAR/FRR dari penggunaan nyata.

## 2. Struktur folder

```
palm_payment/
├── app.py              # Flask app utama (live stream + alur transaksi + registrasi)
├── verify.py            # Wrapper model embedding (.tflite) + pencocokan + registrasi orang baru
├── database.py          # Helper SQLite (akun & riwayat transaksi)
├── seed_accounts.py      # Script isi saldo awal tiap akun terdaftar (dataset awal)
├── templates/
│   ├── index.html        # UI pembayaran (live stream, input nominal, riwayat)
│   └── register.html     # UI registrasi orang baru
├── model/                # <- taruh embedding_network.tflite & reference_embeddings.npz di sini
└── payment.db            # dibuat otomatis saat pertama jalan
```

## 3. Setup

**a. Pindahkan model hasil training** dari proyek `palm_vein_models`
(yang dijalankan di laptop/PC) ke folder `model/` di proyek ini:

```bash
cp /path/ke/palm_vein_models/model_output/embedding_network.tflite ./model/
cp /path/ke/palm_vein_models/model_output/reference_embeddings.npz ./model/
```

Kalau proyek ini dijalankan di Raspberry Pi, pindahkan dulu lewat `scp`:
```bash
scp model_output/embedding_network.tflite pi@<ip-raspi>:/home/pi/palm_payment/model/
scp model_output/reference_embeddings.npz pi@<ip-raspi>:/home/pi/palm_payment/model/
```

**b. Install dependency** (di Raspberry Pi, sama seperti proyek `palm_capture`):
```bash
sudo apt install -y python3-picamera2 python3-opencv python3-flask
pip3 install tflite-runtime --break-system-packages
```

**c. Siapkan PostgreSQL.** Untuk instalasi baru jalankan
`migration_simplified_schema_new.sql`. Untuk database yang sudah memakai
skema tersebut, jalankan `migration_hardening.sql`. Isi `.env` dengan
`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, dan `DB_PASSWORD`.

**d. Jalankan aplikasi:**
```bash
python3 app.py
```

Buka `http://<ip-raspi>:5001` di browser. Pada Raspberry Pi 3B + NoIR v2,
aplikasi memakai kamera 640x480/20 FPS untuk menjaga respons UI dan inferensi.

## 4. Cara pakai

1. Isi nominal pembayaran (contoh: 25000)
2. Klik **"Scan & Verifikasi"**
3. Letakkan telapak tangan di depan kamera
4. Hasil akan muncul:
   - ✅ **Sukses** -- saldo terpotong, ditampilkan saldo baru
   - ⚠️ **Saldo tidak cukup** -- orang dikenali, tapi saldo kurang
   - ❌ **Verifikasi gagal** -- telapak tangan tidak cocok dengan siapa pun
     di atas threshold

Semua percobaan masuk ke **Riwayat Transaksi** di bawahnya.

## 5. Registrasi orang baru (mis. diri Anda sendiri, di luar dataset penelitian)

Karena dataset penelitian diambil dari 30 mahasiswa, Anda butuh cara untuk
menambahkan diri sendiri (atau siapa pun) sebagai akun uji coba tambahan.
Buka `http://<ip-raspi>:5001/register`:

1. Isi nama dan saldo awal
2. Klik **"Mulai Registrasi"**
3. Letakkan telapak tangan di depan kamera -- sistem otomatis mengambil
   15 sampel berturut-turut (jeda 0.4 detik) untuk dihitung jadi satu
   embedding referensi
4. Setelah selesai, akun otomatis dibuat dengan saldo awal yang diisi, dan
   langsung bisa dipakai untuk mencoba `/verify_payment`

**Kenapa ini tidak perlu training ulang model**: ini memanfaatkan sifat
dasar Siamese Network/embedding-based verification yang sudah dibahas di
proyek `palm_vein_models` -- enrollment orang baru cukup dengan menghitung
embedding-nya lewat model yang sudah ada (`embedding_network.tflite`), lalu
menambahkannya ke `reference_embeddings.npz`. Proses ini langsung mengubah
file `.npz` di folder `model/`.

> Catatan: 15 sampel di sini lebih sedikit dari 30 foto per orang di
> dataset penelitian utama (`palm_capture`). Ini cukup untuk menghitung
> satu embedding referensi yang representatif, tapi kalau Anda ingin data
> yang lebih konsisten kualitasnya (dengan estimasi visibilitas vena
> seperti di `palm_capture`), Anda tetap bisa pakai aplikasi `palm_capture`
> untuk mengambil set foto lengkap, lalu hitung embedding-nya manual lewat
> `tambah_orang_baru()` di `inference_siamese.py` (proyek `palm_vein_models`).

## 6. Threshold yang dipakai

Default `0.2037` di `verify.py` -- ini operating point **FAR~1%** hasil
`evaluate_siamese.py` di proyek `palm_vein_models`, dipilih karena untuk
konteks pembayaran, risiko salah menerima orang lain (FAR) jauh lebih
berisiko secara finansial dibanding risiko menolak orang yang sah (FRR).
Lihat README `palm_vein_models` untuk tabel lengkap trade-off FAR vs FRR.

## 7. Keterbatasan yang harus disebutkan di skripsi

- **Belum ada liveness detection** -- sistem belum bisa memastikan yang
  di-scan adalah tangan asli (bukan foto/replay).
- **Belum ada verifikasi cadangan (PIN)** -- kalau verifikasi gagal,
  pengguna saat ini hanya bisa mencoba scan ulang.
- **Saldo & akun adalah data dummy** -- tidak ada keamanan tingkat
  produksi (enkripsi data, autentikasi API, dst).
- **FRR ~30% pada threshold ini** (lihat evaluasi `palm_vein_models`) --
  cukup sering menolak orang yang sah; di sistem nyata biasanya
  dikompensasi dengan mekanisme percobaan ulang atau verifikasi cadangan.

## 8. Langkah selanjutnya (belum dikerjakan)

- Mekanisme verifikasi cadangan (PIN) saat verifikasi gagal
- Liveness detection (analisis multi-frame untuk anti-spoofing)
- Dokumentasi desain sistem untuk bab skripsi

Beri tahu kalau ingin lanjut ke salah satu bagian ini.
