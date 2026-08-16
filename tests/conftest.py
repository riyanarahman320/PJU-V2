"""Fixture bersama untuk seluruh test.

Catatan penting soal isolasi test:
  - Database memakai SQLite in-memory (TestConfig), jadi setiap test mulai
    dari keadaan kosong dan tidak menyentuh data/asepjaga.db.
  - Layanan konteks eksternal (Open-Meteo, TomTom) TIDAK pernah dipanggil
    dari test. Setiap test yang membutuhkan konteks memakai monkeypatch,
    supaya hasil test tidak bergantung pada jaringan.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app  # noqa: E402
from backend.config import TestConfig  # noqa: E402
from backend.database import db as _db  # noqa: E402

# Lokasi model. Test yang membutuhkan model akan di-skip bila file tidak ada,
# karena file 79 MB ini tidak di-commit ke Git.
RF_MODEL_PATH = PROJECT_ROOT / "backend" / "models_store" / "random_forest_pipeline.pkl"
MODEL_TERSEDIA = RF_MODEL_PATH.exists()

butuh_model = pytest.mark.skipif(
    not MODEL_TERSEDIA,
    reason=(
        "random_forest_pipeline.pkl tidak tersedia. "
        "Letakkan di backend/models_store/ (lihat README)."
    ),
)


@pytest.fixture
def app():
    """Aplikasi Flask dengan database in-memory."""
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    """HTTP test client."""
    return app.test_client()


@pytest.fixture
def db(app):
    """Session database di dalam app context."""
    return _db


@pytest.fixture
def api_headers():
    """Header dengan device API key yang sah."""
    return {"X-API-Key": TestConfig.DEVICE_API_KEY}


@pytest.fixture
def operator_headers():
    """Header dengan operator key yang sah (untuk PUT config).

    Kunci operator berbeda dari device API key: perangkat tidak boleh dapat
    mengubah konfigurasi konteks hanya karena memiliki kunci perangkat.
    """
    return {"X-Operator-Key": TestConfig.DEVICE_CONFIG_API_KEY}


@pytest.fixture
def device(db):
    """Device terdaftar TANPA konfigurasi konteks.

    Sengaja tanpa konfigurasi: ini keadaan default device baru, dan dipakai
    untuk menguji bahwa hotspot menolak memprediksi saat fitur belum lengkap.
    """
    from backend.models import Device, utcnow

    item = Device(
        device_id="PJU-TEST-001",
        name="PJU Test",
        location="Jl. Test",
        latitude=-6.9200,
        longitude=107.6400,
        status="ONLINE",
        last_seen=utcnow(),
    )
    db.session.add(item)
    db.session.commit()
    return item


@pytest.fixture
def device_lengkap(db):
    """Device dengan konfigurasi konteks LENGKAP (18 fitur dapat disusun).

    Nilai population_density=12000.0 di sini HANYA agar prediksi dapat diuji.
    Angka ini bukan rekomendasi dan tidak dipakai sebagai default di kode
    produksi mana pun.
    """
    from backend.models import Device, utcnow

    item = Device(
        device_id="PJU-TEST-FULL",
        name="PJU Test Lengkap",
        location="Jl. Babakan Sari",
        latitude=-6.9200,
        longitude=107.6400,
        status="ONLINE",
        last_seen=utcnow(),
        village="Babakan Sari",
        road_type="Main Road",
        area_type="Public Facility",
        nearby_cctv="Yes",
        nearby_police_post="No",
        population_density=12000.0,
        public_event="No",
        holiday="No",
    )
    db.session.add(item)
    db.session.commit()
    return item


@pytest.fixture
def konteks_stabil(monkeypatch):
    """Ganti pemanggilan API eksternal dengan nilai tetap.

    Tanpa fixture ini, test akan memanggil Open-Meteo dan TomTom sungguhan:
    lambat, tidak dapat diandalkan, dan hasilnya berubah-ubah.
    """
    from backend.services.context import traffic_service, weather_service

    def cuaca_palsu(latitude=None, longitude=None):
        return {
            "weather": "Clear",
            "weather_model": "Sunny",
            "temperature": 24.5,
            "rainfall": 0.0,
            "humidity": 80,
            "status": "REAL_API",
            "source": "OPEN_METEO",
        }

    def lalu_lintas_palsu(latitude=None, longitude=None):
        return {
            "traffic_level": "Low",
            "traffic_level_model": "Low",
            "current_speed": 40,
            "free_flow_speed": 45,
            "status": "REAL_API",
            "source": "TOMTOM",
        }

    monkeypatch.setattr(weather_service, "get_weather", cuaca_palsu)
    monkeypatch.setattr(traffic_service, "get_traffic", lalu_lintas_palsu)


@pytest.fixture
def incident(db, device):
    """Incident berstatus ACTIVE untuk menguji aksi operator.

    Dibuat langsung lewat model, bukan lewat /api/emergency/evaluate, supaya
    test aksi operator tidak bergantung pada hasil verifikasi.
    """
    from backend.models import Incident, utcnow

    item = Incident(
        incident_id="INC-20260813-0001",
        device_id=device.device_id,
        sos=True,
        audio_confidence=0.92,
        audio_class="Scream/Teriakan",
        local_decision="LOCAL_VERIFIED",
        server_decision="CONFIRMED",
        server_score=0.85,
        verification_method="RULE_BASED_SECOND_LEVEL",
        status="ACTIVE",
        created_at=utcnow(),
    )
    db.session.add(item)
    db.session.commit()
    return item


@pytest.fixture
def payload_emergency():
    """Payload emergency yang sah dari ESP32."""
    return {
        "device_id": "PJU-TEST-001",
        "sos": True,
        "audio_confidence": 0.92,
        "audio_class": "Scream/Teriakan",
        "local_decision": "LOCAL_VERIFIED",
        "latitude": -6.9200,
        "longitude": 107.6400,
    }
