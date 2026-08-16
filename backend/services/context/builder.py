"""Context builder — menyusun CONTEXT OBJECT untuk verifikasi tahap 2.


Seluruh pengumpulan data konteks terpusat di sini, bukan di app.py atau routes.

Sumber yang digabungkan:

    weather   : Open-Meteo             -> REAL_API (kegagalan ditandai)
    traffic   : TomTom                 -> REAL_API bila ada key, else FALLBACK
    lighting  : estimasi jam + cuaca   -> ESTIMATED (bukan sensor)
    hotspot   : random_forest_pipeline -> OK bila 18 fitur sah
    history   : tabel incidents        -> REAL_OWN_DATABASE
    device    : konfigurasi per device -> USER_CONFIG / NOT_AVAILABLE
    time      : jam server (WIB)       -> REAL

STRUKTUR CONTEXT OBJECT
-----------------------
Detail  : context["weather"|"traffic"|"lighting"|"hotspot"|"history"|
                  "device_config"|"time"|"location"] -> dict ber-"status"
Ringkas : context["summary"] -> nilai tunggal siap pakai untuk skoring

KONTRAK: build_context() TIDAK PERNAH melempar exception. Kegagalan satu
sumber hanya menurunkan kelengkapan konteks, tidak menghentikan alur
emergency. Ini bagian dari prinsip fail-safe.
"""

from datetime import timedelta, timezone

from backend.models import utcnow
from backend.services.context import (
    history_service,
    hotspot_service,
    lighting_service,
    traffic_service,
    weather_service,
)

# WIB (UTC+7). Jam lokal dipakai untuk fitur Hour dan penentuan gelap/terang,
# karena model dilatih memakai waktu setempat, bukan UTC.
WIB = timezone(timedelta(hours=7))

# Status yang dianggap "data dapat dipakai" saat meringkas kualitas konteks.
STATUS_TERPAKAI = ("REAL_API", "OK", "REAL_OWN_DATABASE", "ESTIMATED", "REAL")


def local_now():
    """Waktu sekarang dalam zona WIB."""
    return utcnow().astimezone(WIB)


def device_config_dict(device) -> dict:
    """Konfigurasi konteks dari objek Device beserta status kelengkapannya."""
    if device is None:
        return {
            "village": None,
            "road_type": None,
            "area_type": None,
            "nearby_cctv": None,
            "nearby_police_post": None,
            "population_density": None,
            "population_density_status": "NOT_AVAILABLE",
            "public_event": "No",
            "holiday": "No",
            "status": "NOT_CONFIGURED",
            "source": "NOT_AVAILABLE",
        }

    return {
        "village": device.village,
        "road_type": device.road_type,
        "area_type": device.area_type,
        "nearby_cctv": device.nearby_cctv,
        "nearby_police_post": device.nearby_police_post,
        "population_density": device.population_density,
        # Penanda jujur: nilai ini belum tentu sudah diisi.
        "population_density_status": (
            "USER_CONFIG" if device.population_density is not None else "NOT_AVAILABLE"
        ),
        # STATIC CONFIG / MOCK: belum ada sumber kalender libur / jadwal acara.
        "public_event": device.public_event or "No",
        "holiday": device.holiday or "No",
        "status": "USER_CONFIG",
        "source": "DEVICE_CONFIG",
    }


