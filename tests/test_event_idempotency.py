"""Test idempotency POST /api/emergency/evaluate.

MASALAH YANG DIUJI
------------------
ESP32 mengirim laporan emergency lewat jaringan seluler yang tidak dapat
diandalkan. Bila POST sampai ke server dan incident berhasil dibuat, tetapi
responsnya hilang karena timeout, perangkat tidak dapat membedakan keadaan itu
dari "request tidak pernah sampai". Perangkat karena itu mengirim ulang.

Tanpa idempotency key, retry semacam itu menghasilkan incident KEDUA untuk satu
kejadian nyata: operator melihat dua baris untuk satu teriakan, statistik
terhitung ganda, dan command sirene dibuat dua kali.

`event_id` adalah kuncinya: satu kejadian SOS = satu event_id, dipakai kembali
pada setiap percobaan pengiriman.

Layanan konteks eksternal tidak pernah dipanggil di sini: fixture
`konteks_stabil` menggantikan Open-Meteo dan TomTom dengan nilai tetap,
sehingga hasil test tidak bergantung pada jaringan.
"""

from backend.models import Incident

ENDPOINT = "/api/emergency/evaluate"


def kirim(client, headers, payload):
    """Pembantu kecil supaya maksud setiap test tetap terbaca."""
    return client.post(ENDPOINT, json=payload, headers=headers)


