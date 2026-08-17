"""Endpoint device: registrasi, heartbeat, dan daftar device."""

from flask import Blueprint

from backend.routes import (
    fail,
    get_json_body,
    offline_timeout,
    ok,
    require_device_api_key,
    require_operator_api_key,
)
from backend.schemas import (
    validate_device_context_config,
    validate_device_register,
    validate_heartbeat,
    validate_tamper,
)
from backend.services import device_service
from backend.services.incident_service import get_active_incident_for_device

devices_bp = Blueprint("devices", __name__, url_prefix="/api")


@devices_bp.post("/device/register")
@require_device_api_key
def register_device():
    """POST /api/device/register

    Dipanggil ESP32 setiap kali boot. Bersifat idempotent: bila device_id
    sudah ada, datanya diperbarui (HTTP 200) alih-alih menghasilkan error.
    """
    data, errors = validate_device_register(get_json_body())
    if errors:
        return fail("Payload registrasi tidak valid.", 400, errors)

    device, created = device_service.register_device(data)
    return ok(
        {
            "device": device.to_dict(offline_timeout()),
            "created": created,
            "message": (
                "Device baru terdaftar." if created else "Data device diperbarui."
            ),
        },
        201 if created else 200,
    )


@devices_bp.post("/device/heartbeat")
@require_device_api_key
def heartbeat():
    """POST /api/device/heartbeat

    Perangkat mengirim status berkala. Server memperbarui last_seen.
    Respons menyertakan `has_pending_command` sebagai petunjuk bagi
    perangkat bahwa ada perintah menunggu untuk diambil.
    """
    data, errors = validate_heartbeat(get_json_body())
    if errors:
        return fail("Payload heartbeat tidak valid.", 400, errors)

    device = device_service.record_heartbeat(data)
    if device is None:
        return fail(
            f"Device '{data['device_id']}' belum terdaftar. "
            "Panggil POST /api/device/register terlebih dahulu.",
            404,
        )

    from backend.models import Command

    pending = Command.query.filter(
        Command.device_id == device.device_id,
        Command.status == "PENDING",
    ).count()

    incident = get_active_incident_for_device(device.device_id)

    return ok(
        {
            "device": device.to_dict(offline_timeout()),
            "has_pending_command": pending > 0,
            "active_incident_id": incident.incident_id if incident else None,
        }
    )


@devices_bp.post("/device/tamper")
@require_device_api_key
def report_tamper():
    """POST /api/device/tamper

    Perangkat melaporkan sensor tamper: kotak dibuka paksa, atau kembali
    tertutup.

    ENDPOINT INI SENGAJA TERPISAH dari /api/emergency/evaluate.

    Tamper bukan keadaan darurat korban dan tidak memiliki bukti SOS maupun
    audio. Bila dimasukkan ke verifikasi tahap 2, skornya akan selalu di bawah
    ambang dan tercatat sebagai FALSE_ALARM - label yang keliru untuk
    pembongkaran yang benar-benar terjadi, dan mengotori statistik incident.

    Endpoint ini juga TIDAK membuat command apa pun. Sirene dan strobe hanya
    untuk kejadian darurat; menyalakannya karena tamper memberi tahu pelaku
    bahwa ia terdeteksi dan membuat warga menyangka ada korban.

    Perangkat mengirim ulang laporan yang gagal, jadi endpoint ini bersifat
    idempotent: laporan dengan keadaan yang sama tidak menambah log baru.
    """
    data, errors = validate_tamper(get_json_body())
    if errors:
        return fail("Payload tamper tidak valid.", 400, errors)

    device, berubah = device_service.record_tamper(data)
    if device is None:
        return fail(
            f"Device '{data['device_id']}' belum terdaftar. "
            "Panggil POST /api/device/register terlebih dahulu.",
            404,
        )

    return ok(
        {
            "device_id": device.device_id,
            "tamper_state": device.tamper_state(),
            "changed": berubah,
            "message": (
                "Tamper tercatat: kotak perangkat dibuka."
                if device.tamper
                else "Tamper pulih: kotak perangkat kembali tertutup."
            ),
        }
    )


@devices_bp.get("/devices")
def list_devices():
    """GET /api/devices — dipakai halaman Devices dan peta dashboard."""
    timeout = offline_timeout()
    device_service.refresh_offline_status(timeout)

    devices = device_service.list_devices()
    return ok(
        {
            "devices": [device.to_dict(timeout) for device in devices],
            "count": len(devices),
        }
    )


