"""Verifikasi ASEP-JAGA.

=========================================================================
RULE-BASED SECOND-LEVEL VERIFICATION — INI BUKAN AI
=========================================================================
Seluruh keputusan CONFIRMED / FALSE_ALARM di file ini dihasilkan oleh aturan
dan pembobotan yang ditulis manual. Tidak ada model machine learning yang
mengambil keputusan di sini, tidak ada pelatihan, dan tidak ada inferensi
model untuk menentukan keputusan akhir.

Model yang ada di sistem hanya menghasilkan BUKTI (evidence):

    ai_models.AudioDistressModel      -> bukti audio (adapter feature-based,
                                         BUKAN CNN/TinyML/deep learning)
    random_forest_pipeline.pkl        -> hotspot risk (model ML sungguhan)
    Open-Meteo / TomTom               -> konteks cuaca & lalu lintas
    lighting_service                  -> konteks pencahayaan (ESTIMASI)
    tabel incidents                   -> riwayat device (data sendiri)

Seluruh bukti tersebut masuk ke skoring rule-based di bawah, dan keputusan
akhir ditentukan oleh perbandingan skor terhadap ambang batas.
=========================================================================

Dua lapisan verifikasi:

  TAHAP 1 - verify_local()
      Cermin dari logika di ESP32. Server hanya memakai ini bila ESP32
      tidak mengirim `local_decision`. Keputusan sebenarnya tetap milik
      ESP32 (fail-safe lokal: strobe tidak menunggu server).

  TAHAP 2 - verify_emergency()
      Verifikasi tingkat kedua di server, memakai hasil tahap 1 plus
      CONTEXT OBJECT dari services/context/. Menghasilkan CONFIRMED atau
      FALSE_ALARM.

Aturan yang dijaga ketat:
  - SOS saja TIDAK PERNAH cukup untuk CONFIRMED.
  - audio_confidence tinggi saja TIDAK PERNAH cukup untuk CONFIRMED.
  - hotspot High saja TIDAK PERNAH cukup untuk CONFIRMED.
  - LOCAL_REJECTED tidak bisa dinaikkan menjadi CONFIRMED oleh server.
"""

from backend.services import context as context_engine

# --- Bobot rule-based tahap 2 --------------------------------------------
# Bobot dasar; total = 1.0. Nilai dipilih manual dan BELUM diuji terhadap
# data lapangan. Ubah bila hasil pengujian menunjukkan perlu penyesuaian.
#
# Catatan penting: tidak ada satu pun komponen yang bobotnya >= ambang batas
# (default 0.70). Ini disengaja, supaya tidak ada bukti tunggal yang dapat
# memicu CONFIRMED sendirian.
WEIGHT_SOS = 0.28  # tombol SOS ditekan manusia
WEIGHT_AUDIO = 0.30  # bukti audio (kelas + keyakinan/distress)
WEIGHT_HOTSPOT = 0.14  # hotspot risk dari Random Forest
WEIGHT_HISTORY = 0.12  # riwayat device (database sendiri)
WEIGHT_ENV = 0.08  # konteks lingkungan: pencahayaan, cuaca, lalu lintas
WEIGHT_EMERGENCY_STATE = 0.08  # evidence dari core_emergency_service

# Kelas audio yang dianggap relevan untuk keadaan darurat.
#
# PENTING: daftar ini mencakup DUA kosakata sekaligus.
#   1. Kosakata ai_models.py : "Scream/Teriakan", "Help/Distress",
#                              "Impact/Benturan"
#   2. Kosakata firmware     : "SCREAM", "CRY_FOR_HELP", dll.
# Tanpa penyatuan ini, kelas dari ai_models.py akan dianggap "tidak relevan"
# dan bobot audionya dipotong setengah — salah satu ketidakcocokan senyap
# yang ditemukan saat analisis integrasi.
EMERGENCY_AUDIO_CLASSES = (
    # Kosakata ai_models.py (huruf besar)
    "SCREAM/TERIAKAN",
    "HELP/DISTRESS",
    "IMPACT/BENTURAN",
    # Kosakata firmware / simulator
    "SCREAM",
    "TERIAKAN",
    "CRY_FOR_HELP",
    "HELP",
    "DISTRESS",
    "SHOUT",
    "GLASS_BREAKING",
    "CRASH",
    "IMPACT",
    "BENTURAN",
)

