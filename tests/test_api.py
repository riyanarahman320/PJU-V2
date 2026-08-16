"""Test endpoint HTTP.

Layanan konteks eksternal tidak pernah dipanggil di sini: fixture
`konteks_stabil` menggantikan Open-Meteo dan TomTom dengan nilai tetap,
sehingga hasil test tidak bergantung pada jaringan.
"""

from backend.config import TestConfig


class TestHealth:
    def test_health_dapat_diakses_tanpa_api_key(self, client):
        respons = client.get("/api/health")
        assert respons.status_code == 200
        assert respons.get_json()["data"]["status"] == "OK"

    def test_health_melaporkan_verifikasi_rule_based(self, client):
        """Sistem harus jujur: keputusan tahap 2 bukan hasil model AI."""
        data = client.get("/api/health").get_json()["data"]
        verifikasi = data["verification"]
        assert verifikasi["method"] == "RULE_BASED_SECOND_LEVEL"
        assert verifikasi["is_ai_model"] is False

    def test_health_melaporkan_status_layanan_konteks(self, client):
        data = client.get("/api/health").get_json()["data"]
        layanan = data["context_services"]
        assert layanan["weather"]["provider"] == "Open-Meteo"
        assert layanan["traffic"]["provider"] == "TomTom"
        # Pencahayaan adalah estimasi, bukan sensor. Ini harus terlihat.
        assert layanan["lighting"]["status"] == "ESTIMATED"

    def test_health_tidak_membocorkan_api_key(self, client):
        """Yang dilaporkan hanya ADA/TIDAK, bukan nilai kunci."""
        respons = client.get("/api/health")
        traffic = respons.get_json()["data"]["context_services"]["traffic"]
        assert isinstance(traffic["api_key_present"], bool)

        isi = respons.get_data(as_text=True)
        assert TestConfig.DEVICE_API_KEY not in isi
        assert TestConfig.DEVICE_CONFIG_API_KEY not in isi


class TestRegistrasiDevice:
    def test_registrasi_tanpa_api_key_ditolak(self, client):
        respons = client.post("/api/device/register", json={"device_id": "PJU-X"})
        assert respons.status_code == 401

    def test_registrasi_device_baru(self, client, api_headers):
        respons = client.post(
            "/api/device/register",
            json={"device_id": "PJU-BARU-001", "name": "PJU Baru"},
            headers=api_headers,
        )
        assert respons.status_code == 201
        assert respons.get_json()["data"]["created"] is True

    def test_registrasi_ulang_bersifat_idempotent(self, client, api_headers):
        """ESP32 memanggil register setiap boot; tidak boleh error."""
        payload = {"device_id": "PJU-BARU-002"}
        client.post("/api/device/register", json=payload, headers=api_headers)
        respons = client.post(
            "/api/device/register", json=payload, headers=api_headers
        )
        assert respons.status_code == 200
        assert respons.get_json()["data"]["created"] is False


class TestKonfigurasiDevice:
    """PUT /api/device/<id>/config — operator mengisi konteks titik PJU."""

    def test_pilihan_konfigurasi_tersedia(self, client):
        respons = client.get("/api/device/config/options")
        assert respons.status_code == 200
        opsi = respons.get_json()["data"]["options"]
        assert len(opsi["village"]) == 6
        assert "Yes" in opsi["nearby_cctv"]

    def test_population_density_dilaporkan_belum_tersedia(self, client):
        """Keterbatasan ini harus terlihat oleh operator, bukan disembunyikan."""
        data = client.get("/api/device/config/options").get_json()["data"]
        density = data["population_density"]
        assert density["status"] == "NOT_AVAILABLE"
        assert density["required_for_hotspot"] is True

    def test_device_baru_belum_lengkap_konfigurasinya(self, client, device):
        respons = client.get(f"/api/device/{device.device_id}/config")
        assert respons.status_code == 200
        assert respons.get_json()["data"]["rf_config_complete"] is False

    def test_konfigurasi_dapat_diperbarui(self, client, device, operator_headers):
        respons = client.put(
            f"/api/device/{device.device_id}/config",
            json={"village": "Babakan Sari", "road_type": "Main Road"},
            headers=operator_headers,
        )
        assert respons.status_code == 200
        assert respons.get_json()["data"]["config"]["village"] == "Babakan Sari"

    def test_nilai_di_luar_kosakata_model_ditolak(
        self, client, device, operator_headers
    ):
        """Inti pencegahan ketidakcocokan senyap pada lapisan HTTP.

        Nilai asing harus ditolak dengan 400. Bila diterima, OneHotEncoder
        akan mengubahnya menjadi vektor nol dan prediksi tetap keluar
        walaupun masukannya tidak dikenal model.
        """
        respons = client.put(
            f"/api/device/{device.device_id}/config",
            json={"village": "Menteng"},
            headers=operator_headers,
        )
        assert respons.status_code == 400

    def test_kelurahan_tidak_peka_huruf_besar(self, client, device, operator_headers):
        respons = client.put(
            f"/api/device/{device.device_id}/config",
            json={"village": "babakan sari"},
            headers=operator_headers,
        )
        assert respons.status_code == 200
        # Disimpan dalam bentuk yang dikenal model.
        assert respons.get_json()["data"]["config"]["village"] == "Babakan Sari"

    def test_population_density_negatif_ditolak(
        self, client, device, operator_headers
    ):
        respons = client.put(
            f"/api/device/{device.device_id}/config",
            json={"population_density": -5},
            headers=operator_headers,
        )
        assert respons.status_code == 400

    def test_konfigurasi_device_tidak_ada(self, client, operator_headers):
        respons = client.put(
            "/api/device/PJU-TIDAK-ADA/config",
            json={"village": "Babakan Sari"},
            headers=operator_headers,
        )
        assert respons.status_code == 404


