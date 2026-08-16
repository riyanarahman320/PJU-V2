"""Adapter lalu lintas.

Membungkus core/traffic_service.py (milik pengguna, TomTom Flow Segment Data)
tanpa mengubah isinya. Fungsi get_traffic(latitude, longitude) dipertahankan.

Tambahan pada lapisan adapter ini:

1. Membedakan tiga keadaan yang pada core sama-sama menghasilkan
   traffic_level='Low':
       - API sukses dan jalan memang lengang  -> REAL_API
       - TOMTOM_API_KEY belum diisi           -> FALLBACK
       - API error / timeout                  -> ERROR
   Perbedaan ini penting supaya dashboard tidak menampilkan fallback
   sebagai kondisi lalu lintas sebenarnya.
2. Menerjemahkan traffic_level ke kosakata model (kebetulan sudah sama:
   Low/Medium/High), tetap lewat vocab.py agar konsisten.
3. Tidak memanggil API bila koordinat belum tersedia.

API key dibaca oleh core dari environment variable TOMTOM_API_KEY.
Tidak ada key yang ditulis di source code.
"""

from backend.services.context import vocab
from backend.services.context.core import traffic_service as core_traffic


def _hasil_tidak_tersedia(alasan: str, status: str = "NOT_AVAILABLE") -> dict:
    return {
        "traffic_level": None,
        "traffic_level_model": None,
        "current_speed": None,
        "free_flow_speed": None,
        "speed_ratio": None,
        "confidence": None,
        "status": status,
        "source": status,
        "message": alasan,
    }


def get_traffic(latitude, longitude) -> dict:
    """Ambil kondisi lalu lintas untuk satu titik koordinat.

    Return dict dengan kunci:
        traffic_level        : Low | Medium | High, atau None
        traffic_level_model  : nilai untuk fitur Traffic_Level pada model
        current_speed        : km/jam, atau None
        free_flow_speed      : km/jam, atau None
        speed_ratio          : current/free_flow, atau None
        confidence           : keyakinan dari TomTom, atau None
        status               : REAL_API | FALLBACK | ERROR | NOT_AVAILABLE
        source               : TOMTOM | FALLBACK | ERROR | NOT_AVAILABLE
    """
    if latitude is None or longitude is None:
        return _hasil_tidak_tersedia(
            "Koordinat device belum tersedia, API lalu lintas tidak dipanggil."
        )

    try:
        mentah = core_traffic.get_traffic(latitude, longitude)
    except Exception as error:  # noqa: BLE001 - jangan sampai crash server
        return _hasil_tidak_tersedia(f"{type(error).__name__}: {error}", "ERROR")

    status_core = str(mentah.get("status", "")).lower()

    if status_core == "fallback":
        # Tidak ada API key. Angka 'Low' dari core adalah nilai default,
        # bukan hasil pengukuran, jadi tidak dipakai sebagai fitur model.
        return {
            "traffic_level": mentah.get("traffic_level"),
            "traffic_level_model": None,
            "current_speed": None,
            "free_flow_speed": None,
            "speed_ratio": None,
            "confidence": None,
            "status": "FALLBACK",
            "source": "FALLBACK",
            "message": mentah.get(
                "message", "TOMTOM_API_KEY belum tersedia."
            ),
        }

    if status_core != "success":
        return {
            "traffic_level": mentah.get("traffic_level"),
            "traffic_level_model": None,
            "current_speed": None,
            "free_flow_speed": None,
            "speed_ratio": None,
            "confidence": None,
            "status": "ERROR",
            "source": "ERROR",
            "message": mentah.get("message", "API lalu lintas gagal."),
        }

    level = mentah.get("traffic_level")

    return {
        "traffic_level": level,
        "traffic_level_model": vocab.map_traffic(level),
        "current_speed": mentah.get("current_speed"),
        "free_flow_speed": mentah.get("free_flow_speed"),
        "speed_ratio": mentah.get("speed_ratio"),
        "confidence": mentah.get("confidence"),
        "status": "REAL_API",
        "source": "TOMTOM",
    }
