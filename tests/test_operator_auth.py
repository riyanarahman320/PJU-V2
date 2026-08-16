"""Test autentikasi operator pada endpoint aksi incident.

Empat endpoint di bawah mengubah status darurat dan sebagian mengirim command
ke perangkat di lapangan:

  POST /api/incidents/<id>/confirm       -> membuat EMERGENCY_CONFIRMED
  POST /api/incidents/<id>/false-alarm   -> membuat CLEAR_EMERGENCY
  POST /api/incidents/<id>/close         -> membuat CLEAR_EMERGENCY
  POST /api/incidents/<id>/dispatch      -> mengubah status incident

Karena itu semuanya memerlukan header X-Operator-Key yang cocok dengan
DEVICE_CONFIG_API_KEY. Yang dijaga file ini bukan hanya kode responsnya,
tetapi juga bahwa request yang ditolak TIDAK meninggalkan efek: status
incident tidak berubah dan tidak ada command yang terbuat.

Kunci perangkat (DEVICE_API_KEY) sengaja tidak berlaku di sini. Kunci itu
tertanam di firmware dan dipakai seluruh unit, jadi tidak layak memberi
wewenang menyalakan atau mematikan respons darurat.
"""

import pytest

from backend.config import TestConfig

# Empat endpoint aksi operator beserta status akhir yang diharapkan
# bila request berhasil.
AKSI = [
    ("confirm", "CONFIRMED"),
    ("false-alarm", "FALSE_ALARM"),
    ("close", "CLOSED"),
    ("dispatch", "DISPATCHED"),
]
NAMA_AKSI = [nama for nama, _ in AKSI]


def url(incident_id: str, aksi: str) -> str:
    return f"/api/incidents/{incident_id}/{aksi}"


def jumlah_command(incident_id: str) -> int:
    """Hitung command yang terbuat untuk sebuah incident."""
    from backend.models import Command

    return Command.query.filter_by(incident_id=incident_id).count()


class TestTanpaKunci:
    """Tanpa header X-Operator-Key -> 401."""

    @pytest.mark.parametrize("aksi", NAMA_AKSI)
    def test_ditolak_401(self, client, incident, aksi):
        respons = client.post(url(incident.incident_id, aksi), json={})
        assert respons.status_code == 401

    @pytest.mark.parametrize("aksi", NAMA_AKSI)
    def test_status_incident_tidak_berubah(self, client, incident, aksi):
        semula = incident.status
        client.post(url(incident.incident_id, aksi), json={})

        data = client.get(f"/api/incidents/{incident.incident_id}").get_json()["data"]
        assert data["incident"]["status"] == semula

    @pytest.mark.parametrize("aksi", NAMA_AKSI)
    def test_tidak_ada_command_terbuat(self, client, incident, aksi):
        """Request yang ditolak tidak boleh menyentuh perangkat di lapangan."""
        client.post(url(incident.incident_id, aksi), json={})
        assert jumlah_command(incident.incident_id) == 0


class TestKunciSalah:
    """Header ada tetapi nilainya salah -> 403."""

    HEADERS = {"X-Operator-Key": "kunci-salah"}

    @pytest.mark.parametrize("aksi", NAMA_AKSI)
    def test_ditolak_403(self, client, incident, aksi):
        respons = client.post(
            url(incident.incident_id, aksi), json={}, headers=self.HEADERS
        )
        assert respons.status_code == 403

    @pytest.mark.parametrize("aksi", NAMA_AKSI)
    def test_status_incident_tidak_berubah(self, client, incident, aksi):
        semula = incident.status
        client.post(url(incident.incident_id, aksi), json={}, headers=self.HEADERS)

        data = client.get(f"/api/incidents/{incident.incident_id}").get_json()["data"]
        assert data["incident"]["status"] == semula

    @pytest.mark.parametrize("aksi", NAMA_AKSI)
    def test_tidak_ada_command_terbuat(self, client, incident, aksi):
        client.post(url(incident.incident_id, aksi), json={}, headers=self.HEADERS)
        assert jumlah_command(incident.incident_id) == 0

    @pytest.mark.parametrize("aksi", NAMA_AKSI)
    def test_pesan_galat_tidak_membocorkan_kunci(self, client, incident, aksi):
        respons = client.post(
            url(incident.incident_id, aksi), json={}, headers=self.HEADERS
        )
        assert TestConfig.DEVICE_CONFIG_API_KEY not in respons.get_data(as_text=True)


