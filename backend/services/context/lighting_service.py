"""Adapter kondisi pencahayaan.


Membungkus core/lighting_service.py (milik pengguna) tanpa mengubah isinya.
Fungsi get_lighting_condition(hour, weather, rainfall) dipertahankan.

CATATAN KEJUJURAN DATA
----------------------
Nilai ini ESTIMASI dari jam, cuaca, dan curah hujan. BUKAN hasil pembacaan
sensor LDR/lux di perangkat. core sendiri menandainya dengan
source='estimated', dan penanda itu diteruskan ke dashboard.

Pencahayaan dipakai sebagai konteks lingkungan (PJU) dan sebagai fitur
Lighting_Condition pada Random Forest. Kosakata core (Good/Moderate/Poor)
sudah sama persis dengan kosakata model, sehingga tidak ada kehilangan
informasi pada pemetaan.

Pencahayaan BUKAN pemicu emergency. Ia hanya salah satu bahan pertimbangan
pada verifikasi tahap 2.
"""

from backend.services.context import vocab
from backend.services.context.core import lighting_service as core_lighting


def get_lighting_condition(hour, weather, rainfall) -> dict:
    """Perkirakan kondisi pencahayaan.

    Parameter
    ---------
    hour : int
        Jam lokal 0-23.
    weather : str | None
        Kondisi cuaca (boleh None bila API cuaca gagal).
    rainfall : float | None
        Curah hujan mm (boleh None).

    Return dict dengan kunci:
        lighting_condition       : Good | Moderate | Poor
        lighting_condition_model : nilai untuk fitur Lighting_Condition
        is_dark                  : bool
        period                   : day | transition | night
        status                   : ESTIMATED | ERROR
        source                   : ESTIMATED_FROM_TIME_WEATHER | ERROR
    """
    try:
        jam = int(hour)
    except (TypeError, ValueError):
        jam = 0

    # Jam di luar 0-23 dinormalisasi supaya core tidak salah menentukan periode.
    jam = jam % 24

    try:
        mentah = core_lighting.get_lighting_condition(jam, weather, rainfall)
    except Exception as error:  # noqa: BLE001 - jangan sampai crash server
        return {
            "lighting_condition": None,
            "lighting_condition_model": None,
            "is_dark": None,
            "period": None,
            "status": "ERROR",
            "source": "ERROR",
            "message": f"{type(error).__name__}: {error}",
        }

    kondisi = mentah.get("lighting_condition")

    return {
        "lighting_condition": kondisi,
        "lighting_condition_model": vocab.map_lighting(kondisi),
        "is_dark": mentah.get("is_dark"),
        "period": mentah.get("period"),
        # core menandai 'estimated'; diteruskan dalam bentuk yang lebih tegas.
        "status": "ESTIMATED",
        "source": "ESTIMATED_FROM_TIME_WEATHER",
    }
