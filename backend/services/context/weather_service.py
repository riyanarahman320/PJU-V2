"""Adapter cuaca.


Membungkus core/weather_service.py (milik pengguna, Open-Meteo) tanpa
mengubah isinya. Fungsi get_weather(latitude, longitude) tetap dipertahankan
sesuai permintaan.

Tambahan pada lapisan adapter ini:

1. Menerjemahkan nilai `weather` ke kosakata Random Forest lewat vocab.py.
   Tanpa ini, 'Clear'/'Storm'/'Unknown' menjadi vektor nol secara diam-diam
   di OneHotEncoder.
2. Menandai asal data dengan jelas: REAL_API, FALLBACK, atau ERROR.
   Nilai fallback TIDAK PERNAH disebut sebagai cuaca aktual.
3. Menangani koordinat yang tidak tersedia (device belum punya lat/lon)
   tanpa memanggil API sama sekali.
"""

from backend.services.context import vocab
from backend.services.context.core import weather_service as core_weather


def _hasil_tidak_tersedia(alasan: str) -> dict:
    """Bentuk hasil ketika cuaca benar-benar tidak dapat diambil."""
    return {
        "weather": None,
        "weather_model": None,
        "temperature": None,
        "rainfall": None,
        "rain": None,
        "weather_code": None,
        "status": "NOT_AVAILABLE",
        "source": "NOT_AVAILABLE",
        "message": alasan,
    }


def get_weather(latitude, longitude) -> dict:
    """Ambil cuaca terkini untuk satu titik koordinat.

    Return dict dengan kunci:
        weather        : nilai asli dari core (Clear/Cloudy/Rain/Storm/Unknown)
        weather_model  : nilai yang sudah dipetakan ke kosakata model,
                         atau None bila tidak dapat dipetakan
        temperature    : derajat Celsius, atau None
        rainfall       : mm, atau None
        rain           : mm, atau None
        status         : REAL_API | ERROR | NOT_AVAILABLE
        source         : penanda asal data untuk dashboard
    """
    if latitude is None or longitude is None:
        return _hasil_tidak_tersedia(
            "Koordinat device belum tersedia, API cuaca tidak dipanggil."
        )

    try:
        mentah = core_weather.get_weather(latitude, longitude)
    except Exception as error:  # noqa: BLE001 - jangan sampai crash server
        hasil = _hasil_tidak_tersedia(f"{type(error).__name__}: {error}")
        hasil["status"] = "ERROR"
        hasil["source"] = "ERROR"
        return hasil

    status_core = str(mentah.get("status", "")).lower()
    weather_asli = mentah.get("weather")
    rainfall = mentah.get("rainfall")

    if status_core != "success":
        # core sudah mengembalikan fallback (weather='Unknown'). Nilai ini
        # tidak boleh disebut sebagai cuaca sebenarnya.
        return {
            "weather": weather_asli,
            "weather_model": None,
            "temperature": mentah.get("temperature"),
            "rainfall": rainfall,
            "rain": mentah.get("rain"),
            "weather_code": mentah.get("weather_code"),
            "status": "ERROR",
            "source": "ERROR",
            "message": mentah.get("message", "API cuaca gagal."),
        }

    weather_model = vocab.map_weather(weather_asli, rainfall)

    hasil = {
        "weather": weather_asli,
        "weather_model": weather_model,
        "temperature": mentah.get("temperature"),
        "rainfall": rainfall,
        "rain": mentah.get("rain"),
        "weather_code": mentah.get("weather_code"),
        "status": "REAL_API",
        "source": "OPEN_METEO",
    }

    if weather_model is None:
        hasil["message"] = (
            f"Nilai cuaca '{weather_asli}' tidak dikenal model Random Forest; "
            "fitur Weather dikosongkan agar tidak menyesatkan."
        )

    return hasil