class TestKunciBenar:
    """Dengan kunci yang sah, logika lama harus berjalan seperti semula."""

    @pytest.mark.parametrize("aksi", NAMA_AKSI)
    def test_diterima_200(self, client, incident, operator_headers, aksi):
        respons = client.post(
            url(incident.incident_id, aksi), json={}, headers=operator_headers
        )
        assert respons.status_code == 200

    @pytest.mark.parametrize("aksi,status_akhir", AKSI)
    def test_status_incident_berubah_seperti_semula(
        self, client, incident, operator_headers, aksi, status_akhir
    ):
        """Guard tidak boleh mengubah business logic."""
        respons = client.post(
            url(incident.incident_id, aksi), json={}, headers=operator_headers
        )
        assert respons.get_json()["data"]["incident"]["status"] == status_akhir

    @pytest.mark.parametrize("aksi", ["confirm", "false-alarm", "close"])
    def test_command_tetap_terbuat(self, client, incident, operator_headers, aksi):
        """Ketiga aksi ini memang harus mengirim command ke perangkat."""
        respons = client.post(
            url(incident.incident_id, aksi), json={}, headers=operator_headers
        )
        assert respons.get_json()["data"]["command"] is not None
        assert jumlah_command(incident.incident_id) >= 1

    def test_catatan_operator_tetap_tersimpan(
        self, client, incident, operator_headers
    ):
        respons = client.post(
            url(incident.incident_id, "false-alarm"),
            json={"note": "Ternyata suara petasan."},
            headers=operator_headers,
        )
        alasan = respons.get_json()["data"]["incident"]["server_reason"]
        assert "petasan" in alasan

    def test_incident_tidak_ada_tetap_404(self, client, operator_headers):
        """Autentikasi lulus, lalu 404 seperti perilaku sebelumnya."""
        respons = client.post(
            url("INC-TIDAK-ADA", "confirm"), json={}, headers=operator_headers
        )
        assert respons.status_code == 404


class TestKunciKosong:
    """DEVICE_CONFIG_API_KEY kosong -> endpoint TERTUTUP, bukan terbuka.

    Ini pembeda yang menentukan: bila kunci kosong diartikan "tanpa
    autentikasi", lupa mengisi .env akan membuka seluruh aksi operator tanpa
    ada yang menyadari.
    """

    @pytest.mark.parametrize("aksi", NAMA_AKSI)
    def test_ditolak_500(self, app, incident, aksi):
        app.config["DEVICE_CONFIG_API_KEY"] = ""
        respons = app.test_client().post(
            url(incident.incident_id, aksi),
            json={},
            headers={"X-Operator-Key": "apa-pun"},
        )
        assert respons.status_code == 500

    @pytest.mark.parametrize("aksi", NAMA_AKSI)
    def test_tidak_ada_command_terbuat(self, app, incident, aksi):
        app.config["DEVICE_CONFIG_API_KEY"] = ""
        app.test_client().post(
            url(incident.incident_id, aksi),
            json={},
            headers={"X-Operator-Key": "apa-pun"},
        )
        assert jumlah_command(incident.incident_id) == 0

    @pytest.mark.parametrize("aksi", NAMA_AKSI)
    def test_tanpa_header_pun_tetap_tertutup(self, app, incident, aksi):
        app.config["DEVICE_CONFIG_API_KEY"] = ""
        respons = app.test_client().post(url(incident.incident_id, aksi), json={})
        assert respons.status_code == 500


