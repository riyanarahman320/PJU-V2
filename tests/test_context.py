"""Test lapisan konteks: pemetaan kosakata dan prediksi hotspot.

Fokus utama file ini adalah KETIDAKCOCOKAN SENYAP, yaitu keadaan ketika nilai
yang dikirim sistem tidak dikenal oleh model tetapi diterima tanpa peringatan.
Pipeline memakai OneHotEncoder(handle_unknown='ignore'), sehingga nilai asing
diubah menjadi vektor nol dan prediksi tetap keluar walau masukannya salah.
Itu berbahaya karena hasilnya tampak sah.

Aturan yang dijaga:
  - Nilai di luar kosakata model TIDAK dipaksakan; hotspot menolak memprediksi.
  - Population_Density yang kosong TIDAK diisi angka karangan.
"""

from datetime import datetime

import pytest

from backend.services.context import hotspot_service, vocab
from tests.conftest import butuh_model

MOMENT = datetime(2026, 8, 13, 22, 30)

WEATHER_OK = {
    "weather": "Clear",
    "weather_model": "Sunny",
    "temperature": 24.5,
    "rainfall": 0.0,
    "status": "REAL_API",
}
TRAFFIC_OK = {
    "traffic_level": "Low",
    "traffic_level_model": "Low",
    "status": "REAL_API",
}
LIGHTING_OK = {
    "lighting_condition": "Poor",
    "lighting_condition_model": "Poor",
    "is_dark": True,
    "status": "ESTIMATED",
}
HISTORY_OK = {
    "previous_incidents_last30days": 2,
    "emergency_call_last30days": 5,
    "history_score": 0.6,
    "status": "REAL_OWN_DATABASE",
}

CONFIG_TANPA_DENSITY = {
    "village": "Babakan Sari",
    "road_type": "Main Road",
    "area_type": "Public Facility",
    "nearby_cctv": "Yes",
    "nearby_police_post": "No",
    "population_density": None,
    "public_event": "No",
    "holiday": "No",
}

# Angka ini HANYA untuk pengujian teknis, bukan rekomendasi nilai.
CONFIG_LENGKAP = dict(CONFIG_TANPA_DENSITY, population_density=12000.0)


class TestPemetaanCuaca:
    """Open-Meteo memakai istilah yang berbeda dari dataset training."""

    @pytest.mark.parametrize(
        "masukan,harapan",
        [
            ("Clear", "Sunny"),
            ("Sunny", "Sunny"),
            ("Storm", "Heavy Rain"),
            ("Heavy Rain", "Heavy Rain"),
            ("Rain", "Rain"),
            ("Cloudy", "Cloudy"),
            ("Fog", "Fog"),
        ],
    )
    def test_cuaca_dipetakan_ke_kosakata_model(self, masukan, harapan):
        assert vocab.map_weather(masukan) == harapan

    @pytest.mark.parametrize("masukan", ["Unknown", "", None, "Hujan Es"])
    def test_cuaca_asing_tidak_dipaksakan(self, masukan):
        """Nilai tak dikenal harus menjadi None, bukan ditebak."""
        assert vocab.map_weather(masukan) is None

    def test_hujan_lebat_dinaikkan_berdasarkan_curah(self):
        """Rain dengan curah tinggi lebih tepat disebut Heavy Rain."""
        assert vocab.map_weather("Rain", 15.0) == "Heavy Rain"


class TestPemetaanLaluLintas:
    @pytest.mark.parametrize(
        "masukan,harapan",
        [
            ("Low", "Low"),
            ("Medium", "Medium"),
            ("High", "High"),
            ("QUIET", "Low"),
            ("CONGESTED", "High"),
        ],
    )
    def test_lalu_lintas_dipetakan(self, masukan, harapan):
        assert vocab.map_traffic(masukan) == harapan

    def test_lalu_lintas_asing_tidak_dipaksakan(self):
        assert vocab.map_traffic("Macet Total") is None