def build_context(device_id: str, latitude=None, longitude=None, device=None) -> dict:
    """Kumpulkan seluruh konteks untuk satu kejadian.

    latitude/longitude None -> API cuaca & lalu lintas tidak dipanggil.
    device None -> dicari dari database berdasarkan device_id.
    """
    if device is None:
        try:
            from backend.services.device_service import get_device

            device = get_device(device_id)
        except Exception:  # noqa: BLE001
            device = None

    if latitude is None and device is not None:
        latitude = device.latitude
    if longitude is None and device is not None:
        longitude = device.longitude

    config = device_config_dict(device)
    moment = local_now()

    # 1. Cuaca (dipanggil lebih dulu karena dipakai oleh pencahayaan).
    weather = weather_service.get_weather(latitude, longitude)

    # 2. Lalu lintas.
    traffic = traffic_service.get_traffic(latitude, longitude)

    # 3. Pencahayaan (butuh jam lokal + cuaca + curah hujan).
    lighting = lighting_service.get_lighting_condition(
        moment.hour, weather.get("weather"), weather.get("rainfall")
    )

    # 4. Riwayat device dari database sendiri.
    history = history_service.get_history(device_id)

    # 5. Hotspot risk dari Random Forest.
    hotspot = hotspot_service.predict_hotspot(
        moment=moment,
        weather=weather,
        traffic=traffic,
        lighting=lighting,
        device_config=config,
        history=history,
    )

    waktu = {
        "iso": moment.isoformat(),
        "hour": moment.hour,
        "day_of_week": moment.strftime("%A"),
        "timezone": "Asia/Jakarta (UTC+7)",
        "is_night": moment.hour >= 19 or moment.hour <= 4,
        "status": "REAL",
        "source": "SERVER_CLOCK",
    }

    lokasi = {
        "latitude": latitude,
        "longitude": longitude,
        "available": latitude is not None and longitude is not None,
        "status": "REAL" if latitude is not None else "NOT_AVAILABLE",
        "source": "DEVICE_GPS_OR_CONFIG",
    }

    # Ringkasan datar: satu nilai per konsep, tanpa kunci ganda.
    summary = {
        "hotspot_risk": hotspot.get("risk_score"),
        "hotspot_level": hotspot.get("risk_level"),
        "hotspot_confidence": hotspot.get("confidence"),
        "hotspot_status": hotspot.get("status"),
        "weather": weather.get("weather"),
        "weather_model": weather.get("weather_model"),
        "temperature": weather.get("temperature"),
        "rainfall": weather.get("rainfall"),
        "weather_status": weather.get("status"),
        "traffic": traffic.get("traffic_level"),
        "traffic_level": traffic.get("traffic_level"),
        "traffic_status": traffic.get("status"),
        "lighting_condition": lighting.get("lighting_condition"),
        "is_dark": lighting.get("is_dark"),
        "lighting_status": lighting.get("status"),
        "history_score": history.get("history_score"),
        "history_status": history.get("status"),
        "hour": moment.hour,
        "is_night": waktu["is_night"],
    }

    context = {
        "weather": weather,
        "traffic": traffic,
        "lighting": lighting,
        "hotspot": hotspot,
        "history": history,
        "device_config": config,
        "time": waktu,
        "location": lokasi,
        "summary": summary,
        "source": "MIXED",
    }

    context["data_quality"] = summarize_quality(context)
    return context


def summarize_quality(context: dict) -> dict:
    """Ringkas kualitas data: bagian mana nyata, estimasi, atau tidak ada."""

    def status_dari(nama: str) -> str:
        bagian = context.get(nama)
        if isinstance(bagian, dict):
            return str(bagian.get("status") or "UNKNOWN")
        return "UNKNOWN"

    bagian = {
        "weather": status_dari("weather"),
        "traffic": status_dari("traffic"),
        "lighting": status_dari("lighting"),
        "hotspot": status_dari("hotspot"),
        "history": status_dari("history"),
    }

    tersedia = sum(1 for nilai in bagian.values() if nilai.upper() in STATUS_TERPAKAI)
    hotspot = context.get("hotspot") or {}

    return {
        "sections": bagian,
        "available_sections": tersedia,
        "total_sections": len(bagian),
        "hotspot_missing_features": hotspot.get("missing", []),
    }


def flatten_for_storage(context: dict) -> dict:
    """Nilai yang perlu disimpan ke tabel incidents (nama = nama kolom)."""
    summary = context.get("summary", {}) or {}
    return {
        "hotspot_risk": summary.get("hotspot_risk"),
        "hotspot_level": summary.get("hotspot_level"),
        "hotspot_confidence": summary.get("hotspot_confidence"),
        "hotspot_status": summary.get("hotspot_status"),
        "weather": summary.get("weather"),
        "temperature": summary.get("temperature"),
        "rainfall": summary.get("rainfall"),
        "traffic": summary.get("traffic_level"),
        "traffic_level": summary.get("traffic_level"),
        "lighting_condition": summary.get("lighting_condition"),
        "history_score": summary.get("history_score"),
    }