@devices_bp.get("/device/config/options")
def device_config_options():
    """GET /api/device/config/options

    Pilihan nilai yang sah untuk konfigurasi konteks device.

    Kosakata diambil LANGSUNG dari random_forest_pipeline.pkl bila model
    dapat dimuat, sehingga dashboard tidak pernah menampilkan pilihan yang
    ditolak model. Bila model belum tersedia, dipakai daftar acuan hasil
    inspeksi model yang sama (backend/models.py).
    """
    from backend.models import (
        RF_AREA_TYPES,
        RF_ROAD_TYPES,
        RF_VILLAGES,
        RF_YES_NO,
    )
    from backend.services.ai import model_loader

    vocab_model = model_loader.category_vocabulary()

    def pilihan(nama_fitur, acuan):
        nilai = vocab_model.get(nama_fitur)
        return list(nilai) if nilai else list(acuan)

    return ok(
        {
            "options": {
                "village": pilihan("Village", RF_VILLAGES),
                "road_type": pilihan("Road_Type", RF_ROAD_TYPES),
                "area_type": pilihan("Area_Type", RF_AREA_TYPES),
                "nearby_cctv": pilihan("Nearby_CCTV", RF_YES_NO),
                "nearby_police_post": pilihan("Nearby_Police_Post", RF_YES_NO),
                "public_event": pilihan("Public_Event", RF_YES_NO),
                "holiday": pilihan("Holiday", RF_YES_NO),
            },
            "source": "RANDOM_FOREST_MODEL" if vocab_model else "REFERENCE_LIST",
            "population_density": {
                "type": "number",
                "required_for_hotspot": True,
                "status": "NOT_AVAILABLE",
                "note": (
                    "Satuan harus sama dengan dataset training. Pipeline tidak "
                    "memakai scaler, sehingga nilai dengan satuan berbeda akan "
                    "menggeser hasil prediksi tanpa terdeteksi. Tidak ada nilai "
                    "default yang diisikan server."
                ),
            },
            "note": (
                "Village hanya mengenal 6 kelurahan di Kiaracondong, Bandung. "
                "Device di luar wilayah tersebut tidak dapat diprediksi "
                "hotspot-nya."
            ),
        }
    )


@devices_bp.get("/device/<device_id>/config")
def get_device_config(device_id: str):
    """GET /api/device/<device_id>/config — konfigurasi konteks satu device."""
    device = device_service.get_device(device_id)
    if device is None:
        return fail(f"Device '{device_id}' tidak ditemukan.", 404)

    return ok(
        {
            "device_id": device.device_id,
            "config": device.context_config(),
            "rf_config_complete": device.rf_config_complete(),
        }
    )


@devices_bp.put("/device/<device_id>/config")
@require_operator_api_key
def update_device_config(device_id: str):
    """PUT /api/device/<device_id>/config

    Operator mengisi konfigurasi konteks titik PJU dari dashboard.

    AUTENTIKASI: memerlukan header X-Operator-Key yang cocok dengan
    DEVICE_CONFIG_API_KEY di environment. Bukan device API key, karena
    endpoint ini dipakai operator, bukan perangkat.

    Endpoint ini dilindungi karena mengubah data yang memengaruhi prediksi
    hotspot: mengganti Village atau Population_Density akan mengubah hasil
    verifikasi kejadian berikutnya di titik tersebut.

    GET /config dan /config/options sengaja dibiarkan terbuka karena hanya
    membaca dan dipakai dashboard untuk menampilkan keadaan konfigurasi.
    """
    device = device_service.get_device(device_id)
    if device is None:
        return fail(f"Device '{device_id}' tidak ditemukan.", 404)

    data, errors = validate_device_context_config(get_json_body())
    if errors:
        return fail("Payload konfigurasi tidak valid.", 400, errors)

    device = device_service.update_context_config(device, data)

    return ok(
        {
            "device_id": device.device_id,
            "config": device.context_config(),
            "rf_config_complete": device.rf_config_complete(),
            "message": "Konfigurasi konteks diperbarui.",
        }
    )


@devices_bp.get("/devices/<device_id>")
def get_device(device_id: str):
    """GET /api/devices/<device_id> — detail satu device beserta
    incident aktifnya (bila ada)."""
    timeout = offline_timeout()
    device = device_service.get_device(device_id)
    if device is None:
        return fail(f"Device '{device_id}' tidak ditemukan.", 404)

    incident = get_active_incident_for_device(device_id)
    return ok(
        {
            "device": device.to_dict(timeout),
            "active_incident": incident.to_dict() if incident else None,
        }
    )
