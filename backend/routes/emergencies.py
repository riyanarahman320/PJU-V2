"""Endpoint emergency: evaluasi laporan dari perangkat dan aksi operator."""

from flask import Blueprint, current_app

from backend.routes import (
    fail,
    get_json_body,
    ok,
    require_device_api_key,
    require_operator_api_key,
)
from backend.schemas import validate_emergency_evaluate, validate_operator_action
from backend.services import command_service, device_service, incident_service

emergencies_bp = Blueprint("emergencies", __name__, url_prefix="/api")


def _evaluate_response(incident, command, *, duplicate: bool = False) -> dict:
    """Bentuk respons POST /api/emergency/evaluate.

    Dipakai oleh dua jalur: kejadian baru dan retry yang dikenali lewat
    event_id. Seluruh nilai dibaca dari incident yang tersimpan, sehingga
    perangkat menerima bentuk respons yang sama persis pada kedua jalur dan
    tidak perlu membedakan keduanya untuk dapat bekerja.
    """
    return {
        "incident_id": incident.incident_id,
        "event_id": incident.event_id,
        # True bila request ini adalah pengiriman ulang kejadian yang sudah
        # tercatat. Perangkat boleh mengabaikannya; disertakan supaya retry
        # terlihat jelas saat menelusuri masalah.
        "duplicate": duplicate,
        "local_decision": incident.local_decision,
        "server_decision": incident.server_decision,
        "server_score": incident.server_score,
        "reason": incident.server_reason,
        "verification_method": incident.verification_method,
        "status": incident.status,
        "context": {
                # hotspot_risk bernilai null bila model tidak dapat dipanggil,
                # misalnya karena Population_Density device belum diisi.
                # null berarti TIDAK DIKETAHUI, bukan nol.
                "hotspot_risk": incident.hotspot_risk,
                "hotspot_level": incident.hotspot_level,
                "hotspot_status": incident.hotspot_status,
                "weather": incident.weather,
                "temperature": incident.temperature,
                "rainfall": incident.rainfall,
                "traffic": incident.traffic_level or incident.traffic,
                "lighting_condition": incident.lighting_condition,
                "history_score": incident.history_score,
                # Sumber data dilaporkan per layanan, bukan satu label
                # menyeluruh, karena tingkat kenyataannya berbeda-beda.
                "sources": {
                    "weather": "OPEN_METEO",
                    "traffic": "TOMTOM",
                    "lighting": "ESTIMATED_FROM_TIME_AND_WEATHER",
                    "hotspot": "RANDOM_FOREST_MODEL",
                    "history": "OWN_DATABASE",
                },
            },
            "audio": {
                "audio_class": incident.audio_class,
                "audio_confidence": incident.audio_confidence,
                "audio_distress_probability": incident.audio_distress_probability,
                "ai_status": incident.ai_status,
            },
            "command": command_service.command_payload(command),
        }


