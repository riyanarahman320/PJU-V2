"""Konfigurasi aplikasi ASEP-JAGA.

Semua nilai dibaca dari environment (.env). Jika .env belum ada,
dipakai default yang aman supaya server tetap bisa dijalankan.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Folder backend/ dan root project
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DATA_DIR = BASE_DIR / "data"

# Muat .env dari root project (kalau ada)
load_dotenv(PROJECT_ROOT / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _database_uri() -> str:
    """Bangun URI database.

    DATABASE_URL boleh berisi path relatif (sqlite:///data/asepjaga.db).
    Path relatif diubah menjadi absolut supaya lokasi file .db tidak
    berubah-ubah tergantung dari folder mana Flask dijalankan.
    """
    url = os.getenv("DATABASE_URL", "sqlite:///data/asepjaga.db").strip()
    prefix = "sqlite:///"
    if url.startswith(prefix):
        raw_path = url[len(prefix):]
        path = Path(raw_path)
        if not path.is_absolute():
            path = (BASE_DIR / path).resolve()
        return prefix + path.as_posix()
    return url


class Config:
    """Konfigurasi dasar (dipakai untuk development)."""

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-ganti-di-produksi")
    DEVICE_API_KEY = os.getenv("DEVICE_API_KEY", "dev-device-api-key")

    # Kunci operator untuk PUT /api/device/<id>/config.
    # SENGAJA tanpa nilai default: endpoint konfigurasi mengubah data yang
    # memengaruhi prediksi hotspot, jadi kunci kosong harus berarti endpoint
    # tertutup (HTTP 500), bukan terbuka tanpa autentikasi.
    DEVICE_CONFIG_API_KEY = os.getenv("DEVICE_CONFIG_API_KEY", "").strip()

    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    HOST = os.getenv("FLASK_HOST", "0.0.0.0")
    PORT = _env_int("FLASK_PORT", 5000)
    DEBUG = _env_bool("FLASK_DEBUG", True)

    # Device dianggap OFFLINE jika tidak ada heartbeat selama N detik.
    DEVICE_OFFLINE_TIMEOUT = _env_int("DEVICE_OFFLINE_TIMEOUT", 60)

    # Ambang batas verifikasi tahap-2 (rule-based, lihat services/verification.py)
    SERVER_CONFIRM_THRESHOLD = _env_float("SERVER_CONFIRM_THRESHOLD", 0.70)
    AUDIO_CONFIDENCE_MIN = _env_float("AUDIO_CONFIDENCE_MIN", 0.60)

    # --- AI & model -----------------------------------------------------
    # AI_MODE:
    #   real -> memakai model audio (services/ai/core/ai_models.py) dan
    #           random_forest_pipeline.pkl
    #   mock -> hanya untuk testing; model tidak dipanggil
    AI_MODE = os.getenv("AI_MODE", "real").strip().lower()

    # Lokasi random_forest_pipeline.pkl.
    # Default: backend/models_store/random_forest_pipeline.pkl
    # File ini ~79 MB dan tidak di-commit ke Git (lihat .gitignore + README).
    RF_MODEL_PATH = os.getenv(
        "RF_MODEL_PATH",
        str(BASE_DIR / "models_store" / "random_forest_pipeline.pkl"),
    )

    # Muat model saat startup agar kesalahan konfigurasi terlihat lebih awal.
    # Bila False, model dimuat saat pertama kali dibutuhkan (lazy).
    RF_PRELOAD = _env_bool("RF_PRELOAD", True)

    # Simpan berkas audio yang dikirim perangkat. Default False karena
    # rekaman suara di ruang publik adalah data sensitif.
    SAVE_AUDIO = _env_bool("SAVE_AUDIO", False)
    AUDIO_DIR = str(BASE_DIR / "data" / "audio")

    # --- Layanan konteks eksternal --------------------------------------
    # TOMTOM_API_KEY dibaca langsung oleh services/context/core/traffic_service.py
    # lewat os.getenv. Disalin ke config hanya untuk keperluan /api/health,
    # dan yang dilaporkan hanya ADA/TIDAK, bukan nilainya.
    TOMTOM_API_KEY_PRESENT = bool(os.getenv("TOMTOM_API_KEY", "").strip())

    # Batas waktu pemanggilan API konteks (detik). Dipakai sebagai acuan;
    # core service memakai timeout=10 masing-masing.
    CONTEXT_API_TIMEOUT = _env_int("CONTEXT_API_TIMEOUT", 10)

    # Folder frontend (template & static) berada di luar folder backend/
    TEMPLATE_DIR = str(PROJECT_ROOT / "frontend" / "templates")
    STATIC_DIR = str(PROJECT_ROOT / "frontend" / "static")


class TestConfig(Config):
    """Konfigurasi untuk pytest: database in-memory, API key tetap."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    DEVICE_API_KEY = "test-device-api-key"
    # Kunci operator tetap untuk test. Di luar test, nilainya HARUS berasal
    # dari environment; tidak ada default di Config.
    DEVICE_CONFIG_API_KEY = "test-operator-key"
    DEVICE_OFFLINE_TIMEOUT = 60

    # Model tidak dimuat otomatis saat test supaya pytest tetap cepat.
    # Test yang memang menguji model memanggil model_loader secara eksplisit
    # dan akan di-skip bila file .pkl tidak tersedia.
    RF_PRELOAD = False
    SAVE_AUDIO = False
