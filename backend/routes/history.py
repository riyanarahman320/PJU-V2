"""Endpoint riwayat: incident yang sudah selesai dan log sistem."""

from flask import Blueprint, request

from backend.models import Log
from backend.routes import fail, ok
from backend.services import incident_service

history_bp = Blueprint("history", __name__, url_prefix="/api")


@history_bp.get("/history")
def get_history():
    """GET /api/history

    Incident yang sudah selesai (CLOSED atau FALSE_ALARM).

    Query parameter opsional:
      limit=100       -> jumlah maksimum baris
      device_id=...   -> filter satu device
      decision=CONFIRMED|FALSE_ALARM
    """
    try:
        limit = min(int(request.args.get("limit", 100)), 500)
    except ValueError:
        return fail("Parameter 'limit' harus berupa angka.", 400)

    device_id = request.args.get("device_id")
    decision = request.args.get("decision")

    incidents = incident_service.list_incidents(limit=limit, only_closed=True)

    # Filter tambahan dilakukan di Python karena jumlah baris pada
    # prototype masih kecil dan ini menjaga query tetap sederhana.
    if device_id:
        incidents = [item for item in incidents if item.device_id == device_id]
    if decision:
        decision = decision.strip().upper()
        incidents = [item for item in incidents if item.server_decision == decision]

    return ok(
        {
            "history": [incident.to_dict() for incident in incidents],
            "count": len(incidents),
        }
    )


@history_bp.get("/logs")
def get_logs():
    """GET /api/logs

    Log sistem terbaru. Berguna untuk memeriksa alur saat pengembangan.

    Query parameter opsional:
      limit=100
      device_id=...
      event_type=...
    """
    try:
        limit = min(int(request.args.get("limit", 100)), 500)
    except ValueError:
        return fail("Parameter 'limit' harus berupa angka.", 400)

    query = Log.query
    device_id = request.args.get("device_id")
    event_type = request.args.get("event_type")

    if device_id:
        query = query.filter(Log.device_id == device_id)
    if event_type:
        query = query.filter(Log.event_type == event_type)

    logs = query.order_by(Log.created_at.desc()).limit(limit).all()
    return ok({"logs": [log.to_dict() for log in logs], "count": len(logs)})
