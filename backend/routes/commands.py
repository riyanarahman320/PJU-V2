"""Endpoint command: polling oleh ESP32, acknowledge, dan clear.

Perangkat memanggil GET .../command secara berkala. Server hanya
mengembalikan command berstatus PENDING satu kali; setelahnya command
menjadi SENT sehingga sirene tidak dinyalakan berulang.
"""

from flask import Blueprint

from backend.routes import (
    fail,
    get_json_body,
    ok,
    require_device_api_key,
)
from backend.schemas import validate_command_ack
from backend.services import command_service, device_service

commands_bp = Blueprint("commands", __name__, url_prefix="/api")


@commands_bp.get("/device/<device_id>/command")
@require_device_api_key
def get_command(device_id: str):
    """GET /api/device/<device_id>/command

    Respons ketika ada perintah:
        {"command": "EMERGENCY_CONFIRMED", "strobe": true, "siren": true,
         "speaker": true, "voice_message": "...", "command_id": 1}

    Respons ketika tidak ada perintah:
        {"command": "NONE", "strobe": false, "siren": false,
         "speaker": false, "voice_message": ""}
    """
    device = device_service.get_device(device_id)
    if device is None:
        return fail(f"Device '{device_id}' tidak ditemukan.", 404)

    command = command_service.fetch_pending_command(device_id)
    return ok(command_service.command_payload(command))


@commands_bp.post("/device/<device_id>/command/ack")
@require_device_api_key
def acknowledge_command(device_id: str):
    """POST /api/device/<device_id>/command/ack

    Perangkat memberi tahu bahwa command sudah dijalankan (sirene dan
    speaker aktif). Body opsional: {"command_id": 1}
    """
    data, errors = validate_command_ack(get_json_body())
    if errors:
        return fail("Payload acknowledge tidak valid.", 400, errors)

    device = device_service.get_device(device_id)
    if device is None:
        return fail(f"Device '{device_id}' tidak ditemukan.", 404)

    command = command_service.acknowledge_command(device_id, data["command_id"])
    if command is None:
        return fail(
            "Tidak ada command yang dapat di-acknowledge untuk device ini.", 404
        )

    return ok({"command": command.to_dict()})


@commands_bp.post("/device/<device_id>/command/clear")
@require_device_api_key
def clear_command(device_id: str):
    """POST /api/device/<device_id>/command/clear

    Membatalkan semua command yang belum tuntas untuk device ini.
    Dipakai saat perangkat direset atau saat pengujian.
    """
    device = device_service.get_device(device_id)
    if device is None:
        return fail(f"Device '{device_id}' tidak ditemukan.", 404)

    jumlah = command_service.clear_pending_commands(device_id)
    return ok(
        {
            "cleared": jumlah,
            "message": f"{jumlah} command dibatalkan untuk {device_id}.",
        }
    )


@commands_bp.get("/device/<device_id>/commands")
def list_device_commands(device_id: str):
    """GET /api/device/<device_id>/commands

    Riwayat command untuk satu device. Dipakai dashboard, bukan perangkat,
    jadi tidak memerlukan API key.
    """
    device = device_service.get_device(device_id)
    if device is None:
        return fail(f"Device '{device_id}' tidak ditemukan.", 404)

    commands = command_service.list_commands(device_id=device_id)
    return ok(
        {
            "commands": [command.to_dict() for command in commands],
            "count": len(commands),
        }
    )