class TestKunciPerangkatTidakBerlaku:
    """DEVICE_API_KEY tidak boleh memberi wewenang operator."""

    @pytest.mark.parametrize("aksi", NAMA_AKSI)
    def test_device_api_key_ditolak(self, client, incident, api_headers, aksi):
        respons = client.post(
            url(incident.incident_id, aksi), json={}, headers=api_headers
        )
        assert respons.status_code == 401

    @pytest.mark.parametrize("aksi", NAMA_AKSI)
    def test_device_api_key_di_header_operator_ditolak(
        self, client, incident, aksi
    ):
        """Kunci perangkat yang dikirim lewat header operator tetap ditolak."""
        respons = client.post(
            url(incident.incident_id, aksi),
            json={},
            headers={"X-Operator-Key": TestConfig.DEVICE_API_KEY},
        )
        assert respons.status_code == 403


class TestDispatchLebihKetat:
    """Dispatch diperiksa terpisah karena paling sensitif.

    Urutan yang harus berlaku:
        X-Operator-Key valid -> logika dispatch -> command
    Tanpa kunci yang sah, request berhenti sebelum logika dispatch.
    """

    def test_dispatch_tanpa_kunci_tidak_mengubah_status(self, client, incident):
        assert incident.status == "ACTIVE"
        respons = client.post(url(incident.incident_id, "dispatch"), json={})

        assert respons.status_code == 401
        data = client.get(f"/api/incidents/{incident.incident_id}").get_json()["data"]
        assert data["incident"]["status"] == "ACTIVE"

    def test_dispatch_tanpa_kunci_tidak_menulis_log(self, client, incident):
        """Log INCIDENT_DISPATCHED hanya boleh muncul bila aksi benar terjadi."""
        client.post(url(incident.incident_id, "dispatch"), json={})

        data = client.get(f"/api/incidents/{incident.incident_id}").get_json()["data"]
        jenis = [log["event_type"] for log in data["logs"]]
        assert "INCIDENT_DISPATCHED" not in jenis

    def test_dispatch_dengan_kunci_benar_berjalan(
        self, client, incident, operator_headers
    ):
        respons = client.post(
            url(incident.incident_id, "dispatch"), json={}, headers=operator_headers
        )
        assert respons.status_code == 200
        assert respons.get_json()["data"]["incident"]["status"] == "DISPATCHED"

    def test_dispatch_tidak_membuat_command_baru(
        self, client, incident, operator_headers
    ):
        """Perilaku lama dipertahankan: dispatch tidak mengubah command.

        Sirene tetap menyala sampai incident ditutup, jadi dispatch memang
        tidak perlu mengirim command apa pun.
        """
        client.post(
            url(incident.incident_id, "dispatch"), json={}, headers=operator_headers
        )
        assert jumlah_command(incident.incident_id) == 0


class TestEndpointBacaTetapTerbuka:
    """GET tidak boleh ikut terkunci; dashboard memerlukannya."""

    def test_daftar_incident_terbuka(self, client, incident):
        assert client.get("/api/incidents").status_code == 200

    def test_detail_incident_terbuka(self, client, incident):
        respons = client.get(f"/api/incidents/{incident.incident_id}")
        assert respons.status_code == 200

    def test_daftar_incident_tidak_membocorkan_kunci(self, client, incident):
        isi = client.get("/api/incidents").get_data(as_text=True)
        assert TestConfig.DEVICE_CONFIG_API_KEY not in isi


class TestEndpointLainTidakTerpengaruh:
    """Endpoint perangkat tetap memakai device API key seperti sebelumnya."""

    def test_evaluate_masih_memakai_device_key(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        respons = client.post(
            "/api/emergency/evaluate", json=payload_emergency, headers=api_headers
        )
        assert respons.status_code == 200

    def test_evaluate_menolak_operator_key(
        self, client, operator_headers, device, payload_emergency, konteks_stabil
    ):
        """Sebaliknya juga berlaku: kunci operator bukan kunci perangkat."""
        respons = client.post(
            "/api/emergency/evaluate",
            json=payload_emergency,
            headers=operator_headers,
        )
        assert respons.status_code == 401
