"""Test verifikasi tahap 1 dan tahap 2.

File ini menjaga aturan keselamatan yang tidak boleh dilanggar:

  1. SOS saja TIDAK PERNAH cukup untuk CONFIRMED.
  2. audio_confidence tinggi saja TIDAK PERNAH cukup untuk CONFIRMED.
  3. hotspot High saja TIDAK PERNAH cukup untuk CONFIRMED.
  4. LOCAL_REJECTED tidak dapat dinaikkan menjadi CONFIRMED oleh server.
  5. Bukti yang tidak tersedia TIDAK dianggap nol.

Bila salah satu test di file ini gagal, artinya perilaku keselamatan sistem
berubah — bukan sekadar test yang perlu disesuaikan.
"""

import pytest

from backend.services import verification

CONTEXT_RAWAN = {
    "summary": {
        "hotspot_risk": 0.95,
        "hotspot_level": "High",
        "hotspot_status": "OK",
        "history_score": 0.8,
        "weather": "Clear",
        "traffic_level": "Low",
        "is_dark": True,
    }
}


# --- TAHAP 1 -------------------------------------------------------------


class TestVerifikasiLokal:
    """verify_local(): cermin logika ESP32."""

    def test_sos_saja_ditolak(self):
        """SOS tanpa bukti audio harus LOCAL_REJECTED.

        Ini aturan inti: tombol SOS tidak boleh melewati verifikasi audio,
        supaya tombol yang tertekan tidak sengaja tidak membangunkan sirene.
        """
        hasil = verification.verify_local(
            sos=True, audio_confidence=0.0, audio_class="Normal", audio_threshold=0.60
        )
        assert hasil == "LOCAL_REJECTED"

    def test_sos_dengan_audio_lemah_ditolak(self):
        """Keyakinan audio di bawah ambang tetap ditolak walau ada SOS."""
        hasil = verification.verify_local(
            sos=True,
            audio_confidence=0.40,
            audio_class="Scream/Teriakan",
            audio_threshold=0.60,
        )
        assert hasil == "LOCAL_REJECTED"

    def test_sos_dengan_audio_relevan_diterima(self):
        hasil = verification.verify_local(
            sos=True,
            audio_confidence=0.80,
            audio_class="Scream/Teriakan",
            audio_threshold=0.60,
        )
        assert hasil == "LOCAL_VERIFIED"

    def test_sos_dengan_audio_sangat_kuat_diterima(self):
        """Kelas boleh salah bila suaranya sangat kuat dan SOS ditekan."""
        hasil = verification.verify_local(
            sos=True,
            audio_confidence=0.90,
            audio_class="Unknown",
            audio_threshold=0.60,
        )
        assert hasil == "LOCAL_VERIFIED"

    def test_tanpa_sos_audio_sangat_tinggi_diterima(self):
        """Korban mungkin tidak sanggup menekan tombol."""
        hasil = verification.verify_local(
            sos=False,
            audio_confidence=0.95,
            audio_class="Scream/Teriakan",
            audio_threshold=0.60,
        )
        assert hasil == "LOCAL_VERIFIED"

    def test_tanpa_sos_audio_sedang_ditolak(self):
        hasil = verification.verify_local(
            sos=False,
            audio_confidence=0.75,
            audio_class="Scream/Teriakan",
            audio_threshold=0.60,
        )
        assert hasil == "LOCAL_REJECTED"

    def test_nilai_rusak_tidak_melempar_exception(self):
        """Payload rusak harus ditolak dengan tenang, bukan membuat crash."""
        hasil = verification.verify_local(
            sos=True, audio_confidence=None, audio_class=None, audio_threshold=None
        )
        assert hasil == "LOCAL_REJECTED"


class TestKosakataAudio:
    """is_emergency_audio_class() harus mengenali DUA kosakata.

    ai_models.py memakai "Scream/Teriakan", firmware memakai "SCREAM".
    Bila hanya satu yang dikenali, bukti audio akan terbuang diam-diam.
    """

    @pytest.mark.parametrize(
        "kelas",
        [
            "Scream/Teriakan",
            "Help/Distress",
            "Impact/Benturan",
            "SCREAM",
            "CRY_FOR_HELP",
            "GLASS_BREAKING",
            "teriakan",
        ],
    )
    def test_kelas_darurat_dikenali(self, kelas):
        assert verification.is_emergency_audio_class(kelas) is True

    @pytest.mark.parametrize("kelas", ["Normal", "NONE", "SILENCE", "", None])
    def test_kelas_normal_tidak_dianggap_darurat(self, kelas):
        assert verification.is_emergency_audio_class(kelas) is False