class TestPemetaanKelurahan:
    def test_kelurahan_dikenal_apapun_huruf_besarnya(self):
        assert vocab.map_village("babakan sari") == "Babakan Sari"
        assert vocab.map_village("BABAKAN SARI") == "Babakan Sari"

    def test_kelurahan_luar_wilayah_ditolak(self):
        """Model hanya mengenal 6 kelurahan di Kiaracondong, Bandung.

        Device di luar wilayah itu tidak dapat diprediksi hotspot-nya, dan
        keterbatasan ini harus terlihat, bukan disembunyikan.
        """
        assert vocab.map_village("Menteng") is None
        assert vocab.map_village("Sukajadi") is None


@butuh_model
class TestPrediksiHotspot:
    """Test yang memerlukan random_forest_pipeline.pkl."""

    def test_population_density_kosong_menolak_prediksi(self):
        hasil = hotspot_service.predict_hotspot(
            moment=MOMENT,
            weather=WEATHER_OK,
            traffic=TRAFFIC_OK,
            lighting=LIGHTING_OK,
            device_config=CONFIG_TANPA_DENSITY,
            history=HISTORY_OK,
        )
        assert hasil["status"] == "MISSING_FEATURES"
        assert hasil["risk_score"] is None
        assert any("Population_Density" in m for m in hasil["missing"])

    def test_fitur_lengkap_menghasilkan_prediksi(self):
        hasil = hotspot_service.predict_hotspot(
            moment=MOMENT,
            weather=WEATHER_OK,
            traffic=TRAFFIC_OK,
            lighting=LIGHTING_OK,
            device_config=CONFIG_LENGKAP,
            history=HISTORY_OK,
        )
        assert hasil["status"] == "OK"
        assert hasil["risk_level"] in ("High", "Medium", "Low")
        assert 0.0 <= hasil["risk_score"] <= 1.0

    def test_probabilitas_berjumlah_seratus_persen(self):
        hasil = hotspot_service.predict_hotspot(
            moment=MOMENT,
            weather=WEATHER_OK,
            traffic=TRAFFIC_OK,
            lighting=LIGHTING_OK,
            device_config=CONFIG_LENGKAP,
            history=HISTORY_OK,
        )
        assert abs(sum(hasil["probability"].values()) - 100.0) < 0.5

    def test_cuaca_tidak_dikenal_menolak_prediksi(self):
        """Inti pencegahan ketidakcocokan senyap.

        Tanpa pemeriksaan ini, cuaca asing akan menjadi vektor nol dan model
        tetap mengeluarkan angka yang tampak sah.
        """
        weather_asing = dict(
            WEATHER_OK, weather="Unknown", weather_model=None, status="ERROR"
        )
        hasil = hotspot_service.predict_hotspot(
            moment=MOMENT,
            weather=weather_asing,
            traffic=TRAFFIC_OK,
            lighting=LIGHTING_OK,
            device_config=CONFIG_LENGKAP,
            history=HISTORY_OK,
        )
        assert hasil["status"] == "MISSING_FEATURES"

    def test_kelurahan_luar_wilayah_menolak_prediksi(self):
        config = dict(CONFIG_LENGKAP, village="Menteng")
        hasil = hotspot_service.predict_hotspot(
            moment=MOMENT,
            weather=WEATHER_OK,
            traffic=TRAFFIC_OK,
            lighting=LIGHTING_OK,
            device_config=config,
            history=HISTORY_OK,
        )
        assert hasil["status"] == "MISSING_FEATURES"

    def test_urutan_fitur_sesuai_model(self):
        """Urutan kolom harus mengikuti feature_names_in_ dari pipeline."""
        from backend.services.ai import model_loader

        model_loader.try_load()
        meta = model_loader.model_metadata()
        assert meta["feature_names"] == list(vocab.RF_FEATURE_ORDER)
