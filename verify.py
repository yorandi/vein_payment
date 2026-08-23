"""
verify.py
-----------
Modul verifikasi palm vein untuk sistem pembayaran. Memuat embedding network
(.tflite) dan reference_embeddings.npz hasil training siamese_network.py
(dari proyek palm_vein_models), lalu menyediakan fungsi untuk menghitung
embedding dari frame kamera dan mencocokkannya dengan database referensi.
"""

import os
import numpy as np
import cv2

try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    from tensorflow.lite.python import interpreter as tflite

IMG_SIZE = (128, 128)


class PalmVeinVerifier:
    def __init__(self, model_dir, threshold=0.3):
        """
        threshold default 0.2037 = operating point FAR~1% dari evaluate_siamese.py
        (lihat README palm_vein_models). Sesuaikan kalau Anda evaluasi ulang
        dengan dataset yang berbeda.
        """
        self.threshold = threshold
        self.reference_path = os.path.join(model_dir, "reference_embeddings.npz")

        self.interpreter = tflite.Interpreter(
            model_path=os.path.join(model_dir, "embedding_network.tflite")
        )
        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()

        data = np.load(self.reference_path, allow_pickle=True)
        self.names = list(data["names"])
        self.vectors = np.array(data["vectors"])

    def enhance(self, gray):
        """CLAHE + sharpening -- sama seperti enhancement di palm_capture."""
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        blur = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=3)
        return cv2.addWeighted(enhanced, 1.5, blur, -0.5, 0)

    def preprocess(self, frame_bgr):
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        enhanced = self.enhance(gray)
        resized = cv2.resize(enhanced, IMG_SIZE)
        img = resized.astype("float32") / 255.0
        return img[np.newaxis, ..., np.newaxis]

    def get_embedding(self, frame_bgr):
        img = self.preprocess(frame_bgr)
        self.interpreter.set_tensor(self.input_details[0]["index"], img)
        self.interpreter.invoke()
        return self.interpreter.get_tensor(self.output_details[0]["index"])[0]

    def identify(self, frame_bgr):
        """
        Mengidentifikasi dari satu frame tunggal.
        Untuk sistem pembayaran, gunakan identify_multiframe() agar lebih akurat.
        """
        embedding = self.get_embedding(frame_bgr)
        distances = np.linalg.norm(self.vectors - embedding, axis=1)
        idx = int(np.argmin(distances))
        jarak = float(distances[idx])
        return {
            "nama": str(self.names[idx]),
            "jarak": jarak,
            "cocok": jarak <= self.threshold,
        }

    def identify_multiframe(self, frames_bgr, strategy="embedding_average", min_margin=0.02):
        """
        Mengidentifikasi dari beberapa frame sekaligus dengan agregasi.

        Strategi yang tersedia:
        - "embedding_average"  : rata-ratakan embedding semua frame dulu, baru
                                 cari kandidat terdekat ke embedding gabungan.
                                 Paling stabil -- noise antar frame saling
                                 menghilangkan. DIREKOMENDASIKAN untuk produksi.
        - "majority_vote"      : tiap frame voting ke kandidat terdekat, pemenang
                                 suara terbanyak dinyatakan cocok.
        - "average_distance"   : rata-ratakan jarak per kandidat lintas frame.
        - "min_distance"       : ambil jarak terkecil dari semua frame.

        min_margin: selisih minimum jarak antara kandidat terbaik dan kedua.
                    Kalau selisihnya di bawah min_margin, sistem menolak
                    daripada berisiko salah tebak (terlalu mirip dua kandidat).
                    Set ke 0.0 untuk nonaktifkan.
        """
        if len(frames_bgr) == 0:
            raise ValueError("Tidak ada frame yang diberikan.")

        # hitung embedding semua frame
        embeddings = np.array([
            self.get_embedding(frame) for frame in frames_bgr
        ])  # shape: (n_frames, embedding_dim)

        # detail per frame untuk keperluan logging/UI
        all_distances = np.array([
            np.linalg.norm(self.vectors - emb, axis=1)
            for emb in embeddings
        ])  # shape: (n_frames, n_candidates)

        detail_per_frame = []
        for i, dists in enumerate(all_distances):
            best_idx = int(np.argmin(dists))
            detail_per_frame.append({
                "frame": i + 1,
                "kandidat": str(self.names[best_idx]),
                "jarak": round(float(dists[best_idx]), 4),
                "cocok_frame": float(dists[best_idx]) <= self.threshold,
            })

        # ----------------------------------------------------------------
        # Pilih strategi agregasi
        # ----------------------------------------------------------------
        if strategy == "embedding_average":
            # rata-rata semua embedding jadi satu vektor gabungan
            avg_embedding = embeddings.mean(axis=0)
            # L2 normalize ulang hasil rata-rata supaya skala tetap konsisten
            norm = np.linalg.norm(avg_embedding)
            if norm > 0:
                avg_embedding = avg_embedding / norm
            final_distances = np.linalg.norm(self.vectors - avg_embedding, axis=1)

        elif strategy == "average_distance":
            final_distances = all_distances.mean(axis=0)

        elif strategy == "min_distance":
            final_distances = all_distances.min(axis=0)

        elif strategy == "majority_vote":
            votes = {}
            for dists in all_distances:
                best_idx = int(np.argmin(dists))
                if float(dists[best_idx]) <= self.threshold:
                    nama_kandidat = str(self.names[best_idx])
                    votes[nama_kandidat] = votes.get(nama_kandidat, 0) + 1

            if not votes:
                best_idx = int(np.argmin(all_distances.mean(axis=0)))
                return {
                    "nama": str(self.names[best_idx]),
                    "jarak_final": round(float(all_distances.mean(axis=0)[best_idx]), 4),
                    "cocok": False,
                    "margin": None,
                    "detail_per_frame": detail_per_frame,
                    "strategy": strategy,
                    "alasan_tolak": "tidak ada frame yang cocok",
                }
            pemenang = max(votes, key=votes.get)
            pemenang_idx = self.names.index(pemenang)
            final_distances = all_distances.mean(axis=0)
            # paksa pemenang voting jadi kandidat utama
            final_distances_copy = final_distances.copy()
            final_distances_copy[pemenang_idx] = -1  # jamin jadi terkecil
            best_idx = pemenang_idx
            jarak_final = round(float(all_distances[:, pemenang_idx].mean()), 4)
            sorted_dists = np.sort(final_distances)
            margin = round(float(sorted_dists[1] - sorted_dists[0]), 4) if len(sorted_dists) > 1 else 1.0
            cocok = jarak_final <= self.threshold
            result = {
                "nama": pemenang,
                "jarak_final": jarak_final,
                "cocok": cocok,
                "margin": margin,
                "votes": votes,
                "votes_menang": votes[pemenang],
                "total_frames": len(frames_bgr),
                "detail_per_frame": detail_per_frame,
                "strategy": strategy,
            }
            # Guard yang sama: kalau cuma 1 orang terdaftar, margin tidak
            # relevan (tidak ada kandidat kedua untuk dibandingkan).
            if len(self.names) > 1 and cocok and margin < min_margin:
                result["cocok"] = False
                result["alasan_tolak"] = (
                    f"margin terlalu sempit ({margin:.4f} < {min_margin}) "
                    f"-- terlalu mirip dengan kandidat lain, ditolak demi keamanan"
                )
            return result
        else:
            raise ValueError(f"Strategi tidak dikenal: {strategy}")

        # ----------------------------------------------------------------
        # Evaluasi hasil (untuk semua strategi kecuali majority_vote)
        # ----------------------------------------------------------------
        sorted_idx = np.argsort(final_distances)
        best_idx   = int(sorted_idx[0])
        second_idx = int(sorted_idx[1]) if len(sorted_idx) > 1 else best_idx

        jarak_final  = round(float(final_distances[best_idx]), 4)
        jarak_kedua  = round(float(final_distances[second_idx]), 4)
        margin       = round(jarak_kedua - jarak_final, 4)

        cocok = jarak_final <= self.threshold
        alasan_tolak = None

        # Kalau kandidat yang terdaftar cuma 1 orang, tidak ada "kandidat
        # kedua" untuk dibandingkan -- best_idx == second_idx sehingga
        # margin selalu 0 dan match valid akan salah ditolak. Skip margin
        # check dalam kasus ini (sama seperti guard di identify()).
        if len(self.names) > 1 and cocok and margin < min_margin:
            cocok = False
            alasan_tolak = (
                f"margin terlalu sempit ({margin:.4f} < {min_margin}) "
                f"-- '{self.names[best_idx]}' ({jarak_final}) terlalu mirip "
                f"dengan '{self.names[second_idx]}' ({jarak_kedua})"
            )

        result = {
            "nama": str(self.names[best_idx]),
            "jarak_final": jarak_final,
            "jarak_kandidat_kedua": jarak_kedua,
            "margin": margin,
            "cocok": cocok,
            "detail_per_frame": detail_per_frame,
            "strategy": strategy,
        }
        if alasan_tolak:
            result["alasan_tolak"] = alasan_tolak
        return result

    def register_new_person(self, nama, frames_bgr):
        """
        Menambahkan orang baru (atau memperbarui embedding orang yang sudah
        ada) ke reference_embeddings.npz berdasarkan beberapa frame contoh
        telapak tangan -- TANPA training ulang model embedding.

        Ini memanfaatkan keunggulan utama Siamese Network/embedding-based
        verification: enrollment orang baru cukup dengan menghitung
        embedding-nya lewat model yang sudah ada, lalu menyimpannya sebagai
        referensi baru.
        """
        embeddings = [self.get_embedding(f) for f in frames_bgr]
        new_vector = np.mean(embeddings, axis=0)

        if nama in self.names:
            idx = self.names.index(nama)
            self.vectors[idx] = new_vector
        else:
            self.names.append(nama)
            self.vectors = np.vstack([self.vectors, new_vector[np.newaxis, :]])

        self._save_reference()
        return new_vector

    def delete_person(self, nama):
        """
        Menghapus embedding referensi seseorang dari memori dan file .npz.
        Mengembalikan True kalau berhasil ditemukan dan dihapus, False kalau
        nama tidak ditemukan.
        """
        if nama not in self.names:
            return False

        idx = self.names.index(nama)
        self.names.pop(idx)
        self.vectors = np.delete(self.vectors, idx, axis=0)
        self._save_reference()
        return True

    def _save_reference(self):
        np.savez(self.reference_path, names=np.array(self.names), vectors=self.vectors)
