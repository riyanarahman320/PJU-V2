"""Test simulator perangkat, khususnya penanganan `event_id`.

MENGAPA SIMULATOR PERLU DIUJI
-----------------------------
Simulator adalah satu-satunya cara menguji alur API tanpa hardware. Bila
perilakunya menyimpang dari firmware, pengujian tanpa board memberi rasa aman
yang salah: alur terlihat benar di simulator padahal perangkat sungguhan
berperilaku lain.

Yang dijaga di sini adalah kontrak idempotency: satu kejadian = satu event_id,
dan retry memakai nilai yang sama.

Server tidak pernah dihubungi. `_request` digantikan sehingga payload yang
hendak dikirim dapat diperiksa langsung, dan test tidak bergantung pada server
yang berjalan maupun jaringan.
"""

import pytest

from simulation.simulator import SimulatorPerangkat


@pytest.fixture
def perangkat():
    """Simulator yang tidak pernah menyentuh jaringan.

    Setiap payload yang dikirim dicatat di `perangkat.terkirim`, sehingga test
    dapat memeriksa apa yang sebenarnya akan diterima server.
    """
    alat = SimulatorPerangkat(
        base_url="http://127.0.0.1:5000",
        device_id="SIM-TEST-001",
        api_key="kunci-uji",
        latitude=-6.9200,
        longitude=107.6400,
    )

    alat.terkirim = []
    # Incident id dibuat berurutan; server sungguhan yang menentukan apakah
    # sebuah request menghasilkan incident baru, jadi di sini nilainya hanya
    # perlu berbeda supaya perubahan event_id dapat ditelusuri.
    alat.balasan = {
        "incident_id": "INC-SIM-0001",
        "server_decision": "CONFIRMED",
        "server_score": 0.9,
        "verification_method": "RULE_BASED_SECOND_LEVEL",
        "duplicate": False,
        "context": {},
    }

    def request_palsu(method, path, payload=None):
        alat.terkirim.append({"method": method, "path": path, "payload": payload})
        return 200, {"data": dict(alat.balasan)}

    alat._request = request_palsu
    return alat


def siapkan_audio_lolos(alat):
    """Nilai audio yang melewati verifikasi lokal tahap 1."""
    alat.audio_confidence = 0.92
    alat.audio_class = "SCREAM"


def payload_emergency_terakhir(alat):
    for catatan in reversed(alat.terkirim):
        if catatan["path"] == "/api/emergency/evaluate":
            return catatan["payload"]
    return None


class TestFormatEventId:
    """Format harus sama dengan firmware supaya keduanya dapat dibandingkan."""

    def test_event_id_memakai_bootid_dan_nomor_urut(self, perangkat):
        siapkan_audio_lolos(perangkat)

        perangkat.kirim_emergency(sos=True)

        assert perangkat.current_event_id == f"{perangkat.boot_id}-1"

    def test_boot_id_delapan_karakter_heksadesimal(self, perangkat):
        """Sama seperti String(bootId, HEX) di firmware."""
        assert len(perangkat.boot_id) == 8
        int(perangkat.boot_id, 16)  # melempar ValueError bila bukan heksadesimal

    def test_boot_id_berbeda_antar_proses_simulator(self):
        """Dua sesi tidak boleh memakai ruang nilai yang sama.

        Bila boot_id dapat terulang, kejadian baru pada sesi kedua berisiko
        dianggap retry dari sesi pertama lalu diabaikan server.
        """
        argumen = dict(
            base_url="http://127.0.0.1:5000",
            device_id="SIM-TEST-001",
            api_key="kunci-uji",
            latitude=-6.9200,
            longitude=107.6400,
        )

        kumpulan = {SimulatorPerangkat(**argumen).boot_id for _ in range(20)}

        assert len(kumpulan) == 20

    def test_event_id_tidak_melewati_batas_panjang_server(self, perangkat):
        """Server menolak lebih dari 64 karakter dengan HTTP 400."""
        siapkan_audio_lolos(perangkat)

        perangkat.kirim_emergency(sos=True)

        assert len(perangkat.current_event_id) <= 64


class TestEventIdDikirim:
    """Kunci tidak berguna bila tidak sampai ke server."""

    def test_event_id_disertakan_di_payload(self, perangkat):
        siapkan_audio_lolos(perangkat)

        perangkat.kirim_emergency(sos=True)

        payload = payload_emergency_terakhir(perangkat)
        assert payload["event_id"] == perangkat.current_event_id

    def test_payload_lain_tidak_berubah(self, perangkat):
        """Kompatibilitas: field yang sudah ada harus tetap seperti sebelumnya."""
        siapkan_audio_lolos(perangkat)

        perangkat.kirim_emergency(sos=True)

        payload = payload_emergency_terakhir(perangkat)
        assert payload["device_id"] == "SIM-TEST-001"
        assert payload["sos"] is True
        assert payload["audio_confidence"] == 0.92
        assert payload["audio_class"] == "SCREAM"
        assert payload["local_decision"] == "LOCAL_VERIFIED"
        assert payload["latitude"] == -6.9200
        assert payload["longitude"] == 107.6400