# --- TAHAP 2 -------------------------------------------------------------


class TestBuktiTunggalTidakCukup:
    """Tidak ada satu pun bukti yang boleh memicu CONFIRMED sendirian."""

    def test_sos_saja_di_lokasi_rawan_tetap_false_alarm(self):
        hasil = verification.verify_emergency(
            {
                "sos": True,
                "audio_confidence": 0.0,
                "audio_class": "Normal",
                "audio_distress_probability": 0.0,
                "local_decision": "LOCAL_VERIFIED",
                "context": CONTEXT_RAWAN,
                "threshold": 0.70,
            }
        )
        assert hasil["decision"] == "FALSE_ALARM"

    def test_audio_maksimal_tanpa_bukti_lain_tetap_false_alarm(self):
        hasil = verification.verify_emergency(
            {
                "sos": False,
                "audio_confidence": 1.0,
                "audio_class": "Scream/Teriakan",
                "audio_distress_probability": 1.0,
                "local_decision": "LOCAL_VERIFIED",
                "context": {"summary": {"hotspot_status": "MISSING_FEATURES"}},
                "threshold": 0.70,
            }
        )
        assert hasil["decision"] == "FALSE_ALARM"

    def test_hotspot_tinggi_tanpa_bukti_lain_tetap_false_alarm(self):
        hasil = verification.verify_emergency(
            {
                "sos": False,
                "audio_confidence": 0.0,
                "audio_class": "Normal",
                "audio_distress_probability": 0.0,
                "local_decision": "LOCAL_VERIFIED",
                "context": CONTEXT_RAWAN,
                "threshold": 0.70,
            }
        )
        assert hasil["decision"] == "FALSE_ALARM"

    def test_tidak_ada_bobot_tunggal_melebihi_ambang(self):
        """Pengaman struktural terhadap perubahan bobot di masa depan.

        Bila seseorang menaikkan salah satu bobot melebihi ambang default,
        bukti tunggal akan cukup untuk CONFIRMED. Test ini mencegah hal itu
        lolos tanpa disadari.
        """
        bobot = (
            verification.WEIGHT_SOS,
            verification.WEIGHT_AUDIO,
            verification.WEIGHT_HOTSPOT,
            verification.WEIGHT_HISTORY,
            verification.WEIGHT_ENV,
            verification.WEIGHT_EMERGENCY_STATE,
        )
        assert max(bobot) < 0.70


class TestBuktiBerlapis:
    def test_bukti_berlapis_menghasilkan_confirmed(self):
        hasil = verification.verify_emergency(
            {
                "sos": True,
                "audio_confidence": 0.95,
                "audio_class": "Scream/Teriakan",
                "audio_distress_probability": 0.95,
                "local_decision": "LOCAL_VERIFIED",
                "context": CONTEXT_RAWAN,
                "emergency_state": "EMERGENCY",
                "emergency_state_support": 1.0,
                "threshold": 0.70,
            }
        )
        assert hasil["decision"] == "CONFIRMED"
        assert hasil["score"] >= 0.70

    def test_metode_dilaporkan_rule_based(self):
        """Sistem tidak boleh mengaku memakai AI untuk keputusan ini."""
        hasil = verification.verify_emergency(
            {
                "sos": True,
                "audio_confidence": 0.95,
                "audio_class": "Scream/Teriakan",
                "local_decision": "LOCAL_VERIFIED",
                "context": CONTEXT_RAWAN,
                "threshold": 0.70,
            }
        )
        assert hasil["method"] == "RULE_BASED_SECOND_LEVEL"


class TestServerTidakMelonggarkan:
    def test_local_rejected_tidak_dapat_dinaikkan(self):
        """Verifikasi tahap 2 hanya boleh memperketat."""
        hasil = verification.verify_emergency(
            {
                "sos": True,
                "audio_confidence": 1.0,
                "audio_class": "Scream/Teriakan",
                "audio_distress_probability": 1.0,
                "local_decision": "LOCAL_REJECTED",
                "context": CONTEXT_RAWAN,
                "emergency_state_support": 1.0,
                "threshold": 0.70,
            }
        )
        assert hasil["decision"] == "FALSE_ALARM"
        assert hasil["score"] == 0.0