class TestAutentikasiKonfigurasi:
    """Autentikasi operator pada PUT /api/device/<id>/config.

    Endpoint ini mengubah data yang memengaruhi prediksi hotspot: mengganti
    Village atau Population_Density akan mengubah hasil verifikasi kejadian
    berikutnya di titik tersebut. Karena itu perubahan konfigurasi tidak
    boleh terbuka bagi siapa pun yang dapat menjangkau server.
    """

    PAYLOAD = {"village": "Babakan Sari"}

    def test_tanpa_key_ditolak_401(self, client, device):
        respons = client.put(
            f"/api/device/{device.device_id}/config", json=self.PAYLOAD
        )
        assert respons.status_code == 401

    def test_key_salah_ditolak_403(self, client, device):
        respons = client.put(
            f"/api/device/{device.device_id}/config",
            json=self.PAYLOAD,
            headers={"X-Operator-Key": "kunci-salah"},
        )
        assert respons.status_code == 403

    def test_key_benar_diterima(self, client, device, operator_headers):
        respons = client.put(
            f"/api/device/{device.device_id}/config",
            json=self.PAYLOAD,
            headers=operator_headers,
        )
        assert respons.status_code == 200

    def test_device_api_key_tidak_berlaku_untuk_konfigurasi(
        self, client, device, api_headers
    ):
        """Perangkat tidak boleh dapat mengubah konfigurasi konteks.

        Kunci perangkat tertanam di firmware dan dipakai semua unit, jadi
        kunci itu tidak layak dipakai sebagai wewenang operator.
        """
        respons = client.put(
            f"/api/device/{device.device_id}/config",
            json=self.PAYLOAD,
            headers=api_headers,
        )
        assert respons.status_code == 401

    def test_konfigurasi_tidak_berubah_saat_ditolak(self, client, device):
        """Request yang ditolak tidak boleh menyentuh database."""
        client.put(
            f"/api/device/{device.device_id}/config",
            json=self.PAYLOAD,
            headers={"X-Operator-Key": "kunci-salah"},
        )
        data = client.get(f"/api/device/{device.device_id}/config").get_json()["data"]
        assert data["config"]["village"] is None

    def test_server_menolak_bila_kunci_belum_dikonfigurasi(self, app, device):
        """Kunci kosong berarti endpoint TERTUTUP, bukan terbuka.

        Pembeda penting: bila kunci kosong diartikan "tanpa autentikasi",
        lupa mengisi .env akan membuka endpoint tanpa ada yang menyadari.
        """
        app.config["DEVICE_CONFIG_API_KEY"] = ""
        respons = app.test_client().put(
            f"/api/device/{device.device_id}/config",
            json=self.PAYLOAD,
            headers={"X-Operator-Key": "apa-pun"},
        )
        assert respons.status_code == 500

    def test_pesan_galat_tidak_membocorkan_kunci(self, client, device):
        respons = client.put(
            f"/api/device/{device.device_id}/config",
            json=self.PAYLOAD,
            headers={"X-Operator-Key": "kunci-salah"},
        )
        assert TestConfig.DEVICE_CONFIG_API_KEY not in respons.get_data(as_text=True)

    def test_endpoint_baca_tetap_terbuka(self, client, device):
        """GET config dan options tidak boleh ikut terkunci.

        Dashboard perlu keduanya untuk menampilkan keadaan konfigurasi,
        termasuk peringatan bahwa Population_Density belum tersedia.
        """
        assert client.get(f"/api/device/{device.device_id}/config").status_code == 200
        assert client.get("/api/device/config/options").status_code == 200

    def test_endpoint_perangkat_tidak_terpengaruh(self, client, api_headers):
        """Endpoint perangkat tetap memakai device API key seperti sebelumnya."""
        respons = client.post(
            "/api/device/register",
            json={"device_id": "PJU-AUTH-CEK"},
            headers=api_headers,
        )
        assert respons.status_code in (200, 201)


