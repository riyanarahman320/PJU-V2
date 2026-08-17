"""Sensor tamper: kotak perangkat dibuka paksa.

Yang dijaga file ini bukan hanya kode responsnya, tetapi BATASAN DESAIN yang
mudah dilanggar tanpa sengaja di kemudian hari:

1. Tamper TIDAK membuat Incident.
   Verifikasi tahap 2 menilai bukti darurat korban (SOS + audio). Tamper tidak
   memiliki keduanya, jadi bila dimasukkan ke jalur itu ia akan selalu jatuh
   menjadi FALSE_ALARM - label yang keliru untuk peristiwa yang benar-benar
   terjadi, dan mengotori statistik incident.

2. Tamper TIDAK membuat Command.
   Menyalakan sirene karena tamper memberi tahu pelaku bahwa ia terdeteksi,
   dan membuat warga menyangka ada korban di lokasi.

3. Log hanya ditulis saat keadaan BERUBAH.
   Heartbeat datang setiap 8 detik dan membawa keadaan tamper. Bila setiap
   laporan dicatat, tabel logs akan dipenuhi baris identik sampai peristiwa
   pembongkaran yang sebenarnya tidak lagi dapat ditemukan.

4. `ever_tampered` tetap true setelah kotak ditutup.
   Menutup kotak tidak menghapus fakta bahwa ia pernah dibuka.
"""

from backend.models import Command, Device, Incident, Log

ENDPOINT = "/api/device/tamper"


def kirim(client, headers, payload):
    return client.post(ENDPOINT, json=payload, headers=headers)


def jumlah_log(tipe: str) -> int:
    return Log.query.filter_by(event_type=tipe).count()


class TestAutentikasi:
    """Endpoint tamper memakai kunci PERANGKAT, bukan kunci operator."""

    def test_tanpa_kunci_ditolak(self, client, device):
        respons = client.post(
            ENDPOINT, json={"device_id": device.device_id, "tamper": True}
        )
        assert respons.status_code == 401

    def test_tanpa_kunci_tidak_mengubah_keadaan(self, client, device):
        client.post(
            ENDPOINT, json={"device_id": device.device_id, "tamper": True}
        )
        assert Device.query.filter_by(device_id=device.device_id).first().tamper is False

    def test_kunci_salah_ditolak(self, client, device):
        respons = client.post(
            ENDPOINT,
            json={"device_id": device.device_id, "tamper": True},
            headers={"X-API-Key": "kunci-salah"},
        )
        assert respons.status_code in (401, 403)


class TestValidasi:
    def test_field_tamper_wajib(self, client, api_headers, device):
        """Laporan tanpa keadaan tidak bermakna dan tidak boleh ditebak."""
        respons = kirim(client, api_headers, {"device_id": device.device_id})
        assert respons.status_code == 400

    def test_tamper_harus_boolean(self, client, api_headers, device):
        respons = kirim(
            client, api_headers, {"device_id": device.device_id, "tamper": "ya"}
        )
        assert respons.status_code == 400

    def test_device_id_wajib(self, client, api_headers):
        respons = kirim(client, api_headers, {"tamper": True})
        assert respons.status_code == 400

    def test_device_belum_terdaftar(self, client, api_headers):
        respons = kirim(
            client, api_headers, {"device_id": "TIDAK-ADA-99", "tamper": True}
        )
        assert respons.status_code == 404


class TestPencatatan:
    def test_tamper_aktif_tercatat(self, client, api_headers, device):
        respons = kirim(
            client, api_headers, {"device_id": device.device_id, "tamper": True}
        )
        assert respons.status_code == 200

        state = respons.get_json()["data"]["tamper_state"]
        assert state["tamper"] is True
        assert state["tamper_since"] is not None
        assert state["ever_tampered"] is True

    def test_kolom_database_terisi(self, client, api_headers, device):
        kirim(client, api_headers, {"device_id": device.device_id, "tamper": True})

        tersimpan = Device.query.filter_by(device_id=device.device_id).first()
        assert tersimpan.tamper is True
        assert tersimpan.tamper_since is not None
        assert tersimpan.tamper_last_report is not None

    def test_log_ditulis_saat_terdeteksi(self, client, api_headers, device):
        sebelum = jumlah_log("DEVICE_TAMPER_DETECTED")
        kirim(client, api_headers, {"device_id": device.device_id, "tamper": True})
        assert jumlah_log("DEVICE_TAMPER_DETECTED") == sebelum + 1

    def test_laporan_ulang_tidak_menambah_log(self, client, api_headers, device):
        """Perangkat mengirim ulang laporan yang gagal, dan heartbeat membawa
        keadaan tamper setiap 8 detik. Keduanya tidak boleh membanjiri log."""
        kirim(client, api_headers, {"device_id": device.device_id, "tamper": True})
        setelah_pertama = jumlah_log("DEVICE_TAMPER_DETECTED")

        for _ in range(5):
            respons = kirim(
                client, api_headers, {"device_id": device.device_id, "tamper": True}
            )
            assert respons.get_json()["data"]["changed"] is False

        assert jumlah_log("DEVICE_TAMPER_DETECTED") == setelah_pertama

    def test_tamper_since_tidak_bergeser_pada_laporan_ulang(
        self, client, api_headers, device
    ):
        """Waktu mulai harus menunjuk pembukaan pertama, bukan laporan terakhir.
        Bila bergeser, operator kehilangan informasi sudah berapa lama kotak
        dalam keadaan terbuka."""
        pertama = kirim(
            client, api_headers, {"device_id": device.device_id, "tamper": True}
        ).get_json()["data"]["tamper_state"]["tamper_since"]

        ulang = kirim(
            client, api_headers, {"device_id": device.device_id, "tamper": True}
        ).get_json()["data"]["tamper_state"]["tamper_since"]

        assert pertama == ulang