class TestBuktiTidakTersedia:
    """Bukti yang tidak diketahui tidak boleh diperlakukan sebagai nol.

    Nol berarti "lokasi aman"; tidak tersedia berarti "tidak diketahui".
    Menyamakan keduanya akan menekan skor dan berpotensi menolak kejadian
    nyata di lokasi yang belum dikonfigurasi.
    """

    def _data(self, hotspot_risk, hotspot_status):
        return {
            "sos": True,
            "audio_confidence": 0.95,
            "audio_class": "Scream/Teriakan",
            "audio_distress_probability": 0.95,
            "local_decision": "LOCAL_VERIFIED",
            "context": {
                "summary": {
                    "hotspot_risk": hotspot_risk,
                    "hotspot_status": hotspot_status,
                    "history_score": 0.6,
                    "weather": "Clear",
                    "traffic_level": "Low",
                    "is_dark": True,
                }
            },
            "emergency_state_support": 1.0,
            "threshold": 0.70,
        }

    def test_hotspot_none_dikeluarkan_dari_perhitungan(self):
        hasil = verification.verify_emergency(self._data(None, "MISSING_FEATURES"))
        komponen = hasil["components"]
        assert komponen["hotspot"] is None
        assert komponen["weight_used"] < 1.0

    def test_hotspot_none_tidak_menghalangi_confirmed(self):
        hasil = verification.verify_emergency(self._data(None, "MISSING_FEATURES"))
        assert hasil["decision"] == "CONFIRMED"

    def test_hotspot_nol_berbeda_dari_hotspot_none(self):
        """Skor "aman" (0.0) harus lebih rendah daripada "tidak diketahui"."""
        aman = verification.verify_emergency(self._data(0.0, "OK"))
        tidak_tahu = verification.verify_emergency(self._data(None, "MISSING_FEATURES"))
        assert aman["score"] < tidak_tahu["score"]

    def test_alasan_menjelaskan_hotspot_tidak_tersedia(self):
        hasil = verification.verify_emergency(self._data(None, "MISSING_FEATURES"))
        assert "hotspot tidak tersedia" in hasil["reason"]


class TestKompatibilitasBentukKonteks:
    """Bentuk konteks lama (datar) harus tetap terbaca."""

    def test_konteks_datar_tanpa_summary(self):
        hasil = verification.verify_emergency(
            {
                "sos": True,
                "audio_confidence": 0.95,
                "audio_class": "Scream/Teriakan",
                "local_decision": "LOCAL_VERIFIED",
                "context": {
                    "hotspot_risk": 0.9,
                    "hotspot_level": "High",
                    "history_score": 0.7,
                    "weather": "RAIN",
                    "traffic": "QUIET",
                },
                "threshold": 0.70,
            }
        )
        assert hasil["components"]["hotspot"] is not None


class TestModulEksternal:
    def test_default_tidak_ada_modul_eksternal(self):
        """Tanpa pendaftaran, verifikasi harus rule-based."""
        assert verification.ai_verifier_active() is False

    def test_modul_eksternal_gagal_jatuh_ke_rule_based(self):
        """Kegagalan modul eksternal tidak boleh menggagalkan emergency."""

        def modul_rusak(data):
            raise RuntimeError("model tidak tersedia")

        verification.register_ai_verifier(modul_rusak)
        try:
            hasil = verification.run_verification(
                {
                    "sos": True,
                    "audio_confidence": 0.95,
                    "audio_class": "Scream/Teriakan",
                    "audio_distress_probability": 0.95,
                    "local_decision": "LOCAL_VERIFIED",
                    "context": CONTEXT_RAWAN,
                    "emergency_state_support": 1.0,
                    "threshold": 0.70,
                }
            )
            assert hasil["method"] == "RULE_BASED_FALLBACK"
            assert hasil["decision"] in ("CONFIRMED", "FALSE_ALARM")
        finally:
            # Dipulihkan agar tidak mempengaruhi test lain.
            verification.register_ai_verifier(None)
            verification._ai_verifier = None