class TestRetryMemakaiEventIdSama:
    """Inti idempotency di sisi perangkat."""

    def test_retry_mengirim_event_id_yang_sama(self, perangkat):
        siapkan_audio_lolos(perangkat)
        perangkat.kirim_emergency(sos=True)
        event_pertama = perangkat.current_event_id

        perangkat.kirim_emergency_ulang()

        assert payload_emergency_terakhir(perangkat)["event_id"] == event_pertama

    def test_retry_tidak_menaikkan_penghitung_kejadian(self, perangkat):
        """Retry bukan kejadian baru, jadi tidak boleh menambah hitungan."""
        siapkan_audio_lolos(perangkat)
        perangkat.kirim_emergency(sos=True)

        perangkat.kirim_emergency_ulang()

        assert perangkat.event_counter == 1

    def test_retry_berkali_kali_tetap_satu_kunci(self, perangkat):
        siapkan_audio_lolos(perangkat)
        perangkat.kirim_emergency(sos=True)
        event_pertama = perangkat.current_event_id

        for _ in range(4):
            perangkat.kirim_emergency_ulang()

        dikirim = [
            catatan["payload"]["event_id"]
            for catatan in perangkat.terkirim
            if catatan["path"] == "/api/emergency/evaluate"
        ]
        assert dikirim == [event_pertama] * 5

    def test_retry_mempertahankan_nilai_sos_kejadian(self, perangkat):
        """Retry harus melaporkan kejadian yang sama, termasuk status SOS-nya.

        Firmware memakai sosLatched untuk ini: kejadian yang sudah berjalan
        tidak berubah hanya karena tombol sudah dilepas.
        """
        perangkat.audio_confidence = 0.95
        perangkat.audio_class = "SCREAM"
        perangkat.kirim_emergency(sos=False)

        perangkat.kirim_emergency_ulang()

        assert payload_emergency_terakhir(perangkat)["sos"] is False

    def test_retry_tanpa_kejadian_berjalan_tidak_mengirim_apa_pun(self, perangkat):
        """Tidak ada yang perlu dikirim ulang bila tidak ada kejadian."""
        hasil = perangkat.kirim_emergency_ulang()

        assert hasil is None
        assert perangkat.terkirim == []


class TestKejadianBaruMemakaiKunciBaru:
    """Idempotency tidak boleh menelan kejadian nyata berikutnya."""

    def test_kejadian_kedua_memakai_event_id_berbeda(self, perangkat):
        siapkan_audio_lolos(perangkat)
        perangkat.kirim_emergency(sos=True)
        pertama = perangkat.current_event_id

        perangkat.reset()
        siapkan_audio_lolos(perangkat)
        perangkat.kirim_emergency(sos=True)

        assert perangkat.current_event_id != pertama
        assert perangkat.event_counter == 2

    def test_nomor_urut_tidak_kembali_ke_awal_setelah_reset(self, perangkat):
        """Penghitung harus terus naik.

        Bila reset mengembalikannya ke nol, kejadian setelah reset akan memakai
        kunci yang sama dengan kejadian pertama dan server akan menganggapnya
        retry — emergency nyata hilang.
        """
        siapkan_audio_lolos(perangkat)
        perangkat.kirim_emergency(sos=True)
        perangkat.reset()
        siapkan_audio_lolos(perangkat)
        perangkat.kirim_emergency(sos=True)
        perangkat.reset()
        siapkan_audio_lolos(perangkat)
        perangkat.kirim_emergency(sos=True)

        assert perangkat.current_event_id == f"{perangkat.boot_id}-3"

    def test_reset_mengosongkan_kunci_kejadian(self, perangkat):
        """Setelah kejadian ditutup, tidak ada lagi yang boleh di-retry."""
        siapkan_audio_lolos(perangkat)
        perangkat.kirim_emergency(sos=True)

        perangkat.reset()

        assert perangkat.current_event_id is None
        assert perangkat.kirim_emergency_ulang() is None


class TestVerifikasiLokalTidakBerubah:
    """Perubahan idempotency tidak boleh menyentuh keputusan tahap 1."""

    def test_local_rejected_tidak_membuat_event_id(self, perangkat):
        """Kejadian yang ditolak lokal tidak pernah ada bagi server.

        Membuat kunci di sini akan memboroskan nomor urut dan membuat log
        menyesatkan: seolah ada kejadian yang dilaporkan padahal tidak.
        """
        perangkat.audio_confidence = 0.20
        perangkat.audio_class = "Normal"

        hasil = perangkat.kirim_emergency(sos=True)

        assert hasil is None
        assert perangkat.current_event_id is None
        assert perangkat.event_counter == 0
        assert perangkat.terkirim == []

    def test_sos_saja_tetap_ditolak_lokal(self, perangkat):
        """Aturan keselamatan inti: SOS tidak melewati verifikasi audio."""
        perangkat.audio_confidence = 0.0
        perangkat.audio_class = "Normal"

        assert perangkat.verifikasi_lokal(sos=True) == "LOCAL_REJECTED"

    def test_strobe_tidak_menyala_saat_ditolak_lokal(self, perangkat):
        perangkat.audio_confidence = 0.20
        perangkat.audio_class = "Normal"

        perangkat.kirim_emergency(sos=True)

        assert perangkat.local_emergency_active is False

    def test_strobe_menyala_sebelum_hasil_server(self, perangkat):
        """Fail-safe lokal tidak menunggu jaringan."""
        siapkan_audio_lolos(perangkat)

        perangkat.kirim_emergency(sos=True)

        assert perangkat.local_emergency_active is True