class TestPemulihan:
    def test_pulih_tercatat(self, client, api_headers, device):
        kirim(client, api_headers, {"device_id": device.device_id, "tamper": True})
        respons = kirim(
            client, api_headers, {"device_id": device.device_id, "tamper": False}
        )

        state = respons.get_json()["data"]["tamper_state"]
        assert state["tamper"] is False
        assert state["tamper_since"] is None

    def test_jejak_tetap_ada_setelah_pulih(self, client, api_headers, device):
        """Menutup kotak tidak menghapus fakta bahwa ia pernah dibuka."""
        kirim(client, api_headers, {"device_id": device.device_id, "tamper": True})
        respons = kirim(
            client, api_headers, {"device_id": device.device_id, "tamper": False}
        )

        assert respons.get_json()["data"]["tamper_state"]["ever_tampered"] is True

    def test_log_pemulihan_terpisah(self, client, api_headers, device):
        kirim(client, api_headers, {"device_id": device.device_id, "tamper": True})
        sebelum = jumlah_log("DEVICE_TAMPER_CLEARED")

        kirim(client, api_headers, {"device_id": device.device_id, "tamper": False})
        assert jumlah_log("DEVICE_TAMPER_CLEARED") == sebelum + 1


class TestTidakMenyentuhJalurDarurat:
    """Batasan paling penting di file ini.

    Bila suatu saat seseorang menyambungkan tamper ke jalur emergency agar
    "lebih terlihat", test di kelas ini yang akan gagal lebih dulu.
    """

    def test_tidak_membuat_incident(self, client, api_headers, device):
        sebelum = Incident.query.count()
        kirim(client, api_headers, {"device_id": device.device_id, "tamper": True})
        assert Incident.query.count() == sebelum

    def test_tidak_membuat_command(self, client, api_headers, device):
        """Sirene tidak boleh menyala karena tamper."""
        sebelum = Command.query.count()
        kirim(client, api_headers, {"device_id": device.device_id, "tamper": True})
        assert Command.query.count() == sebelum

    def test_tidak_ada_command_pending_untuk_device(
        self, client, api_headers, device
    ):
        kirim(client, api_headers, {"device_id": device.device_id, "tamper": True})

        pending = Command.query.filter_by(
            device_id=device.device_id, status="PENDING"
        ).count()
        assert pending == 0


class TestJalurHeartbeat:
    """Heartbeat membawa keadaan tamper sebagai jaring pengaman bila
    POST /api/device/tamper gagal karena jaringan."""

    def test_heartbeat_menandai_tamper(self, client, api_headers, device):
        respons = client.post(
            "/api/device/heartbeat",
            json={"device_id": device.device_id, "tamper": True},
            headers=api_headers,
        )
        assert respons.status_code == 200
        assert Device.query.filter_by(device_id=device.device_id).first().tamper is True

    def test_heartbeat_tanpa_field_tamper_tidak_menyalakan(
        self, client, api_headers, device
    ):
        """Firmware lama tidak mengirim field ini. Ketidakhadirannya tidak
        boleh diartikan sebagai tamper aktif, karena itu akan memunculkan
        peringatan palsu untuk seluruh perangkat yang belum diperbarui."""
        respons = client.post(
            "/api/device/heartbeat",
            json={"device_id": device.device_id},
            headers=api_headers,
        )
        assert respons.status_code == 200
        assert Device.query.filter_by(device_id=device.device_id).first().tamper is False

    def test_heartbeat_berulang_tidak_membanjiri_log(
        self, client, api_headers, device
    ):
        """Heartbeat datang setiap 8 detik. Tanpa pemisahan "hanya saat
        berubah", satu jam tamper aktif menghasilkan ratusan baris log
        identik."""
        for _ in range(6):
            client.post(
                "/api/device/heartbeat",
                json={"device_id": device.device_id, "tamper": True},
                headers=api_headers,
            )

        assert jumlah_log("DEVICE_TAMPER_DETECTED") == 1


class TestTampilDiApi:
    def test_daftar_device_menyertakan_tamper_state(
        self, client, api_headers, device
    ):
        """Dashboard membaca endpoint ini untuk menampilkan penanda tamper."""
        kirim(client, api_headers, {"device_id": device.device_id, "tamper": True})

        data = client.get("/api/devices").get_json()["data"]
        cocok = [
            d for d in data["devices"] if d["device_id"] == device.device_id
        ]
        assert cocok, "device tidak muncul di /api/devices"
        assert cocok[0]["tamper_state"]["tamper"] is True

    def test_device_baru_belum_pernah_tamper(self, client, device):
        data = client.get("/api/devices").get_json()["data"]
        cocok = [
            d for d in data["devices"] if d["device_id"] == device.device_id
        ]
        state = cocok[0]["tamper_state"]

        assert state["tamper"] is False
        assert state["ever_tampered"] is False
