"""Logika command untuk ESP32.

Aturan penting (bagian 13 spesifikasi): command tidak boleh dieksekusi
dua kali. Cara kerjanya:

  PENDING       -> baru dibuat server, belum diambil perangkat
  SENT          -> sudah diambil perangkat lewat GET .../command
  ACKNOWLEDGED  -> perangkat memastikan command sudah dijalankan
  CLEARED       -> command dibatalkan / emergency selesai

GET .../command hanya mengembalikan command berstatus PENDING. Setelah
diambil, statusnya langsung menjadi SENT sehingga polling berikutnya
mendapat "NONE" dan sirene tidak dinyalakan ulang.
"""

from backend.database import db
from backend.models import Command, utcnow
from backend.services.device_service import write_log

# Respons ketika tidak ada perintah apa pun untuk perangkat.
EMPTY_COMMAND = {
    "command": "NONE",
    "strobe": False,
    "siren": False,
    "speaker": False,
    "voice_message": "",
}

DEFAULT_VOICE_MESSAGE = "Petugas sedang menuju lokasi."


def create_emergency_command(device_id: str, incident_id: str,
                             voice_message: str = DEFAULT_VOICE_MESSAGE) -> Command:
    """Buat command EMERGENCY_CONFIRMED (strobe + siren + speaker).

    Bila sudah ada command PENDING untuk incident yang sama, command itu
    dipakai kembali agar tidak menumpuk perintah ganda.
    """
    existing = (
        Command.query.filter(
            Command.device_id == device_id,
            Command.incident_id == incident_id,
            Command.command == "EMERGENCY_CONFIRMED",
            Command.status.in_(("PENDING", "SENT", "ACKNOWLEDGED")),
        )
        .order_by(Command.created_at.desc())
        .first()
    )
    if existing is not None:
        return existing

    command = Command(
        device_id=device_id,
        incident_id=incident_id,
        command="EMERGENCY_CONFIRMED",
        strobe=True,
        siren=True,
        speaker=True,
        voice_message=voice_message,
        status="PENDING",
    )
    db.session.add(command)

    write_log(
        event_type="COMMAND_CREATED",
        message=f"Command EMERGENCY_CONFIRMED dibuat untuk {device_id}.",
        device_id=device_id,
        incident_id=incident_id,
        payload={"voice_message": voice_message},
    )

    db.session.commit()
    return command


def create_clear_command(device_id: str, incident_id=None) -> Command:
    """Buat command CLEAR_EMERGENCY: matikan sirene, strobe, dan speaker.

    Dipakai saat operator menutup incident atau menandainya false alarm.
    """
    # Command lama yang belum tuntas dibatalkan supaya perangkat tidak
    # menerima perintah yang saling bertentangan.
    clear_pending_commands(device_id, commit=False)

    command = Command(
        device_id=device_id,
        incident_id=incident_id,
        command="CLEAR_EMERGENCY",
        strobe=False,
        siren=False,
        speaker=False,
        voice_message="",
        status="PENDING",
    )
    db.session.add(command)

    write_log(
        event_type="COMMAND_CREATED",
        message=f"Command CLEAR_EMERGENCY dibuat untuk {device_id}.",
        device_id=device_id,
        incident_id=incident_id,
    )

    db.session.commit()
    return command


def fetch_pending_command(device_id: str) -> Command | None:
    """Ambil satu command PENDING lalu tandai SENT (sekali kirim saja).

    Return None bila tidak ada command menunggu.
    """
    command = (
        Command.query.filter(
            Command.device_id == device_id,
            Command.status == "PENDING",
        )
        .order_by(Command.created_at.asc())
        .first()
    )

    if command is None:
        return None

    command.status = "SENT"
    write_log(
        event_type="COMMAND_SENT",
        message=f"Command {command.command} dikirim ke {device_id}.",
        device_id=device_id,
        incident_id=command.incident_id,
    )
    db.session.commit()
    return command


def acknowledge_command(device_id: str, command_id=None) -> Command | None:
    """Tandai command sudah dijalankan perangkat.

    Bila command_id tidak diberikan, command SENT terakhir yang di-ack.
    Return None bila tidak ada command yang cocok.
    """
    query = Command.query.filter(Command.device_id == device_id)

    if command_id is not None:
        command = query.filter(Command.id == command_id).first()
    else:
        command = (
            query.filter(Command.status == "SENT")
            .order_by(Command.created_at.desc())
            .first()
        )

    if command is None:
        return None

    command.status = "ACKNOWLEDGED"
    command.executed_at = utcnow()

    write_log(
        event_type="COMMAND_ACKNOWLEDGED",
        message=f"Perangkat {device_id} menjalankan command {command.command}.",
        device_id=device_id,
        incident_id=command.incident_id,
    )

    db.session.commit()
    return command


def clear_pending_commands(device_id: str, commit: bool = True) -> int:
    """Batalkan semua command yang belum tuntas untuk satu device.

    Return: jumlah command yang dibatalkan.
    """
    commands = Command.query.filter(
        Command.device_id == device_id,
        Command.status.in_(("PENDING", "SENT")),
    ).all()

    for command in commands:
        command.status = "CLEARED"

    if commands:
        write_log(
            event_type="COMMAND_CLEARED",
            message=f"{len(commands)} command dibatalkan untuk {device_id}.",
            device_id=device_id,
        )

    if commit:
        db.session.commit()
    return len(commands)


def list_commands(device_id=None, incident_id=None, limit: int = 50) -> list[Command]:
    """Daftar command untuk keperluan dashboard / debugging."""
    query = Command.query
    if device_id:
        query = query.filter(Command.device_id == device_id)
    if incident_id:
        query = query.filter(Command.incident_id == incident_id)
    return query.order_by(Command.created_at.desc()).limit(limit).all()


def command_payload(command: Command | None) -> dict:
    """Bentuk respons untuk ESP32. Selalu memakai struktur yang sama
    supaya parsing JSON di firmware sederhana.
    """
    if command is None:
        return dict(EMPTY_COMMAND, command_id=None, incident_id=None)

    return {
        "command_id": command.id,
        "incident_id": command.incident_id,
        "command": command.command,
        "strobe": command.strobe,
        "siren": command.siren,
        "speaker": command.speaker,
        "voice_message": command.voice_message,
    }
