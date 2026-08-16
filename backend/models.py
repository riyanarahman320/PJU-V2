"""Model database ASEP-JAGA.

Empat tabel: devices, incidents, commands, logs.
Semua timestamp disimpan dalam UTC (timezone-aware).
"""

from datetime import datetime, timedelta, timezone

from backend.database import db


def utcnow() -> datetime:
    """Waktu sekarang dalam UTC (timezone-aware)."""
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    """Ubah datetime menjadi string ISO-8601. SQLite kadang mengembalikan
    datetime tanpa tzinfo, jadi UTC ditambahkan kembali di sini."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


# --- Nilai status yang diperbolehkan -------------------------------------

DEVICE_STATUS = ("ONLINE", "OFFLINE")
LOCAL_DECISIONS = ("LOCAL_VERIFIED", "LOCAL_REJECTED")
SERVER_DECISIONS = ("CONFIRMED", "FALSE_ALARM", "PENDING")
INCIDENT_STATUS = ("ACTIVE", "CONFIRMED", "FALSE_ALARM", "DISPATCHED", "CLOSED")
COMMAND_STATUS = ("PENDING", "SENT", "ACKNOWLEDGED", "CLEARED")

# --- Kosakata konfigurasi device untuk Random Forest ---------------------
# Nilai di bawah HARUS sama dengan categories_ pada OneHotEncoder di dalam
# random_forest_pipeline.pkl. Diperoleh dari inspeksi model, bukan dugaan.
# Nilai di luar daftar ini akan diubah menjadi vektor nol secara diam-diam
# oleh handle_unknown='ignore', karena itu divalidasi lebih awal di sini.

RF_VILLAGES = (
    "Babakan Sari",
    "Babakan Surabaya",
    "Cicaheum",
    "Kebon Jayanti",
    "Kebon Kangkung",
    "Sukapura",
)
RF_ROAD_TYPES = ("Alley", "Main Road", "Market Area", "Residential")
RF_AREA_TYPES = (
    "Commercial",
    "Public Facility",
    "Residential",
    "School",
    "Terminal",
    "Traditional Market",
)
RF_YES_NO = ("Yes", "No")


class Device(db.Model):
    """Satu unit PJU ASEP-JAGA (ESP32-S3)."""

    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False, default="")
    location = db.Column(db.String(200), nullable=False, default="")
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(16), nullable=False, default="OFFLINE")
    last_seen = db.Column(db.DateTime(timezone=True), nullable=True)
    firmware_version = db.Column(db.String(32), nullable=False, default="unknown")

    # --- Konfigurasi konteks untuk Random Forest (USER CONFIG) ----------
    # Nilai-nilai ini TIDAK dapat diukur sensor maupun diambil dari API.
    # Operator mengisinya sesuai kondisi nyata titik PJU.
    # Selama masih NULL, hotspot_service melaporkan fitur tidak tersedia
    # dan model TIDAK dipanggil (lihat services/context/hotspot_service.py).
    village = db.Column(db.String(64), nullable=True)
    road_type = db.Column(db.String(32), nullable=True)
    area_type = db.Column(db.String(32), nullable=True)
    nearby_cctv = db.Column(db.String(8), nullable=True)
    nearby_police_post = db.Column(db.String(8), nullable=True)

    # Population_Density sengaja TIDAK diberi nilai default.
    # Pipeline memakai 'passthrough' (tanpa scaler) untuk fitur numerik,
    # sehingga angka dengan satuan yang salah akan menggeser hasil prediksi
    # tanpa terdeteksi. NULL berarti NOT_AVAILABLE.
    population_density = db.Column(db.Float, nullable=True)

    # STATIC CONFIG / MOCK: belum ada sumber kalender hari libur maupun
    # jadwal acara. Default "No", dapat diubah manual dari dashboard.
    public_event = db.Column(db.String(8), nullable=False, default="No")
    holiday = db.Column(db.String(8), nullable=False, default="No")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    incidents = db.relationship("Incident", back_populates="device", lazy="select")

    def is_online(self, timeout_seconds: int) -> bool:
        """Device online bila heartbeat terakhir masih dalam batas timeout."""
        if self.last_seen is None:
            return False
        last = self.last_seen
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (utcnow() - last) <= timedelta(seconds=timeout_seconds)

    def context_config(self) -> dict:
        """Konfigurasi konteks device beserta status kelengkapannya.

        `population_density_status` dibuat eksplisit supaya dashboard dan
        API tidak pernah menampilkan nilai kosong sebagai angka nyata.
        """
        return {
            "village": self.village,
            "road_type": self.road_type,
            "area_type": self.area_type,
            "nearby_cctv": self.nearby_cctv,
            "nearby_police_post": self.nearby_police_post,
            "population_density": self.population_density,
            "population_density_status": (
                "USER_CONFIG"
                if self.population_density is not None
                else "NOT_AVAILABLE"
            ),
            "public_event": self.public_event,
            "holiday": self.holiday,
            "public_event_source": "STATIC_CONFIG",
            "holiday_source": "STATIC_CONFIG",
        }

    def rf_config_complete(self) -> bool:
        """True bila seluruh konfigurasi yang dibutuhkan model sudah diisi.

        Dipakai dashboard untuk menandai device yang hotspot-nya belum bisa
        diprediksi.
        """
        return all(
            (
                self.village,
                self.road_type,
                self.area_type,
                self.nearby_cctv,
                self.nearby_police_post,
                self.population_density is not None,
            )
        )

    def to_dict(self, timeout_seconds: int = 60) -> dict:
        online = self.is_online(timeout_seconds)
        return {
            "device_id": self.device_id,
            "name": self.name,
            "location": self.location,
            "latitude": self.latitude,
            "longitude": self.longitude,
            # status dihitung ulang dari last_seen agar selalu akurat
            "status": "ONLINE" if online else "OFFLINE",
            "online": online,
            "last_seen": iso(self.last_seen),
            "firmware_version": self.firmware_version,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            # Konfigurasi konteks untuk Random Forest.
            "context_config": self.context_config(),
            "rf_config_complete": self.rf_config_complete(),
        }


class Incident(db.Model):
    """Satu kejadian emergency, dari SOS sampai ditutup."""

    __tablename__ = "incidents"

    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    device_id = db.Column(
        db.String(64), db.ForeignKey("devices.device_id"), nullable=False, index=True
    )

    # IDEMPOTENCY KEY dari perangkat.
    #
    # ESP32 membuat satu event_id untuk satu kejadian SOS, lalu memakai nilai
    # yang sama pada setiap percobaan pengiriman. Bila POST sampai ke server
    # tetapi responsnya hilang karena timeout, perangkat mengirim ulang dengan
    # event_id yang sama dan server mengembalikan incident yang sudah ada
    # alih-alih membuat kejadian kedua.
    #
    # Nullable karena: (a) field ini opsional di API supaya firmware lama dan
    # dashboard tetap berfungsi, dan (b) incident yang sudah tersimpan sebelum
    # kolom ini ada tidak memilikinya.
    #
    # Keunikan dijaga per device, bukan global: event_id dibuat perangkat dari
    # penghitung lokalnya (mis. millis()), sehingga dua perangkat berbeda
    # wajar menghasilkan nilai yang sama tanpa berarti kejadian yang sama.
    event_id = db.Column(db.String(64), nullable=True)

    # Dipakai UNIQUE INDEX, bukan UniqueConstraint, dengan alasan praktis:
    # SQLite tidak mendukung ALTER TABLE ... ADD CONSTRAINT, sehingga
    # constraint tidak dapat ditambahkan ke database yang sudah berisi data
    # tanpa membangun ulang tabel. Unique index dapat dibuat belakangan lewat
    # CREATE UNIQUE INDEX, sehingga database baru (create_all) dan database
    # lama (scripts/migrate_add_event_id.py) berakhir dengan objek yang sama.
    #
    # Baris dengan event_id NULL tidak saling bertabrakan: SQLite tidak
    # menganggap dua NULL sebagai nilai yang sama. Ini yang membuat incident
    # tanpa event_id (dibuat dashboard atau firmware lama) tetap boleh banyak.
    __table_args__ = (
        db.Index(
            "uq_incident_device_event", "device_id", "event_id", unique=True
        ),
    )

    # Data dari ESP32 (tahap 1 - local verification)
    sos = db.Column(db.Boolean, nullable=False, default=False)
    audio_confidence = db.Column(db.Float, nullable=False, default=0.0)
    audio_class = db.Column(db.String(64), nullable=False, default="Unknown")
    local_decision = db.Column(db.String(32), nullable=False, default="LOCAL_REJECTED")

    # Bukti audio tambahan.
    # audio_distress_probability = 1 - P(Normal) dari model audio.
    # Berbeda maknanya dengan audio_confidence (keyakinan pada kelas
    # terpilih), jadi disimpan terpisah agar tidak tertukar.
    audio_distress_probability = db.Column(db.Float, nullable=True)
    ai_status = db.Column(db.String(16), nullable=True)
    audio_model = db.Column(db.String(64), nullable=True)
    audio_source = db.Column(db.String(48), nullable=True)

    # Data konteks (tahap 2 - server verification).
    # hotspot_* berasal dari random_forest_pipeline.pkl (model nyata).
    # weather/temperature/rainfall dari Open-Meteo (API nyata).
    # traffic dari TomTom (API nyata bila TOMTOM_API_KEY tersedia).
    # lighting_condition adalah ESTIMASI, bukan sensor.
    hotspot_risk = db.Column(db.Float, nullable=True)
    hotspot_level = db.Column(db.String(16), nullable=True)
    hotspot_confidence = db.Column(db.Float, nullable=True)
    hotspot_status = db.Column(db.String(32), nullable=True)
    weather = db.Column(db.String(64), nullable=True)
    temperature = db.Column(db.Float, nullable=True)
    rainfall = db.Column(db.Float, nullable=True)
    traffic = db.Column(db.String(64), nullable=True)
    traffic_level = db.Column(db.String(32), nullable=True)
    lighting_condition = db.Column(db.String(32), nullable=True)
    history_score = db.Column(db.Float, nullable=True)

    # Snapshot konteks lengkap (JSON string). Disimpan agar keputusan lama
    # tetap dapat diaudit walau data cuaca/lalu lintas sudah berubah.
    context_snapshot = db.Column(db.Text, nullable=True)

    # Hasil verifikasi server
    server_score = db.Column(db.Float, nullable=True)
    server_decision = db.Column(db.String(32), nullable=False, default="PENDING")
    server_reason = db.Column(db.Text, nullable=True)
    verification_method = db.Column(db.String(48), nullable=True)

    status = db.Column(db.String(32), nullable=False, default="ACTIVE", index=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    closed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    device = db.relationship("Device", back_populates="incidents")
    commands = db.relationship("Command", back_populates="incident", lazy="select")

    def to_dict(self, include_device: bool = True) -> dict:
        data = {
            "incident_id": self.incident_id,
            "device_id": self.device_id,
            # Idempotency key dari perangkat; null untuk incident yang dibuat
            # tanpa event_id (dashboard, firmware lama, atau data lama).
            "event_id": self.event_id,
            "sos": self.sos,
            "audio_confidence": self.audio_confidence,
            "audio_class": self.audio_class,
            "audio_distress_probability": self.audio_distress_probability,
            "ai_status": self.ai_status,
            "audio_model": self.audio_model,
            "audio_source": self.audio_source,
            "local_decision": self.local_decision,
            # Kunci lama dipertahankan apa adanya supaya dashboard dan data
            # incident lama tidak rusak; field baru ditambahkan di sampingnya.
            "context": {
                "hotspot_risk": self.hotspot_risk,
                "hotspot_level": self.hotspot_level,
                "hotspot_confidence": self.hotspot_confidence,
                "hotspot_status": self.hotspot_status,
                "weather": self.weather,
                "temperature": self.temperature,
                "rainfall": self.rainfall,
                "traffic": self.traffic,
                "traffic_level": self.traffic_level,
                "lighting_condition": self.lighting_condition,
                "history_score": self.history_score,
            },
            "server_score": self.server_score,
            "server_decision": self.server_decision,
            "server_reason": self.server_reason,
            "verification_method": self.verification_method,
            "status": self.status,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "confirmed_at": iso(self.confirmed_at),
            "closed_at": iso(self.closed_at),
        }
        if include_device and self.device is not None:
            data["device_name"] = self.device.name
            data["device_location"] = self.device.location
        return data


class Command(db.Model):
    """Perintah dari server untuk ESP32 (strobe / siren / speaker)."""

    __tablename__ = "commands"

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(
        db.String(64), db.ForeignKey("devices.device_id"), nullable=False, index=True
    )
    incident_id = db.Column(
        db.String(64), db.ForeignKey("incidents.incident_id"), nullable=True, index=True
    )

    command = db.Column(db.String(64), nullable=False, default="NONE")
    strobe = db.Column(db.Boolean, nullable=False, default=False)
    siren = db.Column(db.Boolean, nullable=False, default=False)
    speaker = db.Column(db.Boolean, nullable=False, default=False)
    voice_message = db.Column(db.String(255), nullable=False, default="")

    status = db.Column(db.String(32), nullable=False, default="PENDING", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    executed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    incident = db.relationship("Incident", back_populates="commands")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "device_id": self.device_id,
            "incident_id": self.incident_id,
            "command": self.command,
            "strobe": self.strobe,
            "siren": self.siren,
            "speaker": self.speaker,
            "voice_message": self.voice_message,
            "status": self.status,
            "created_at": iso(self.created_at),
            "executed_at": iso(self.executed_at),
        }


class Log(db.Model):
    """Jejak kejadian sistem untuk audit dan debugging."""

    __tablename__ = "logs"

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(64), nullable=True, index=True)
    incident_id = db.Column(db.String(64), nullable=True, index=True)
    event_type = db.Column(db.String(64), nullable=False)
    message = db.Column(db.Text, nullable=False, default="")
    payload = db.Column(db.Text, nullable=True)  # JSON disimpan sebagai string
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "device_id": self.device_id,
            "incident_id": self.incident_id,
            "event_type": self.event_type,
            "message": self.message,
            "payload": self.payload,
            "created_at": iso(self.created_at),
        }
