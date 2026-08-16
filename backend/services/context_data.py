"""Adapter kompatibilitas untuk context engine.


=========================================================================
STATUS FILE INI: LAPISAN KOMPATIBILITAS, BUKAN LAGI SUMBER DATA MOCK
=========================================================================
Sebelum integrasi, file ini berisi DEVELOPMENT MOCK: nilai cuaca, lalu
lintas, dan hotspot dihasilkan secara deterministik dari device_id tanpa
memanggil layanan apa pun.

Seluruh mock tersebut SUDAH DIGANTI oleh implementasi nyata di
backend/services/context/:

    cuaca       -> Open-Meteo               (context/weather_service.py)
    lalu lintas -> TomTom                   (context/traffic_service.py)
    pencahayaan -> estimasi jam + cuaca     (context/lighting_service.py)
    hotspot     -> random_forest_pipeline   (context/hotspot_service.py)
    riwayat     -> tabel incidents          (context/history_service.py)

File ini dipertahankan HANYA agar kode dan test yang sudah memanggil
`context_data.collect_context()` atau `context_data.get_*()` tidak rusak.
Seluruh fungsi di sini hanya meneruskan ke context engine.

Untuk kode baru, panggil langsung:

    from backend.services.context import build_context
    context = build_context(device_id, latitude, longitude)
=========================================================================
"""

from backend.services.context import build_context
from backend.services.context import history_service as _history_service


def collect_context(device_id: str, latitude=None, longitude=None) -> dict:
    """Kumpulkan seluruh data konteks untuk satu incident.

    Meneruskan ke context engine. Return-nya adalah CONTEXT OBJECT lengkap
    (lihat services/context/builder.py), yang berisi kunci ringkasan lama
    di dalam context["summary"].
    """
    return build_context(device_id, latitude, longitude)


def get_hotspot_risk(device_id: str, latitude=None, longitude=None):
    """Hotspot risk 0.0-1.0 dari Random Forest.

    Mengembalikan None bila model tidak dapat dipanggil, misalnya karena
    Population_Density belum diisi. None berarti TIDAK DIKETAHUI, bukan nol.
    """
    context = build_context(device_id, latitude, longitude)
    return context["summary"].get("hotspot_risk")


def get_weather(device_id: str, latitude=None, longitude=None):
    """Kondisi cuaca dari Open-Meteo. None bila API gagal."""
    context = build_context(device_id, latitude, longitude)
    return context["summary"].get("weather")


def get_traffic(device_id: str, latitude=None, longitude=None):
    """Tingkat lalu lintas dari TomTom. None bila tidak tersedia."""
    context = build_context(device_id, latitude, longitude)
    return context["summary"].get("traffic_level")


def get_history_score(device_id: str) -> float:
    """Skor riwayat device 0.0-1.0 dari tabel incidents.

    Ini BUKAN mock: datanya berasal dari database sendiri. Dihitung langsung
    oleh history_service tanpa memanggil API eksternal, sehingga fungsi ini
    tetap murah untuk dipanggil terpisah.
    """
    return _history_service.get_history(device_id).get("history_score", 0.5)