class TestAlurEmergency:
    """POST /api/emergency/evaluate — alur utama sistem."""

    def test_tanpa_api_key_ditolak(self, client, device, payload_emergency):
        respons = client.post("/api/emergency/evaluate", json=payload_emergency)
        assert respons.status_code == 401

    def test_device_belum_terdaftar_ditolak(
        self, client, api_headers, payload_emergency, konteks_stabil
    ):
        payload = dict(payload_emergency, device_id="PJU-TIDAK-ADA")
        respons = client.post(
            "/api/emergency/evaluate", json=payload, headers=api_headers
        )
        assert respons.status_code == 404

    def test_emergency_tersimpan_dan_dievaluasi(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        respons = client.post(
            "/api/emergency/evaluate", json=payload_emergency, headers=api_headers
        )
        assert respons.status_code == 200
        data = respons.get_json()["data"]
        assert data["incident_id"].startswith("INC-")
        assert data["server_decision"] in ("CONFIRMED", "FALSE_ALARM")

    def test_metode_verifikasi_dilaporkan_rule_based(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        respons = client.post(
            "/api/emergency/evaluate", json=payload_emergency, headers=api_headers
        )
        data = respons.get_json()["data"]
        assert data["verification_method"] == "RULE_BASED_SECOND_LEVEL"

    def test_respons_tidak_lagi_mengaku_mock(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Data konteks kini nyata, jadi label DEVELOPMENT_MOCK harus hilang."""
        respons = client.post(
            "/api/emergency/evaluate", json=payload_emergency, headers=api_headers
        )
        assert "DEVELOPMENT_MOCK" not in respons.get_data(as_text=True)

    def test_hotspot_null_bila_konfigurasi_belum_lengkap(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Device tanpa Population_Density: hotspot harus null, bukan 0.0.

        Nilai 0.0 berarti "lokasi aman", dan itu klaim yang tidak dapat
        dipertanggungjawabkan bila modelnya tidak pernah dipanggil.
        """
        respons = client.post(
            "/api/emergency/evaluate", json=payload_emergency, headers=api_headers
        )
        konteks = respons.get_json()["data"]["context"]
        assert konteks["hotspot_risk"] is None
        assert konteks["hotspot_status"] != "OK"

    def test_sos_saja_tidak_menghasilkan_confirmed(
        self, client, api_headers, device, konteks_stabil
    ):
        """Aturan keselamatan inti, diuji lewat HTTP."""
        payload = {
            "device_id": device.device_id,
            "sos": True,
            "audio_confidence": 0.0,
            "audio_class": "Normal",
        }
        respons = client.post(
            "/api/emergency/evaluate", json=payload, headers=api_headers
        )
        assert respons.get_json()["data"]["server_decision"] == "FALSE_ALARM"

    def test_payload_tidak_valid_ditolak(self, client, api_headers, device):
        respons = client.post(
            "/api/emergency/evaluate",
            json={"device_id": device.device_id, "audio_confidence": 5.0},
            headers=api_headers,
        )
        assert respons.status_code == 400

    def test_fitur_audio_opsional_diterima(
        self, client, api_headers, device, konteks_stabil
    ):
        """Perangkat boleh mengirim audio_features untuk dijalankan model."""
        payload = {
            "device_id": device.device_id,
            "sos": True,
            "audio_confidence": 0.90,
            "audio_class": "Scream/Teriakan",
            "audio_features": {
                "energy": 0.9,
                "peak": 0.95,
                "zero_crossing_rate": 0.5,
                "dominant_frequency": 2800,
                "duration_ms": 1200,
            },
        }
        respons = client.post(
            "/api/emergency/evaluate", json=payload, headers=api_headers
        )
        assert respons.status_code == 200
        assert respons.get_json()["data"]["audio"]["ai_status"] == "OK"

    def test_fitur_audio_rusak_ditolak(
        self, client, api_headers, device, konteks_stabil
    ):
        payload = {
            "device_id": device.device_id,
            "sos": True,
            "audio_confidence": 0.90,
            "audio_class": "Scream/Teriakan",
            "audio_features": {"energy": "bukan angka"},
        }
        respons = client.post(
            "/api/emergency/evaluate", json=payload, headers=api_headers
        )
        assert respons.status_code == 400

    def test_snapshot_konteks_disimpan(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Keputusan lama harus tetap dapat diaudit di kemudian hari."""
        from backend.services.incident_service import get_incident

        respons = client.post(
            "/api/emergency/evaluate", json=payload_emergency, headers=api_headers
        )
        incident_id = respons.get_json()["data"]["incident_id"]
        assert get_incident(incident_id).context_snapshot is not None