@emergencies_bp.post("/emergency/evaluate")
@require_device_api_key
def evaluate_emergency():
    """POST /api/emergency/evaluate

    Alur:
      1. Validasi payload (400 bila tidak valid).
      2. Pastikan device terdaftar (404 bila tidak).
      3. Bila `event_id` sudah pernah diterima dari device ini, kembalikan
         incident yang ada tanpa memproses ulang (idempotency).
      4. Jalankan verifikasi tahap 2 lalu simpan incident.
      5. Bila CONFIRMED, langsung buat command EMERGENCY_CONFIRMED
         sehingga perangkat dapat mengambilnya pada polling berikutnya.

    Perlu diingat: strobe di perangkat sudah menyala sejak verifikasi
    lokal, tanpa menunggu respons endpoint ini.

    IDEMPOTENCY
    -----------
    Perangkat membuat satu `event_id` untuk satu kejadian SOS dan memakai
    nilai yang sama pada setiap percobaan pengiriman. Bila POST sampai ke
    server tetapi responsnya hilang karena timeout, retry akan mengembalikan
    incident yang sama: tidak ada incident kedua, tidak ada verifikasi yang
    dijalankan ulang, dan tidak ada command tambahan yang dibuat.

    `event_id` bersifat opsional. Bila tidak dikirim, perilaku lama
    dipertahankan: setiap request menghasilkan incident baru.
    """
    data, errors = validate_emergency_evaluate(get_json_body())
    if errors:
        return fail("Payload emergency tidak valid.", 400, errors)

    device = device_service.get_device(data["device_id"])
    if device is None:
        return fail(
            f"Device '{data['device_id']}' belum terdaftar. "
            "Panggil POST /api/device/register terlebih dahulu.",
            404,
        )

    # --- Pemeriksaan idempotency ---
    # Dilakukan SEBELUM verifikasi supaya retry tidak memanggil model,
    # tidak mengambil data cuaca/lalu lintas lagi, dan tidak menambah
    # riwayat kejadian device yang akan menggeser skor kejadian berikutnya.
    event_id = data.get("event_id")
    if event_id:
        existing = incident_service.get_incident_by_event_id(
            device.device_id, event_id
        )
        if existing is not None:
            # Command yang sudah ada dikembalikan apa adanya; tidak ada
            # command baru yang dibuat, sehingga sirene tidak dinyalakan ulang.
            commands = command_service.list_commands(
                incident_id=existing.incident_id
            )
            return ok(
                _evaluate_response(
                    existing,
                    commands[0] if commands else None,
                    duplicate=True,
                )
            )

    # Koordinat dari perangkat dipakai bila ada; bila tidak, memakai
    # koordinat yang tersimpan saat registrasi.
    if data.get("latitude") is None:
        data["latitude"] = device.latitude
    if data.get("longitude") is None:
        data["longitude"] = device.longitude

    incident, hasil = incident_service.evaluate_emergency(data, current_app.config)

    command = None
    if hasil["decision"] == "CONFIRMED":
        command = command_service.create_emergency_command(
            device_id=device.device_id,
            incident_id=incident.incident_id,
        )

    return ok(_evaluate_response(incident, command))


@emergencies_bp.get("/incidents")
def list_incidents():
    """GET /api/incidents

    Query parameter opsional:
      status=ACTIVE|CONFIRMED|FALSE_ALARM|DISPATCHED|CLOSED
      open=true    -> hanya incident yang masih berjalan
      limit=100
    """
    from flask import request

    status = request.args.get("status")
    only_open = request.args.get("open", "").lower() in ("1", "true", "yes")

    try:
        limit = min(int(request.args.get("limit", 100)), 500)
    except ValueError:
        return fail("Parameter 'limit' harus berupa angka.", 400)

    incidents = incident_service.list_incidents(
        status=status, limit=limit, only_open=only_open
    )
    return ok(
        {
            "incidents": [incident.to_dict() for incident in incidents],
            "count": len(incidents),
        }
    )


@emergencies_bp.get("/incidents/<incident_id>")
def get_incident(incident_id: str):
    """GET /api/incidents/<incident_id>

    Menyertakan daftar command dan log terkait supaya halaman detail
    dapat menampilkan seluruh alur dari SOS sampai command.
    """
    from backend.models import Log

    incident = incident_service.get_incident(incident_id)
    if incident is None:
        return fail(f"Incident '{incident_id}' tidak ditemukan.", 404)

    commands = command_service.list_commands(incident_id=incident_id)
    logs = (
        Log.query.filter_by(incident_id=incident_id)
        .order_by(Log.created_at.asc())
        .all()
    )

    return ok(
        {
            "incident": incident.to_dict(),
            "commands": [command.to_dict() for command in commands],
            "logs": [log.to_dict() for log in logs],
        }
    )