# Kelas yang jelas BUKAN keadaan darurat.
NORMAL_AUDIO_CLASSES = ("NORMAL", "NONE", "SILENCE", "UNKNOWN", "")

# Kata kunci untuk pencocokan sebagian, menampung variasi penulisan kelas.
_KATA_DARURAT = (
    "SCREAM",
    "TERIAK",
    "HELP",
    "DISTRESS",
    "TOLONG",
    "SHOUT",
    "IMPACT",
    "BENTUR",
    "CRASH",
    "GLASS",
)

# Slot untuk modul verifikasi eksternal (diisi lewat register_ai_verifier()).
_ai_verifier = None


def register_ai_verifier(func) -> None:
    """Pasang fungsi verifikasi eksternal (opsional).

    Fungsi yang didaftarkan harus menerima satu argumen dict dan
    mengembalikan dict dengan kunci minimal:
        {"decision": "CONFIRMED"|"FALSE_ALARM", "score": float, "reason": str}

    Saat ini TIDAK ADA modul yang didaftarkan: verifikasi tahap 2 memakai
    rule-based di file ini. Hook dipertahankan untuk kebutuhan mendatang,
    misalnya bila tersedia model klasifikasi keputusan yang sudah dilatih
    dan diuji pada data lapangan.
    """
    global _ai_verifier
    _ai_verifier = func


def ai_verifier_active() -> bool:
    """True bila modul verifikasi eksternal sudah dipasang."""
    return _ai_verifier is not None


def is_emergency_audio_class(audio_class) -> bool:
    """True bila kelas audio termasuk indikasi keadaan darurat.

    Menerima kedua kosakata (ai_models.py dan firmware) serta variasi
    penulisannya, sehingga bukti audio tidak pernah terbuang hanya karena
    perbedaan format nama kelas.
    """
    teks = str(audio_class or "").strip().upper()
    if teks in NORMAL_AUDIO_CLASSES:
        return False
    if teks in EMERGENCY_AUDIO_CLASSES:
        return True
    return any(kata in teks for kata in _KATA_DARURAT)


# --- TAHAP 1: verifikasi lokal ------------------------------------------


def verify_local(sos: bool, audio_confidence: float, audio_class: str,
                 audio_threshold: float) -> str:
    """Tiruan logika verifikasi lokal ESP32.

    ATURAN WAJIB: SOS TIDAK BOLEH BYPASS AUDIO VERIFICATION.
    Karena itu tidak ada cabang yang mengembalikan LOCAL_VERIFIED hanya
    karena `sos` bernilai True.

    Aturan:
      - SOS + audio relevan + keyakinan >= ambang    -> LOCAL_VERIFIED
      - SOS + keyakinan sangat tinggi (>= 0.85)      -> LOCAL_VERIFIED
        (kelas mungkin salah, tetapi ada suara kuat bersamaan dengan SOS)
      - Tanpa SOS: audio relevan + keyakinan >= 0.90 -> LOCAL_VERIFIED
        (korban mungkin tidak sanggup menekan tombol)
      - Selain itu                                   -> LOCAL_REJECTED
    """
    try:
        keyakinan = float(audio_confidence or 0.0)
    except (TypeError, ValueError):
        keyakinan = 0.0

    try:
        ambang = float(audio_threshold or 0.60)
    except (TypeError, ValueError):
        ambang = 0.60

    audio_relevan = is_emergency_audio_class(audio_class)
    audio_kuat = keyakinan >= ambang

    if sos and audio_kuat and audio_relevan:
        return "LOCAL_VERIFIED"
    if sos and keyakinan >= 0.85:
        return "LOCAL_VERIFIED"
    if not sos and audio_relevan and keyakinan >= 0.90:
        return "LOCAL_VERIFIED"
    return "LOCAL_REJECTED"


