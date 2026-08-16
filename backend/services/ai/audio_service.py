"""Adapter audio — jembatan antara payload perangkat dan ai_models.py.

Membungkus core/ai_models.AudioDistressModel tanpa mengubah isinya.

APA YANG SEBENARNYA DILAKUKAN MODEL INI
---------------------------------------
Dua jalur, sesuai implementasi asli:

1. Perangkat mengirim `class_probabilities`
   -> nilai dinormalisasi dan dipakai apa adanya
   -> source = "hardware-model-output"
   Ini jalur untuk target akhir: inferensi terjadi DI PERANGKAT.

2. Perangkat mengirim fitur ringkas (energy, peak, zero_crossing_rate,
   dominant_frequency, duration_ms)
   -> probabilitas dihitung dari pembobotan manual + softmax
   -> source = "feature-fallback"
   Ini BUKAN AI hasil pelatihan. Ini heuristik deterministik.

Tidak ada jalur yang menerima WAV/PCM mentah, karena ai_models.py memang
tidak memilikinya. Tidak ada format yang dikarang di sini.

KELAS AUDIO (dari AUDIO_CLASSES pada file asli):
    Normal, Scream/Teriakan, Help/Distress, Impact/Benturan

Output utama:
    audio_distress_probability = 1 - P(Normal)

CATATAN PENTING SOAL PENAMAAN
-----------------------------
`audio_confidence` yang dikirim ESP32 pada payload emergency TIDAK otomatis
sama dengan `audio_distress_probability`. Yang pertama adalah keyakinan
perangkat terhadap kelas yang ia pilih; yang kedua adalah peluang kejadian
ini bukan suara normal. Keduanya disimpan terpisah agar tidak tertukar.
"""

from backend.services.ai.core.ai_models import AUDIO_CLASSES, AudioDistressModel

# Satu instance cukup: model ini stateless.
_model = AudioDistressModel()

# Kelas yang dianggap menandakan keadaan darurat (selain "Normal").
DISTRESS_CLASSES = tuple(label for label in AUDIO_CLASSES if label != "Normal")


def available_classes() -> list[str]:
    """Daftar kelas audio yang dikenal model."""
    return list(AUDIO_CLASSES)


def model_info() -> dict:
    """Informasi model audio untuk /api/health.

    Menyebut jenis implementasi secara jujur, bukan mengklaimnya sebagai CNN.
    """
    return {
        "model": _model.model_name,
        "implementation": "feature-based adapter (pure Python), bukan CNN/TinyML",
        "classes": list(AUDIO_CLASSES),
        "accepts": [
            "class_probabilities (hasil inferensi di perangkat)",
            "fitur ringkas: energy, peak, zero_crossing_rate, "
            "dominant_frequency, duration_ms",
        ],
        "status": "OK",
    }


def analyze(features: dict | None = None) -> dict:
    """Jalankan inferensi audio.

    Parameter
    ---------
    features : dict | None
        Boleh berisi `class_probabilities` (dict label -> peluang) atau fitur
        ringkas. Bila None atau kosong, model memakai nilai default fiturnya.

    Return
    ------
    dict dengan kunci:
        ai_status                  : OK | ERROR
        audio_class                : kelas dengan peluang tertinggi
        audio_confidence           : peluang kelas tersebut (0.0-1.0)
        audio_distress_probability : 1 - P(Normal)
        is_distress                : bool, kelas teratas bukan "Normal"
        class_probabilities        : seluruh peluang per kelas
        source                     : hardware-model-output | feature-fallback
        model                      : nama model

    Tidak pernah melempar exception. Bila inferensi gagal, mengembalikan
    bentuk error terstruktur sesuai kontrak bagian 13.
    """
    try:
        hasil = _model.predict(features or {})

        peluang = hasil.get("class_probabilities", {}) or {}
        if not peluang:
            raise ValueError("Model tidak mengembalikan class_probabilities.")

        kelas_teratas = max(peluang, key=peluang.get)
        keyakinan = float(peluang[kelas_teratas])

        return {
            "ai_status": "OK",
            "audio_class": kelas_teratas,
            "audio_confidence": round(keyakinan, 6),
            "audio_distress_probability": float(
                hasil.get("audio_distress_probability", 0.0)
            ),
            "is_distress": kelas_teratas != "Normal",
            "class_probabilities": peluang,
            "source": hasil.get("source"),
            "model": hasil.get("model"),
            "assumption": hasil.get("assumption"),
        }

    except Exception as error:  # noqa: BLE001 - fail-safe, server tidak boleh mati
        # Bentuk error mengikuti kontrak pada bagian 13 prompt.
        return {
            "ai_status": "ERROR",
            "audio_class": None,
            "audio_confidence": 0,
            "audio_distress_probability": 0.0,
            "is_distress": False,
            "class_probabilities": {},
            "source": None,
            "model": getattr(_model, "model_name", None),
            "error": f"{type(error).__name__}: {error}",
        }


def distress_probability_from_payload(data: dict) -> dict:
    """Tentukan bukti audio dari payload /api/emergency/evaluate.

    Urutan prioritas:

    1. `audio_features` ada -> jalankan model audio.
    2. `audio_distress_probability` dikirim langsung -> pakai nilai itu.
    3. Tidak ada keduanya -> turunkan dari `audio_class` + `audio_confidence`
       yang dikirim perangkat, tanpa memanggil model.

    Jalur 3 penting untuk kompatibilitas: perangkat dan simulator yang sudah
    ada hanya mengirim audio_class dan audio_confidence.
    """
    fitur = data.get("audio_features")

    if isinstance(fitur, dict) and fitur:
        hasil = analyze(fitur)
        hasil["evidence_source"] = "AI_AUDIO_MODEL"
        return hasil

    langsung = data.get("audio_distress_probability")
    kelas = data.get("audio_class") or "Unknown"
    keyakinan = float(data.get("audio_confidence") or 0.0)

    if langsung is not None:
        try:
            nilai = float(langsung)
        except (TypeError, ValueError):
            nilai = 0.0
        return {
            "ai_status": "OK",
            "audio_class": kelas,
            "audio_confidence": keyakinan,
            "audio_distress_probability": max(0.0, min(1.0, nilai)),
            "is_distress": nilai > 0.5,
            "class_probabilities": {},
            "source": "device-reported",
            "model": None,
            "evidence_source": "DEVICE_REPORTED",
        }

    # Turunan dari kelas + keyakinan perangkat.
    normal = str(kelas).strip().lower() in ("normal", "none", "unknown", "")
    distress = 0.0 if normal else keyakinan

    return {
        "ai_status": "OK",
        "audio_class": kelas,
        "audio_confidence": keyakinan,
        "audio_distress_probability": round(distress, 6),
        "is_distress": not normal,
        "class_probabilities": {},
        "source": "derived-from-device-class",
        "model": None,
        "evidence_source": "DERIVED",
    }
