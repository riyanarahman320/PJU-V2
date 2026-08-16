"""Logika pengelolaan incident: pembuatan, verifikasi tahap 2, aksi operator."""

import json
from datetime import timedelta

from backend.database import db
from backend.models import Incident, utcnow
from backend.services import emergency_adapter, verification
from backend.services.ai import audio_service
from backend.services.device_service import write_log

# Status incident yang masih dianggap berjalan (belum selesai).
OPEN_STATUS = ("ACTIVE", "CONFIRMED", "DISPATCHED")
CLOSED_STATUS = ("CLOSED", "FALSE_ALARM")


def generate_incident_id() -> str:
    """Buat ID incident yang mudah dibaca manusia, contoh:
    INC-20260813-0007 (urutan ke-7 pada tanggal tersebut).
    """
    now = utcnow()
    prefix = f"INC-{now.strftime('%Y%m%d')}"
    jumlah_hari_ini = Incident.query.filter(
        Incident.incident_id.like(f"{prefix}%")
    ).count()
    return f"{prefix}-{jumlah_hari_ini + 1:04d}"


def get_incident(incident_id: str) -> Incident | None:
    return Incident.query.filter_by(incident_id=incident_id).first()


def get_incident_by_event_id(device_id: str, event_id: str) -> Incident | None:
    """Cari incident berdasarkan idempotency key dari perangkat.

    Dipakai untuk mengenali retry: bila perangkat mengirim ulang kejadian yang
    sama karena responsnya hilang, incident yang sudah ada dikembalikan alih-
    alih membuat kejadian kedua.

    Pencocokan memakai pasangan (device_id, event_id), bukan event_id saja.
    event_id dibuat dari penghitung lokal perangkat, sehingga dua perangkat
    berbeda wajar menghasilkan nilai yang sama tanpa berarti kejadian yang
    sama.
    """
    if not event_id:
        return None
    return Incident.query.filter_by(device_id=device_id, event_id=event_id).first()


def get_active_incident_for_device(device_id: str) -> Incident | None:
    """Incident yang masih berjalan untuk satu device (bila ada)."""
    return (
        Incident.query.filter(
            Incident.device_id == device_id,
            Incident.status.in_(OPEN_STATUS),
        )
        .order_by(Incident.created_at.desc())
        .first()
    )


def list_incidents(status=None, limit: int = 100, only_open=False,
                   only_closed=False) -> list[Incident]:
    """Daftar incident dengan filter sederhana."""
    query = Incident.query
    if status:
        query = query.filter(Incident.status == status)
    if only_open:
        query = query.filter(Incident.status.in_(OPEN_STATUS))
    if only_closed:
        query = query.filter(Incident.status.in_(CLOSED_STATUS))
    return query.order_by(Incident.created_at.desc()).limit(limit).all()


