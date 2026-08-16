"""Adapter untuk core_emergency_service.evaluate_emergency().

File asli (AI/model/emergency_service.py) dipertahankan utuh di
backend/services/core_emergency_service.py dan TIDAK diubah isinya.

MENGAPA PERLU ADAPTER, BUKAN DIPAKAI LANGSUNG
---------------------------------------------
Implementasi asli bertentangan dengan tiga aturan arsitektur ASEP-JAGA:

1. `if sos and audio_confidence >= 0.70: return EMERGENCY`
   -> SOS + confidence tinggi langsung menjadi keputusan akhir.
   Arsitektur mewajibkan keputusan akhir melewati verifikasi tahap 2
   dengan konteks lengkap, bukan dua nilai saja.

2. `if sos: return SUSPICIOUS dengan local_action=True`
   -> SOS saja sudah memicu aksi lokal, tanpa audio verification.
   Arsitektur mewajibkan: SOS TIDAK BOLEH BYPASS AUDIO VERIFICATION.

3. Output NORMAL / SUSPICIOUS / EMERGENCY tidak sesuai kontrak sistem yang
   memakai LOCAL_VERIFIED / LOCAL_REJECTED (tahap 1) dan
   CONFIRMED / FALSE_ALARM (tahap 2).

SOLUSI YANG DIPAKAI
-------------------
Fungsi asli tetap dipanggil, tetapi hasilnya diturunkan perannya menjadi
SATU BUTIR EVIDENCE bernama `emergency_state`, bukan keputusan.
Field `local_action` dan `server_confirmation` dari fungsi asli TIDAK dipakai
untuk mengendalikan strobe maupun keputusan server, karena keduanya berasal
dari logika yang mem-bypass audio verification.

Keputusan tahap 1 tetap milik verification.verify_local() (cermin logika
ESP32). Keputusan tahap 2 tetap milik verification.verify_emergency().
"""

from backend.services import core_emergency_service

# Pemetaan emergency_state -> bobot dukungan (0.0 - 1.0).
# Nilai ini dipakai sebagai salah satu komponen skor tahap 2, BUKAN sebagai
# keputusan. Bobotnya kecil, lihat verification.WEIGHT_EMERGENCY_STATE.
STATE_SUPPORT = {
    "EMERGENCY": 1.0,
    "SUSPICIOUS": 0.5,
    "NORMAL": 0.0,
}


def evaluate_as_evidence(
    *, sos: bool, audio_confidence: float, hotspot_level=None
) -> dict:
    """Jalankan fungsi asli dan kemas hasilnya sebagai evidence.

    Parameter
    ---------
    sos : bool
        Status tombol SOS.
    audio_confidence : float
        Keyakinan audio 0.0-1.0.
    hotspot_level : str | None
        Label hotspot dari Random Forest (High/Medium/Low). Fungsi asli
        mengharapkan string; None diterjemahkan menjadi "Low" oleh fungsi
        asli itu sendiri.

    Return
    ------
    dict:
        emergency_state    : NORMAL | SUSPICIOUS | EMERGENCY (evidence)
        state_support      : 0.0-1.0, bobot dukungan untuk skoring tahap 2
        reason             : alasan dari fungsi asli
        status             : OK | ERROR
        note               : penegasan bahwa ini bukan keputusan akhir

    Tidak pernah melempar exception.
    """
    try:
        hasil = core_emergency_service.evaluate_emergency(
            sos=sos,
            audio_confidence=audio_confidence,
            hotspot_risk=hotspot_level,
        )

        state = str(hasil.get("emergency_state", "NORMAL")).upper()

        return {
            "emergency_state": state,
            "state_support": STATE_SUPPORT.get(state, 0.0),
            "reason": hasil.get("reason", ""),
            "confidence": hasil.get("confidence"),
            "status": "OK",
            # Penegasan eksplisit: field local_action / server_confirmation
            # dari fungsi asli sengaja diabaikan.
            "note": (
                "emergency_state dipakai sebagai evidence tahap 2. "
                "local_action dan server_confirmation dari implementasi asli "
                "tidak dipakai karena melewati audio verification."
            ),
            "ignored_fields": {
                "local_action": hasil.get("local_action"),
                "server_confirmation": hasil.get("server_confirmation"),
            },
        }

    except Exception as error:  # noqa: BLE001 - fail-safe
        return {
            "emergency_state": "NORMAL",
            "state_support": 0.0,
            "reason": "",
            "confidence": None,
            "status": "ERROR",
            "error": f"{type(error).__name__}: {error}",
        }