# --- TAHAP 2: verifikasi server -----------------------------------------


def _ambil_ringkasan(context: dict) -> dict:
    """Ambil ringkasan datar dari CONTEXT OBJECT.

    Mendukung dua bentuk:
      - CONTEXT OBJECT baru : {"summary": {...}, "weather": {...}, ...}
      - bentuk lama         : {"hotspot_risk": ..., "weather": "RAIN", ...}
    Ini menjaga kompatibilitas dengan data dan test yang sudah ada.
    """
    if not isinstance(context, dict):
        return {}
    if isinstance(context.get("summary"), dict):
        return context["summary"]
    return context


def _score_rule_based(data: dict) -> tuple[float, list[str], dict]:
    """Hitung skor 0.0-1.0 beserta alasan dan rincian tiap komponen.

    PENANGANAN BUKTI YANG TIDAK TERSEDIA
    ------------------------------------
    Bila hotspot tidak dapat diprediksi (mis. Population_Density belum
    diisi), bobotnya TIDAK dianggap nol. Nol berarti "lokasi aman", padahal
    keadaan sebenarnya adalah "tidak diketahui". Menganggapnya nol akan
    menekan skor dan berpotensi menolak kejadian nyata.

    Yang dilakukan: bobot komponen yang tidak tersedia dikeluarkan dari
    perhitungan, lalu skor dinormalisasi terhadap total bobot yang benar-
    benar terpakai. Dengan begitu bukti yang ada tetap dinilai adil.
    """
    reasons: list[str] = []
    rincian: dict = {}

    sos = bool(data.get("sos"))
    audio_class = data.get("audio_class") or ""

    try:
        audio_confidence = float(data.get("audio_confidence") or 0.0)
    except (TypeError, ValueError):
        audio_confidence = 0.0

    distress = data.get("audio_distress_probability")
    try:
        distress = float(distress) if distress is not None else None
    except (TypeError, ValueError):
        distress = None

    ringkas = _ambil_ringkasan(data.get("context") or {})

    skor_terkumpul = 0.0
    bobot_terpakai = 0.0

    # --- Komponen SOS (selalu tersedia) ---
    bobot_terpakai += WEIGHT_SOS
    if sos:
        skor_terkumpul += WEIGHT_SOS
        reasons.append("tombol SOS aktif")
        rincian["sos"] = WEIGHT_SOS
    else:
        reasons.append("tombol SOS tidak aktif")
        rincian["sos"] = 0.0

    # --- Komponen audio (selalu tersedia) ---
    # Memakai nilai distress bila ada, karena maknanya lebih tepat:
    # peluang kejadian ini bukan suara normal.
    audio_relevan = is_emergency_audio_class(audio_class)
    dasar_audio = distress if distress is not None else audio_confidence
    dasar_audio = max(0.0, min(1.0, dasar_audio))

    komponen_audio = WEIGHT_AUDIO * dasar_audio
    if not audio_relevan:
        komponen_audio *= 0.5
        reasons.append(f"kelas audio '{audio_class or 'UNKNOWN'}' kurang relevan")
    else:
        sumber = "distress" if distress is not None else "confidence"
        reasons.append(f"audio '{audio_class}' {dasar_audio:.0%} ({sumber})")

    skor_terkumpul += komponen_audio
    bobot_terpakai += WEIGHT_AUDIO
    rincian["audio"] = round(komponen_audio, 4)

    # --- Komponen hotspot (Random Forest; mungkin tidak tersedia) ---
    hotspot_risk = ringkas.get("hotspot_risk")
    hotspot_status = str(ringkas.get("hotspot_status") or "").upper()

    if hotspot_risk is not None:
        try:
            nilai = max(0.0, min(1.0, float(hotspot_risk)))
        except (TypeError, ValueError):
            nilai = 0.0
        komponen = WEIGHT_HOTSPOT * nilai
        skor_terkumpul += komponen
        bobot_terpakai += WEIGHT_HOTSPOT
        level = ringkas.get("hotspot_level") or "-"
        reasons.append(f"hotspot {level} ({nilai:.2f}, Random Forest)")
        rincian["hotspot"] = round(komponen, 4)
    else:
        reasons.append(
            f"hotspot tidak tersedia ({hotspot_status or 'UNKNOWN'}), "
            "bobotnya dikeluarkan dari perhitungan"
        )
        rincian["hotspot"] = None

    # --- Komponen riwayat device ---
    history_score = ringkas.get("history_score")
    if history_score is not None:
        try:
            nilai = max(0.0, min(1.0, float(history_score)))
        except (TypeError, ValueError):
            nilai = 0.5
        komponen = WEIGHT_HISTORY * nilai
        skor_terkumpul += komponen
        bobot_terpakai += WEIGHT_HISTORY
        reasons.append(f"skor riwayat device {nilai:.2f}")
        rincian["history"] = round(komponen, 4)
    else:
        reasons.append("riwayat device tidak tersedia")
        rincian["history"] = None

    # --- Komponen lingkungan: pencahayaan, cuaca, lalu lintas ---
    # Alasan relevansi: gelap, hujan lebat, dan jalan lengang membuat korban
    # lebih sulit mendapat pertolongan dari orang di sekitar.
    faktor_env = []
    nilai_env = 0.0

    is_dark = ringkas.get("is_dark")
    if is_dark is not None:
        if is_dark:
            nilai_env += 0.5
            faktor_env.append("kondisi gelap")
        else:
            faktor_env.append("kondisi terang")

    cuaca = str(ringkas.get("weather") or "").upper()
    if cuaca and cuaca not in ("UNKNOWN", "NONE"):
        if cuaca in ("HEAVY RAIN", "HEAVY_RAIN", "STORM"):
            nilai_env += 0.3
            faktor_env.append("hujan lebat/badai")
        elif cuaca == "RAIN":
            nilai_env += 0.15
            faktor_env.append("hujan")

    # Kosakata TomTom: Low/Medium/High. Kosakata mock lama: QUIET/NORMAL/
    # CONGESTED. Keduanya diterima supaya data lama tetap terbaca.
    lalu_lintas = str(
        ringkas.get("traffic_level") or ringkas.get("traffic") or ""
    ).upper()
    if lalu_lintas in ("LOW", "QUIET"):
        nilai_env += 0.2
        faktor_env.append("jalan lengang")

    if faktor_env:
        nilai_env = max(0.0, min(1.0, nilai_env))
        komponen = WEIGHT_ENV * nilai_env
        skor_terkumpul += komponen
        bobot_terpakai += WEIGHT_ENV
        reasons.append("lingkungan: " + ", ".join(faktor_env))
        rincian["environment"] = round(komponen, 4)
    else:
        reasons.append("konteks lingkungan tidak tersedia")
        rincian["environment"] = None

    # --- Komponen evidence emergency_state (dari file pengguna) ---
    dukungan = data.get("emergency_state_support")
    if dukungan is not None:
        try:
            nilai = max(0.0, min(1.0, float(dukungan)))
        except (TypeError, ValueError):
            nilai = 0.0
        komponen = WEIGHT_EMERGENCY_STATE * nilai
        skor_terkumpul += komponen
        bobot_terpakai += WEIGHT_EMERGENCY_STATE
        state = data.get("emergency_state") or "-"
        reasons.append(f"emergency_state={state} (evidence)")
        rincian["emergency_state"] = round(komponen, 4)
    else:
        rincian["emergency_state"] = None

    # --- Normalisasi terhadap bobot yang benar-benar terpakai ---
    if bobot_terpakai <= 0:
        return 0.0, reasons + ["tidak ada bukti yang dapat dinilai"], rincian

    skor = skor_terkumpul / bobot_terpakai

    rincian["weight_used"] = round(bobot_terpakai, 4)
    rincian["raw_score"] = round(skor_terkumpul, 4)
    rincian["normalized"] = round(skor, 4)

    if bobot_terpakai < 0.999:
        reasons.append(
            f"skor dinormalisasi terhadap bobot tersedia {bobot_terpakai:.2f}"
        )

    return round(min(skor, 1.0), 3), reasons, rincian