def evaluate_emergency(data: dict, config) -> tuple[Incident, dict]:
    """Proses laporan emergency dari ESP32 dan jalankan verifikasi tahap 2.

    Langkah:
      1. Tentukan hasil verifikasi lokal (dari ESP32, atau dihitung server).
      2. Kumpulkan data konteks.
      3. Jalankan verifikasi tahap 2.
      4. Simpan incident.

    Parameter `config` adalah objek mirip dict (app.config dari Flask).

    Return: (incident, hasil_verifikasi)
    """
    device_id = data["device_id"]

    audio_threshold = config.get("AUDIO_CONFIDENCE_MIN", 0.60)
    confirm_threshold = config.get("SERVER_CONFIRM_THRESHOLD", 0.70)

    # 1. Bukti audio.
    # Bila perangkat mengirim `audio_features`, model audio dijalankan.
    # Bila hanya mengirim audio_class + audio_confidence (perilaku firmware
    # dan simulator saat ini), nilai itu dipakai tanpa memanggil model.
    audio = audio_service.distress_probability_from_payload(data)

    # Kelas dan keyakinan hasil model dipakai HANYA bila perangkat memang
    # mengirim fitur audio; jika tidak, nilai asli perangkat dipertahankan.
    if (
        audio.get("evidence_source") == "AI_AUDIO_MODEL"
        and audio.get("ai_status") == "OK"
    ):
        audio_class = audio.get("audio_class") or data["audio_class"]
        audio_confidence = float(audio.get("audio_confidence") or 0.0)
    else:
        audio_class = data["audio_class"]
        audio_confidence = data["audio_confidence"]

    distress = audio.get("audio_distress_probability")

    # 2. Verifikasi lokal (TAHAP 1).
    # ESP32 adalah pemegang keputusan tahap 1. Bila tidak dikirim,
    # server menghitung ulang memakai aturan yang sama.
    local_decision = data.get("local_decision") or verification.verify_local(
        sos=data["sos"],
        audio_confidence=audio_confidence,
        audio_class=audio_class,
        audio_threshold=audio_threshold,
    )

    # 3. CONTEXT OBJECT: cuaca, lalu lintas, pencahayaan, hotspot, riwayat.
    context = verification.collect_context(
        device_id, data.get("latitude"), data.get("longitude")
    )
    ringkas = context.get("summary", {})

    # 4. Evidence tambahan dari core_emergency_service (file pengguna).
    # Hasilnya HANYA evidence, bukan keputusan; lihat emergency_adapter.py.
    evidence = emergency_adapter.evaluate_as_evidence(
        sos=data["sos"],
        audio_confidence=audio_confidence,
        hotspot_level=ringkas.get("hotspot_level"),
    )

    # 5. Verifikasi tahap 2 (RULE-BASED SECOND-LEVEL VERIFICATION).
    hasil = verification.run_verification(
        {
            "device_id": device_id,
            "sos": data["sos"],
            "audio_confidence": audio_confidence,
            "audio_class": audio_class,
            "audio_distress_probability": distress,
            "local_decision": local_decision,
            "context": context,
            "emergency_state": evidence.get("emergency_state"),
            "emergency_state_support": evidence.get("state_support"),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "threshold": confirm_threshold,
        }
    )

    # 6. Simpan incident beserta snapshot konteks.
    now = utcnow()

    # Snapshot disimpan agar keputusan lama tetap dapat diaudit walaupun
    # data cuaca / lalu lintas / model sudah berubah kemudian.
    try:
        snapshot = json.dumps(
            {"context": context, "audio": audio, "evidence": evidence},
            default=str,
        )
    except (TypeError, ValueError):
        snapshot = None

    incident = Incident(
        incident_id=generate_incident_id(),
        device_id=device_id,
        # Idempotency key dari perangkat (opsional). Disimpan supaya retry
        # dengan nilai yang sama dapat dikenali pada request berikutnya.
        event_id=data.get("event_id"),
        sos=data["sos"],
        audio_confidence=audio_confidence,
        audio_class=audio_class,
        audio_distress_probability=distress,
        ai_status=audio.get("ai_status"),
        audio_model=audio.get("model"),
        audio_source=audio.get("source"),
        local_decision=local_decision,
        hotspot_risk=ringkas.get("hotspot_risk"),
        hotspot_level=ringkas.get("hotspot_level"),
        hotspot_confidence=ringkas.get("hotspot_confidence"),
        hotspot_status=ringkas.get("hotspot_status"),
        weather=ringkas.get("weather"),
        temperature=ringkas.get("temperature"),
        rainfall=ringkas.get("rainfall"),
        traffic=ringkas.get("traffic_level"),
        traffic_level=ringkas.get("traffic_level"),
        lighting_condition=ringkas.get("lighting_condition"),
        history_score=ringkas.get("history_score"),
        context_snapshot=snapshot,
        server_score=hasil["score"],
        server_decision=hasil["decision"],
        server_reason=hasil["reason"],
        verification_method=hasil.get("method"),
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        # timestamp dari perangkat dipakai bila dikirim (penting untuk
        # event yang tertunda karena perangkat sempat offline).
        created_at=data.get("timestamp") or now,
    )

    if hasil["decision"] == "CONFIRMED":
        incident.status = "CONFIRMED"
        incident.confirmed_at = now
    else:
        incident.status = "FALSE_ALARM"
        incident.closed_at = now

    db.session.add(incident)

    write_log(
        event_type=f"EMERGENCY_{hasil['decision']}",
        message=(
            f"Incident {incident.incident_id} dari {device_id}: "
            f"{local_decision} -> {hasil['decision']} "
            f"(skor {hasil['score']:.2f}, metode {hasil['method']})."
        ),
        device_id=device_id,
        incident_id=incident.incident_id,
        payload={
            "input": data,
            "audio": audio,
            "context": context,
            "evidence": evidence,
            "result": hasil,
        },
    )

    # Catat bila hotspot tidak dapat diprediksi, supaya penyebabnya terlihat
    # di halaman History tanpa perlu membuka log server.
    hotspot = context.get("hotspot") or {}
    if hotspot.get("status") != "OK":
        kurang = hotspot.get("missing") or []
        write_log(
            event_type="HOTSPOT_UNAVAILABLE",
            message=(
                f"Hotspot tidak diprediksi untuk {incident.incident_id}: "
                f"{hotspot.get('status')}. "
                + ("; ".join(kurang) if kurang else str(hotspot.get("message") or ""))
            ),
            device_id=device_id,
            incident_id=incident.incident_id,
            payload={"hotspot": hotspot},
        )

    db.session.commit()
    return incident, hasil