@emergencies_bp.post("/incidents/<incident_id>/confirm")
@require_operator_api_key
def confirm_incident(incident_id: str):
    """POST /api/incidents/<incident_id>/confirm

    Operator mengonfirmasi incident dari dashboard. Command
    EMERGENCY_CONFIRMED dibuat bila belum ada.

    AUTENTIKASI: memerlukan header X-Operator-Key (DEVICE_CONFIG_API_KEY).
    Aksi ini menyalakan sirene di lokasi, jadi wewenangnya tidak boleh
    terbuka bagi siapa pun yang dapat menjangkau server.
    """
    data, errors = validate_operator_action(get_json_body())
    if errors:
        return fail("Payload tidak valid.", 400, errors)

    incident = incident_service.get_incident(incident_id)
    if incident is None:
        return fail(f"Incident '{incident_id}' tidak ditemukan.", 404)

    incident_service.confirm_incident(incident, data["note"])
    command = command_service.create_emergency_command(
        device_id=incident.device_id,
        incident_id=incident.incident_id,
    )

    return ok(
        {
            "incident": incident.to_dict(),
            "command": command_service.command_payload(command),
        }
    )


@emergencies_bp.post("/incidents/<incident_id>/false-alarm")
@require_operator_api_key
def false_alarm_incident(incident_id: str):
    """POST /api/incidents/<incident_id>/false-alarm

    Menandai incident sebagai false alarm dan mengirim CLEAR_EMERGENCY
    supaya sirene dan strobe dimatikan.

    AUTENTIKASI: memerlukan header X-Operator-Key (DEVICE_CONFIG_API_KEY).
    Aksi ini MEMATIKAN respons darurat yang sedang berjalan; bila dipanggil
    pihak yang tidak berwenang, kejadian nyata dapat dibungkam.
    """
    data, errors = validate_operator_action(get_json_body())
    if errors:
        return fail("Payload tidak valid.", 400, errors)

    incident = incident_service.get_incident(incident_id)
    if incident is None:
        return fail(f"Incident '{incident_id}' tidak ditemukan.", 404)

    incident_service.mark_false_alarm(incident, data["note"])
    command = command_service.create_clear_command(
        device_id=incident.device_id,
        incident_id=incident.incident_id,
    )

    return ok(
        {
            "incident": incident.to_dict(),
            "command": command_service.command_payload(command),
        }
    )


@emergencies_bp.post("/incidents/<incident_id>/dispatch")
@require_operator_api_key
def dispatch_incident(incident_id: str):
    """POST /api/incidents/<incident_id>/dispatch

    Menandai bahwa petugas sudah dikirim. Command tidak diubah: sirene
    tetap aktif sampai incident ditutup.

    AUTENTIKASI: memerlukan header X-Operator-Key (DEVICE_CONFIG_API_KEY).
    Dekorator berjalan SEBELUM fungsi ini, sehingga request tanpa kunci yang
    sah tidak pernah mencapai logika dispatch: status incident tidak berubah
    dan tidak ada command yang dibuat.
    """
    data, errors = validate_operator_action(get_json_body())
    if errors:
        return fail("Payload tidak valid.", 400, errors)

    incident = incident_service.get_incident(incident_id)
    if incident is None:
        return fail(f"Incident '{incident_id}' tidak ditemukan.", 404)

    incident_service.mark_dispatched(incident, data["note"])
    return ok({"incident": incident.to_dict()})


@emergencies_bp.post("/incidents/<incident_id>/close")
@require_operator_api_key
def close_incident(incident_id: str):
    """POST /api/incidents/<incident_id>/close

    Menutup incident dan mengirim CLEAR_EMERGENCY ke perangkat.
    Setelah ditutup, incident muncul di halaman History.

    AUTENTIKASI: memerlukan header X-Operator-Key (DEVICE_CONFIG_API_KEY).
    Aksi ini mengirim CLEAR_EMERGENCY yang mematikan sirene dan strobe.
    """
    data, errors = validate_operator_action(get_json_body())
    if errors:
        return fail("Payload tidak valid.", 400, errors)

    incident = incident_service.get_incident(incident_id)
    if incident is None:
        return fail(f"Incident '{incident_id}' tidak ditemukan.", 404)

    incident_service.close_incident(incident, data["note"])
    command = command_service.create_clear_command(
        device_id=incident.device_id,
        incident_id=incident.incident_id,
    )

    return ok(
        {
            "incident": incident.to_dict(),
            "command": command_service.command_payload(command),
        }
    )