def verify_emergency(data: dict) -> dict:
    """RULE-BASED SECOND-LEVEL VERIFICATION.

    Parameter `data` diharapkan berisi:
        device_id, sos, audio_confidence, audio_class,
        audio_distress_probability (opsional), local_decision,
        context (CONTEXT OBJECT dari services/context/),
        emergency_state / emergency_state_support (opsional),
        threshold (opsional)

    Return:
        {"decision": str, "score": float, "reason": str, "method": str,
         "components": dict}
    """
    try:
        threshold = float(data.get("threshold", 0.70))
    except (TypeError, ValueError):
        threshold = 0.70

    local_decision = str(data.get("local_decision") or "").upper()

    # Verifikasi tahap 2 hanya boleh MEMPERKETAT, bukan melonggarkan.
    # Bila perangkat sendiri menolak, server tidak menaikkannya.
    if local_decision == "LOCAL_REJECTED":
        return {
            "decision": "FALSE_ALARM",
            "score": 0.0,
            "reason": (
                "Verifikasi lokal di perangkat menolak kejadian "
                "(LOCAL_REJECTED). Server tidak menaikkan keputusan tahap 1."
            ),
            "method": "RULE_BASED_SECOND_LEVEL",
            "components": {},
        }

    score, reasons, rincian = _score_rule_based(data)
    decision = "CONFIRMED" if score >= threshold else "FALSE_ALARM"

    reason = (
        f"Skor {score:.2f} {'>=' if decision == 'CONFIRMED' else '<'} "
        f"ambang {threshold:.2f}. Faktor: " + "; ".join(reasons) + "."
    )

    return {
        "decision": decision,
        "score": score,
        "reason": reason,
        "method": "RULE_BASED_SECOND_LEVEL",
        "components": rincian,
    }