def confirm_incident(incident: Incident, note: str = "") -> Incident:
    """Operator mengonfirmasi incident secara manual dari dashboard.

    Berguna ketika verifikasi otomatis memutuskan FALSE_ALARM tetapi
    operator menilai kejadian ini nyata.
    """
    incident.status = "CONFIRMED"
    incident.server_decision = "CONFIRMED"
    if incident.confirmed_at is None:
        incident.confirmed_at = utcnow()
    # Incident yang sudah ditutup otomatis dibuka kembali.
    incident.closed_at = None

    catatan = f" Catatan: {note}" if note else ""
    incident.server_reason = (
        f"Dikonfirmasi manual oleh operator.{catatan} "
        f"(Hasil otomatis sebelumnya: {incident.server_reason or '-'})"
    )

    write_log(
        event_type="INCIDENT_CONFIRMED_BY_OPERATOR",
        message=f"Incident {incident.incident_id} dikonfirmasi operator.{catatan}",
        device_id=incident.device_id,
        incident_id=incident.incident_id,
    )

    db.session.commit()
    return incident


def mark_false_alarm(incident: Incident, note: str = "") -> Incident:
    """Operator menandai incident sebagai false alarm dan menutupnya."""
    now = utcnow()
    incident.status = "FALSE_ALARM"
    incident.server_decision = "FALSE_ALARM"
    incident.closed_at = now

    catatan = f" Catatan: {note}" if note else ""
    incident.server_reason = f"Ditandai false alarm oleh operator.{catatan}"

    write_log(
        event_type="INCIDENT_FALSE_ALARM_BY_OPERATOR",
        message=f"Incident {incident.incident_id} ditandai false alarm.{catatan}",
        device_id=incident.device_id,
        incident_id=incident.incident_id,
    )

    db.session.commit()
    return incident


def mark_dispatched(incident: Incident, note: str = "") -> Incident:
    """Operator menyatakan petugas sudah dikirim ke lokasi."""
    incident.status = "DISPATCHED"
    catatan = f" Catatan: {note}" if note else ""

    write_log(
        event_type="INCIDENT_DISPATCHED",
        message=f"Petugas dikirim untuk incident {incident.incident_id}.{catatan}",
        device_id=incident.device_id,
        incident_id=incident.incident_id,
    )

    db.session.commit()
    return incident


def close_incident(incident: Incident, note: str = "") -> Incident:
    """Tutup incident. Riwayat tetap tersimpan di tabel incidents."""
    incident.status = "CLOSED"
    incident.closed_at = utcnow()
    catatan = f" Catatan: {note}" if note else ""

    write_log(
        event_type="INCIDENT_CLOSED",
        message=f"Incident {incident.incident_id} ditutup.{catatan}",
        device_id=incident.device_id,
        incident_id=incident.incident_id,
    )

    db.session.commit()
    return incident


def build_statistics(timeout_seconds: int) -> dict:
    """Angka untuk kartu statistik dashboard."""
    from backend.services.device_service import count_devices

    now = utcnow()
    awal_hari = now - timedelta(hours=24)

    perangkat = count_devices(timeout_seconds)

    emergency_aktif = Incident.query.filter(
        Incident.status.in_(OPEN_STATUS)
    ).count()

    confirmed_hari_ini = Incident.query.filter(
        Incident.server_decision == "CONFIRMED",
        Incident.created_at >= awal_hari,
    ).count()

    false_alarm_hari_ini = Incident.query.filter(
        Incident.server_decision == "FALSE_ALARM",
        Incident.created_at >= awal_hari,
    ).count()

    return {
        "total_devices": perangkat["total"],
        "online_devices": perangkat["online"],
        "offline_devices": perangkat["offline"],
        "active_emergencies": emergency_aktif,
        "confirmed_today": confirmed_hari_ini,
        "false_alarms_today": false_alarm_hari_ini,
        "total_incidents": Incident.query.count(),
        "generated_at": now.isoformat(),
    }
