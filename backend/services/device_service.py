"""Logika pengelolaan device (registrasi, heartbeat, status online)."""

import json

from backend.database import db
from backend.models import Device, Log, utcnow


def write_log(event_type: str, message: str, device_id=None, incident_id=None,
              payload=None) -> Log:
    """Catat kejadian ke tabel logs. Dipakai semua service.

    Catatan: fungsi ini menambahkan objek ke session tetapi TIDAK commit,
    supaya pemanggil dapat menggabungkan beberapa perubahan dalam satu
    transaksi.
    """
    log = Log(
        device_id=device_id,
        incident_id=incident_id,
        event_type=event_type,
        message=message,
        payload=json.dumps(payload, default=str) if payload is not None else None,
    )
    db.session.add(log)
    return log


def get_device(device_id: str) -> Device | None:
    """Ambil satu device berdasarkan device_id. None bila tidak ada."""
    return Device.query.filter_by(device_id=device_id).first()


def list_devices() -> list[Device]:
    """Semua device, diurutkan berdasarkan device_id."""
    return Device.query.order_by(Device.device_id.asc()).all()


def register_device(data: dict) -> tuple[Device, bool]:
    """Daftarkan device baru atau perbarui yang sudah ada (idempotent).

    ESP32 memanggil endpoint ini setiap kali boot, jadi pemanggilan
    berulang tidak boleh menimbulkan error.

    Return: (device, created) — created=True bila device baru dibuat.
    """
    device = get_device(data["device_id"])
    created = device is None

    if created:
        device = Device(device_id=data["device_id"])
        db.session.add(device)

    # Field kosong tidak menimpa data yang sudah ada.
    if data.get("name"):
        device.name = data["name"]
    elif created:
        device.name = data["device_id"]

    if data.get("location"):
        device.location = data["location"]
    if data.get("latitude") is not None:
        device.latitude = data["latitude"]
    if data.get("longitude") is not None:
        device.longitude = data["longitude"]
    if data.get("firmware_version"):
        device.firmware_version = data["firmware_version"]

    device.status = "ONLINE"
    device.last_seen = utcnow()

    write_log(
        event_type="DEVICE_REGISTERED" if created else "DEVICE_UPDATED",
        message=(
            f"Device {device.device_id} terdaftar."
            if created
            else f"Data device {device.device_id} diperbarui."
        ),
        device_id=device.device_id,
        payload=data,
    )

    db.session.commit()
    return device, created


def update_context_config(device: Device, data: dict) -> Device:
    """Perbarui konfigurasi konteks device untuk Random Forest.

    Hanya field yang dikirim yang diubah (partial update). Nilai None
    berarti mengosongkan field tersebut.

    Nilai kategorikal SUDAH divalidasi terhadap kosakata model di
    schemas.validate_device_context_config(), jadi di sini tidak ada lagi
    penebakan nilai.

    Catatan Population_Density: nilainya disimpan apa adanya. Server tidak
    dapat memverifikasi satuannya karena dataset training tidak tersedia dan
    pipeline tidak memakai scaler. Selama field ini NULL, hotspot tidak
    diprediksi (lihat services/context/hotspot_service.py).
    """
    FIELDS = (
        "village",
        "road_type",
        "area_type",
        "nearby_cctv",
        "nearby_police_post",
        "population_density",
        "public_event",
        "holiday",
    )

    berubah = {}
    for field in FIELDS:
        if field not in data:
            continue
        lama = getattr(device, field)
        baru = data[field]

        # public_event dan holiday tidak boleh NULL (kolom NOT NULL).
        if baru is None and field in ("public_event", "holiday"):
            baru = "No"

        if lama != baru:
            setattr(device, field, baru)
            berubah[field] = {"dari": lama, "ke": baru}

    if berubah:
        write_log(
            event_type="DEVICE_CONFIG_UPDATED",
            message=(
                f"Konfigurasi konteks {device.device_id} diperbarui: "
                f"{', '.join(berubah.keys())}."
            ),
            device_id=device.device_id,
            payload={"changes": berubah},
        )
        db.session.commit()

    return device


def record_heartbeat(data: dict) -> Device | None:
    """Perbarui last_seen device. None bila device belum terdaftar."""
    device = get_device(data["device_id"])
    if device is None:
        return None

    device.last_seen = utcnow()
    device.status = data.get("status") or "ONLINE"
    if data.get("firmware_version"):
        device.firmware_version = data["firmware_version"]

    # Heartbeat terjadi terus-menerus, jadi tidak semuanya dicatat ke logs
    # agar tabel tidak membengkak. Hanya subsistem yang bermasalah dicatat.
    masalah = [
        nama
        for nama in ("network", "audio")
        if data.get(nama) is False
    ]
    if masalah:
        write_log(
            event_type="DEVICE_SUBSYSTEM_WARNING",
            message=f"Subsistem bermasalah pada {device.device_id}: {', '.join(masalah)}.",
            device_id=device.device_id,
            payload=data,
        )

    db.session.commit()
    return device


def refresh_offline_status(timeout_seconds: int) -> int:
    """Tandai device OFFLINE bila heartbeat terakhir melewati batas waktu.

    Dipanggil sebelum menampilkan daftar device / statistik supaya status
    di dashboard sesuai kenyataan tanpa perlu background scheduler.

    Return: jumlah device yang berubah status.
    """
    berubah = 0
    for device in Device.query.all():
        seharusnya = "ONLINE" if device.is_online(timeout_seconds) else "OFFLINE"
        if device.status != seharusnya:
            device.status = seharusnya
            berubah += 1
            if seharusnya == "OFFLINE":
                write_log(
                    event_type="DEVICE_OFFLINE",
                    message=(
                        f"Device {device.device_id} dianggap OFFLINE "
                        f"(tidak ada heartbeat > {timeout_seconds}s)."
                    ),
                    device_id=device.device_id,
                )

    if berubah:
        db.session.commit()
    return berubah


def count_devices(timeout_seconds: int) -> dict:
    """Hitung total/online/offline device untuk kartu statistik dashboard."""
    devices = Device.query.all()
    online = sum(1 for device in devices if device.is_online(timeout_seconds))
    return {
        "total": len(devices),
        "online": online,
        "offline": len(devices) - online,
    }