def run_verification(data: dict) -> dict:
    """Titik masuk tunggal yang dipakai incident_service.

    Memakai modul eksternal bila didaftarkan lewat register_ai_verifier();
    jika tidak, memakai verify_emergency() yang rule-based. Bila modul
    eksternal gagal, sistem jatuh kembali ke rule-based supaya emergency
    tetap terproses.
    """
    if _ai_verifier is not None:
        try:
            result = _ai_verifier(data)
            decision = str(result.get("decision", "")).upper()
            if decision not in ("CONFIRMED", "FALSE_ALARM"):
                raise ValueError(f"decision tidak dikenal: {decision!r}")
            return {
                "decision": decision,
                "score": float(result.get("score", 0.0)),
                "reason": str(result.get("reason", "")),
                "method": str(result.get("method", "EXTERNAL_MODULE")),
                "components": result.get("components", {}),
            }
        except Exception as error:  # noqa: BLE001 - fail-safe
            fallback = verify_emergency(data)
            fallback["reason"] = (
                f"Modul verifikasi eksternal gagal ({error}); "
                "memakai verifikasi rule-based. " + fallback["reason"]
            )
            fallback["method"] = "RULE_BASED_FALLBACK"
            return fallback

    return verify_emergency(data)


def collect_context(device_id: str, latitude=None, longitude=None) -> dict:
    """Pintasan ke context engine supaya incident_service cukup mengimpor
    satu modul. Menghasilkan CONTEXT OBJECT lengkap.
    """
    return context_engine.build_context(device_id, latitude, longitude)