class TestRetryTidakMembuatDuplicate:
    """Inti perbaikan: event_id yang sama tidak boleh membuat incident kedua."""

    def test_dua_request_event_id_sama_hanya_satu_incident(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Skenario timeout: perangkat mengirim dua kali, kejadiannya satu."""
        payload = dict(payload_emergency, event_id="EVT-1001")

        pertama = kirim(client, api_headers, payload)
        kedua = kirim(client, api_headers, payload)

        assert pertama.status_code == 200
        assert kedua.status_code == 200
        assert Incident.query.count() == 1

    def test_retry_mengembalikan_incident_id_yang_sama(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Perangkat harus menerima ID yang sama, bukan ID baru.

        Ini yang membuat perangkat dapat menyimpan satu activeIncidentId dan
        mencocokkannya dengan command yang datang kemudian.
        """
        payload = dict(payload_emergency, event_id="EVT-1002")

        pertama = kirim(client, api_headers, payload).get_json()["data"]
        kedua = kirim(client, api_headers, payload).get_json()["data"]

        assert kedua["incident_id"] == pertama["incident_id"]

    def test_retry_ditandai_duplicate(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Request pertama bukan duplicate; retry ditandai duplicate.

        Penanda ini hanya untuk penelusuran masalah. Perangkat tidak wajib
        membacanya, karena isi respons lainnya sudah sama.
        """
        payload = dict(payload_emergency, event_id="EVT-1003")

        assert kirim(client, api_headers, payload).get_json()["data"][
            "duplicate"
        ] is False
        assert kirim(client, api_headers, payload).get_json()["data"][
            "duplicate"
        ] is True

    def test_retry_berkali_kali_tetap_satu_incident(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Perangkat dengan jaringan buruk dapat mencoba lebih dari dua kali."""
        payload = dict(payload_emergency, event_id="EVT-1004")

        hasil = [
            kirim(client, api_headers, payload).get_json()["data"]["incident_id"]
            for _ in range(5)
        ]

        assert len(set(hasil)) == 1
        assert Incident.query.count() == 1

    def test_event_id_dikembalikan_di_respons(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Perangkat dapat memastikan server memang mengenali kuncinya."""
        payload = dict(payload_emergency, event_id="EVT-1005")

        data = kirim(client, api_headers, payload).get_json()["data"]

        assert data["event_id"] == "EVT-1005"


class TestRetryKonsisten:
    """Retry harus mengembalikan respons yang ekuivalen, bukan sekadar 200."""

    def test_keputusan_verifikasi_tidak_berubah_pada_retry(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Retry membaca incident tersimpan, jadi keputusannya tidak dihitung ulang.

        Penting karena verifikasi tahap 2 memakai data konteks dan riwayat yang
        berubah menurut waktu: menjalankannya ulang dapat menghasilkan keputusan
        berbeda untuk kejadian yang sama.
        """
        payload = dict(payload_emergency, event_id="EVT-2001")

        pertama = kirim(client, api_headers, payload).get_json()["data"]
        kedua = kirim(client, api_headers, payload).get_json()["data"]

        assert kedua["server_decision"] == pertama["server_decision"]
        assert kedua["server_score"] == pertama["server_score"]
        assert kedua["local_decision"] == pertama["local_decision"]
        assert kedua["verification_method"] == pertama["verification_method"]
        assert kedua["status"] == pertama["status"]

    def test_bentuk_respons_retry_sama_dengan_request_pertama(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Firmware memakai satu jalur parsing untuk kedua respons.

        Bila retry mengembalikan bentuk berbeda, firmware harus membedakan
        keduanya; justru itu yang ingin dihindari.
        """
        payload = dict(payload_emergency, event_id="EVT-2002")

        pertama = kirim(client, api_headers, payload).get_json()["data"]
        kedua = kirim(client, api_headers, payload).get_json()["data"]

        assert set(kedua.keys()) == set(pertama.keys())
        assert set(kedua["context"].keys()) == set(pertama["context"].keys())
        assert set(kedua["audio"].keys()) == set(pertama["audio"].keys())

    def test_retry_tidak_membuat_command_tambahan(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Command ganda berarti sirene dinyalakan dua kali untuk satu kejadian."""
        from backend.models import Command

        payload = dict(payload_emergency, event_id="EVT-2003")

        kirim(client, api_headers, payload)
        jumlah_setelah_pertama = Command.query.count()
        kirim(client, api_headers, payload)

        assert Command.query.count() == jumlah_setelah_pertama

    def test_command_yang_ada_tetap_dikembalikan_pada_retry(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Retry tetap membawa command, karena respons pertama mungkin hilang.

        Bila respons pertama tidak pernah diterima perangkat, retry adalah satu-
        satunya kesempatan perangkat mengetahui command yang sudah dibuat.
        """
        payload = dict(payload_emergency, event_id="EVT-2004")

        pertama = kirim(client, api_headers, payload).get_json()["data"]
        kedua = kirim(client, api_headers, payload).get_json()["data"]

        assert kedua["command"] == pertama["command"]


class TestEventIdBerbeda:
    """Idempotency tidak boleh menelan kejadian nyata yang berikutnya."""

    def test_event_id_berbeda_membuat_incident_baru(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Dua kejadian terpisah dari device yang sama harus tetap dua incident."""
        pertama = kirim(
            client, api_headers, dict(payload_emergency, event_id="EVT-3001")
        ).get_json()["data"]
        kedua = kirim(
            client, api_headers, dict(payload_emergency, event_id="EVT-3002")
        ).get_json()["data"]

        assert kedua["incident_id"] != pertama["incident_id"]
        assert kedua["duplicate"] is False
        assert Incident.query.count() == 2

    def test_event_id_sama_dari_device_berbeda_tetap_terpisah(
        self,
        client,
        api_headers,
        device,
        device_lengkap,
        payload_emergency,
        konteks_stabil,
    ):
        """Kunci dicocokkan per device, bukan global.

        event_id dibuat dari penghitung lokal perangkat (millis()), sehingga dua
        perangkat berbeda wajar menghasilkan nilai yang sama. Menganggapnya satu
        kejadian akan MENGHILANGKAN emergency nyata di perangkat kedua.
        """
        satu = dict(payload_emergency, device_id=device.device_id, event_id="EVT-4000")
        dua = dict(
            payload_emergency, device_id=device_lengkap.device_id, event_id="EVT-4000"
        )

        hasil_satu = kirim(client, api_headers, satu).get_json()["data"]
        hasil_dua = kirim(client, api_headers, dua).get_json()["data"]

        assert hasil_dua["incident_id"] != hasil_satu["incident_id"]
        assert hasil_dua["duplicate"] is False
        assert Incident.query.count() == 2


class TestKompatibilitasFirmwareLama:
    """event_id opsional: firmware lama harus tetap bekerja seperti sebelumnya."""

    def test_tanpa_event_id_perilaku_lama_dipertahankan(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Tanpa kunci, server tidak dapat mengenali retry; setiap request baru.

        Ini bukan kemunduran, melainkan batas yang jujur: tanpa event_id server
        memang tidak memiliki dasar untuk menyatakan dua request adalah satu
        kejadian.
        """
        kirim(client, api_headers, payload_emergency)
        kirim(client, api_headers, payload_emergency)

        assert Incident.query.count() == 2

    def test_tanpa_event_id_respons_tetap_menyertakan_field(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Field tetap ada dengan nilai null, supaya bentuk respons konsisten."""
        data = kirim(client, api_headers, payload_emergency).get_json()["data"]

        assert data["event_id"] is None
        assert data["duplicate"] is False

    def test_event_id_kosong_tidak_dianggap_kunci(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """String kosong TIDAK boleh menjadi kunci.

        Bila "" diperlakukan sebagai kunci yang sah, kejadian pertama dari
        firmware yang mengirim string kosong akan mengunci seluruh kejadian
        berikutnya: emergency nyata kedua tidak akan pernah tercatat.
        """
        payload = dict(payload_emergency, event_id="   ")

        pertama = kirim(client, api_headers, payload)
        kedua = kirim(client, api_headers, payload)

        assert pertama.status_code == 200
        assert kedua.status_code == 200
        assert Incident.query.count() == 2
        assert pertama.get_json()["data"]["event_id"] is None


class TestValidasiEventId:
    """event_id datang dari jaringan, jadi harus diperiksa seperti input lain."""

    def test_event_id_bukan_string_ditolak(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        payload = dict(payload_emergency, event_id=12345)

        respons = kirim(client, api_headers, payload)

        assert respons.status_code == 400
        assert Incident.query.count() == 0

    def test_event_id_terlalu_panjang_ditolak(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Batas panjang mengikuti lebar kolom database (64 karakter)."""
        payload = dict(payload_emergency, event_id="X" * 65)

        respons = kirim(client, api_headers, payload)

        assert respons.status_code == 400
        assert Incident.query.count() == 0

    def test_event_id_panjang_maksimum_diterima(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Tepat 64 karakter masih sah; batasnya inklusif."""
        payload = dict(payload_emergency, event_id="X" * 64)

        respons = kirim(client, api_headers, payload)

        assert respons.status_code == 200
        assert respons.get_json()["data"]["event_id"] == "X" * 64


class TestIncidentTersimpan:
    """event_id harus benar-benar tersimpan, bukan hanya dipantulkan."""

    def test_event_id_tersimpan_di_database(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Kunci hanya berguna bila bertahan setelah server restart."""
        payload = dict(payload_emergency, event_id="EVT-5001")

        kirim(client, api_headers, payload)

        incident = Incident.query.filter_by(event_id="EVT-5001").first()
        assert incident is not None
        assert incident.device_id == device.device_id

    def test_retry_tidak_menambah_log_verifikasi(
        self, client, api_headers, device, payload_emergency, konteks_stabil
    ):
        """Retry tidak menjalankan verifikasi, jadi tidak ada log baru.

        Selain menghemat pemanggilan model dan API konteks, ini menjaga riwayat
        device tetap benar: log kejadian ganda akan menggeser history_score dan
        mengubah penilaian kejadian berikutnya.
        """
        from backend.models import Log

        payload = dict(payload_emergency, event_id="EVT-5002")

        kirim(client, api_headers, payload)
        jumlah_setelah_pertama = Log.query.count()
        kirim(client, api_headers, payload)

        assert Log.query.count() == jumlah_setelah_pertama