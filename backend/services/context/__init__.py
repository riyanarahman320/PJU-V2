"""Context engine ASEP-JAGA.

Struktur:

    core/                 file asli milik pengguna (tidak diubah isinya)
        weather_service.py     Open-Meteo
        traffic_service.py     TomTom
        lighting_service.py    estimasi pencahayaan

    vocab.py              pemetaan kosakata sumber data <-> Random Forest
    weather_service.py    adapter cuaca
    traffic_service.py    adapter lalu lintas
    lighting_service.py   adapter pencahayaan
    history_service.py    riwayat device dari database sendiri
    hotspot_service.py    penyusun 18 fitur + pemanggil model
    builder.py            penggabung seluruh konteks (CONTEXT OBJECT)

Pemakaian dari luar cukup lewat builder:

    from backend.services.context import build_context
    context = build_context(device_id, latitude, longitude)
"""

from backend.services.context.builder import (  # noqa: F401
    build_context,
    device_config_dict,
    flatten_for_storage,
    local_now,
)
