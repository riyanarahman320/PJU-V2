"""Validasi payload request.

Ditulis manual tanpa library eksternal supaya mudah dibaca dan
tidak menambah dependency. Setiap fungsi validate_* mengembalikan:

    (data, errors)

- data   : dict berisi nilai yang sudah dibersihkan (None jika ada error)
- errors : list berisi pesan error (list kosong jika valid)

Endpoint memakai hasil ini untuk menentukan HTTP 400 atau lanjut proses.
"""

from datetime import datetime, timezone

from backend.models import (
    DEVICE_STATUS,
    LOCAL_DECISIONS,
    RF_AREA_TYPES,
    RF_ROAD_TYPES,
    RF_VILLAGES,
    RF_YES_NO,
)

# Panjang maksimum agar tidak ada string liar masuk ke database
MAX_DEVICE_ID = 64
MAX_NAME = 120
MAX_LOCATION = 200
MAX_AUDIO_CLASS = 64


# --- Helper dasar ---------------------------------------------------------


def _require_dict(payload):
    """Pastikan body request berupa objek JSON."""
    if payload is None:
        return None, ["Body request harus berupa JSON (Content-Type: application/json)."]
    if not isinstance(payload, dict):
        return None, ["Body request harus berupa objek JSON."]
    return payload, []


def _clean_string(payload, key, errors, *, required=False, max_length=255, default=""):
    value = payload.get(key, None)
    if value is None:
        if required:
            errors.append(f"Field '{key}' wajib diisi.")
            return default
        return default
    if not isinstance(value, str):
        errors.append(f"Field '{key}' harus berupa string.")
        return default
    value = value.strip()
    if required and not value:
        errors.append(f"Field '{key}' tidak boleh kosong.")
        return default
    if len(value) > max_length:
        errors.append(f"Field '{key}' maksimal {max_length} karakter.")
        return value[:max_length]
    return value


def _clean_bool(payload, key, errors, *, required=False, default=False):
    value = payload.get(key, None)
    if value is None:
        if required:
            errors.append(f"Field '{key}' wajib diisi.")
        return default
    if isinstance(value, bool):
        return value
    errors.append(f"Field '{key}' harus berupa boolean (true/false).")
    return default


def _clean_float(
    payload, key, errors, *, required=False, default=None, minimum=None, maximum=None
):
    value = payload.get(key, None)
    if value is None:
        if required:
            errors.append(f"Field '{key}' wajib diisi.")
        return default
    # bool adalah subclass int di Python, tolak secara eksplisit
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"Field '{key}' harus berupa angka.")
        return default
    value = float(value)
    if minimum is not None and value < minimum:
        errors.append(f"Field '{key}' minimal {minimum}.")
        return default
    if maximum is not None and value > maximum:
        errors.append(f"Field '{key}' maksimal {maximum}.")
        return default
    return value


def _clean_choice(payload, key, errors, choices, *, required=False, default=None):
    value = payload.get(key, None)
    if value is None:
        if required:
            errors.append(f"Field '{key}' wajib diisi.")
        return default
    if not isinstance(value, str):
        errors.append(f"Field '{key}' harus berupa string.")
        return default
    value = value.strip().upper()
    if value not in choices:
        errors.append(f"Field '{key}' harus salah satu dari: {', '.join(choices)}.")
        return default
    return value


def _clean_timestamp(payload, key, errors):
    """Terima ISO-8601 (termasuk akhiran 'Z'). Opsional.
    Jika tidak dikirim atau kosong, server memakai waktu sekarang.
    """
    value = payload.get(key, None)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        errors.append(f"Field '{key}' harus berupa string ISO-8601.")
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        errors.append(
            f"Field '{key}' harus format ISO-8601, contoh: 2026-08-13T00:00:00Z."
        )
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _clean_coordinates(payload, errors, *, required=False):
    latitude = _clean_float(
        payload, "latitude", errors, required=required, minimum=-90, maximum=90
    )
    longitude = _clean_float(
        payload, "longitude", errors, required=required, minimum=-180, maximum=180
    )
    return latitude, longitude


# --- Validator per endpoint ----------------------------------------------


def validate_device_register(payload):
    """POST /api/device/register"""
    payload, errors = _require_dict(payload)
    if errors:
        return None, errors

    data = {
        "device_id": _clean_string(
            payload, "device_id", errors, required=True, max_length=MAX_DEVICE_ID
        ),
        "name": _clean_string(payload, "name", errors, max_length=MAX_NAME),
        "location": _clean_string(payload, "location", errors, max_length=MAX_LOCATION),
        "firmware_version": _clean_string(
            payload, "firmware_version", errors, max_length=32, default="unknown"
        ),
    }
    data["latitude"], data["longitude"] = _clean_coordinates(payload, errors)

    if errors:
        return None, errors
    if not data["firmware_version"]:
        data["firmware_version"] = "unknown"
    return data, []


def validate_heartbeat(payload):
    """POST /api/device/heartbeat"""
    payload, errors = _require_dict(payload)
    if errors:
        return None, errors

    data = {
        "device_id": _clean_string(
            payload, "device_id", errors, required=True, max_length=MAX_DEVICE_ID
        ),
        "status": _clean_choice(
            payload, "status", errors, DEVICE_STATUS, default="ONLINE"
        ),
        "network": _clean_bool(payload, "network", errors, default=True),
        "audio": _clean_bool(payload, "audio", errors, default=True),
        "camera": _clean_bool(payload, "camera", errors, default=False),
        # Keadaan sensor tamper (kotak perangkat dibuka paksa).
        #
        # Default False dipilih sadar: firmware lama tidak mengirim field ini,
        # dan menganggap "tidak dikirim" sebagai tamper aktif akan memunculkan
        # peringatan palsu untuk seluruh perangkat yang belum diperbarui.
        # Konsekuensinya, perangkat berfirmware lama TIDAK dapat melaporkan
        # tamper - itu keterbatasan yang diketahui, bukan kelalaian.
        "tamper": _clean_bool(payload, "tamper", errors, default=False),
        "firmware_version": _clean_string(
            payload, "firmware_version", errors, max_length=32, default=""
        ),
    }

    if errors:
        return None, errors
    return data, []


def validate_tamper(payload):
    """POST /api/device/tamper

    Laporan sensor tamper dari perangkat. Sengaja TERPISAH dari
    /api/emergency/evaluate: tamper bukan keadaan darurat korban dan tidak
    memiliki bukti SOS maupun audio, sehingga bila dimasukkan ke verifikasi
    tahap 2 ia akan selalu jatuh menjadi FALSE_ALARM dan mengotori data
    incident.

    Field `tamper` wajib dan eksplisit. Tidak ada nilai default di sini:
    laporan tamper yang tidak menyebutkan keadaannya tidak bermakna, dan
    menebaknya berisiko menyembunyikan pembongkaran yang sebenarnya terjadi.
    """
    payload, errors = _require_dict(payload)
    if errors:
        return None, errors

    data = {
        "device_id": _clean_string(
            payload, "device_id", errors, required=True, max_length=MAX_DEVICE_ID
        ),
        "tamper": _clean_bool(payload, "tamper", errors, required=True),
        "firmware_version": _clean_string(
            payload, "firmware_version", errors, max_length=32, default=""
        ),
        "note": _clean_string(payload, "note", errors, max_length=255, default=""),
    }

    if errors:
        return None, errors
    return data, []


# Panjang maksimum event_id (idempotency key dari perangkat).
MAX_EVENT_ID = 64


def validate_emergency_evaluate(payload):
    """POST /api/emergency/evaluate

    Payload minimal dari ESP32:
        device_id, sos, audio_confidence, audio_class, latitude, longitude, timestamp

    Field opsional `event_id` berfungsi sebagai IDEMPOTENCY KEY: perangkat
    membuat satu nilai untuk satu kejadian SOS dan memakainya kembali pada
    setiap retry, sehingga timeout jaringan tidak menghasilkan incident ganda.
    Bila tidak dikirim, perilaku lama dipertahankan (setiap request membuat
    incident baru).
    """
    payload, errors = _require_dict(payload)
    if errors:
        return None, errors

    data = {
        "device_id": _clean_string(
            payload, "device_id", errors, required=True, max_length=MAX_DEVICE_ID
        ),
        "sos": _clean_bool(payload, "sos", errors, required=True),
        "audio_confidence": _clean_float(
            payload,
            "audio_confidence",
            errors,
            required=True,
            minimum=0.0,
            maximum=1.0,
        ),
        "audio_class": _clean_string(
            payload,
            "audio_class",
            errors,
            max_length=MAX_AUDIO_CLASS,
            default="Unknown",
        ),
        # Opsional: ESP32 boleh mengirim hasil verifikasi lokalnya.
        # Jika tidak dikirim, server menghitungnya sendiri.
        "local_decision": _clean_choice(
            payload, "local_decision", errors, LOCAL_DECISIONS, default=None
        ),
        # Opsional: peluang kejadian bukan suara normal (1 - P(Normal)).
        # Berbeda makna dengan audio_confidence, jadi field terpisah.
        "audio_distress_probability": _clean_float(
            payload,
            "audio_distress_probability",
            errors,
            default=None,
            minimum=0.0,
            maximum=1.0,
        ),
        "timestamp": _clean_timestamp(payload, "timestamp", errors),
        # Idempotency key opsional dari perangkat. String kosong diperlakukan
        # sama dengan tidak dikirim, supaya firmware yang mengirim "" tidak
        # membuat seluruh kejadiannya dianggap satu event yang sama.
        "event_id": _clean_event_id(payload, errors),
    }
    data["latitude"], data["longitude"] = _clean_coordinates(payload, errors)

    # Opsional: fitur audio ringkas untuk dijalankan oleh model audio.
    # Nama dan satuan mengikuti ai_models.AudioDistressModel; tidak ada
    # format yang dikarang di sini.
    data["audio_features"] = _clean_audio_features(payload, errors)

    if errors:
        return None, errors
    if not data["audio_class"]:
        data["audio_class"] = "Unknown"
    return data, []


def _clean_event_id(payload, errors):
    """Validasi `event_id` opsional.

    Return None bila tidak dikirim atau kosong. Nilai kosong TIDAK dianggap
    sebagai kunci: bila "" diterima sebagai event_id, seluruh kejadian dari
    perangkat yang mengirim string kosong akan dianggap satu kejadian yang
    sama dan kejadian nyata berikutnya tidak akan terbuat.
    """
    value = payload.get("event_id", None)
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append("Field 'event_id' harus berupa string.")
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > MAX_EVENT_ID:
        errors.append(f"Field 'event_id' maksimal {MAX_EVENT_ID} karakter.")
        return None
    return value


# Nama fitur audio ringkas yang dikenal ai_models.AudioDistressModel.
AUDIO_FEATURE_KEYS = (
    "energy",
    "peak",
    "zero_crossing_rate",
    "dominant_frequency",
    "duration_ms",
)


def _clean_audio_features(payload, errors):
    """Validasi field opsional `audio_features`.

    Menerima dua bentuk (keduanya didukung ai_models.py):

      1. {"class_probabilities": {"Normal": 0.1, "Scream/Teriakan": 0.9, ...}}
         Hasil inferensi di perangkat.

      2. {"energy": 0.8, "peak": 0.9, "zero_crossing_rate": 0.4,
          "dominant_frequency": 2600, "duration_ms": 900}
         Fitur ringkas yang dihitung perangkat.

    Return None bila tidak dikirim. Field yang tidak dikenal diabaikan tanpa
    error, supaya firmware versi lebih baru tidak ditolak server.
    """
    value = payload.get("audio_features", None)
    if value is None:
        return None
    if not isinstance(value, dict):
        errors.append("Field 'audio_features' harus berupa objek JSON.")
        return None

    hasil = {}

    probabilitas = value.get("class_probabilities")
    if probabilitas is not None:
        if not isinstance(probabilitas, dict) or not probabilitas:
            errors.append(
                "Field 'audio_features.class_probabilities' harus objek JSON "
                "tidak kosong."
            )
        else:
            bersih = {}
            for label, peluang in probabilitas.items():
                if isinstance(peluang, bool) or not isinstance(peluang, (int, float)):
                    errors.append(
                        f"Nilai class_probabilities['{label}'] harus angka."
                    )
                    continue
                bersih[str(label)] = float(peluang)
            if bersih:
                hasil["class_probabilities"] = bersih

    for key in AUDIO_FEATURE_KEYS:
        if key not in value:
            continue
        angka = value.get(key)
        if isinstance(angka, bool) or not isinstance(angka, (int, float)):
            errors.append(f"Field 'audio_features.{key}' harus berupa angka.")
            continue
        hasil[key] = float(angka)

    return hasil or None


def validate_device_context_config(payload):
    """PUT /api/device/<device_id>/config

    Konfigurasi konteks device untuk Random Forest. Seluruh field opsional:
    hanya yang dikirim yang diubah.

    Nilai kategorikal divalidasi terhadap kosakata model (RF_*). Nilai di luar
    kosakata DITOLAK dengan HTTP 400, bukan diterima lalu diubah menjadi
    vektor nol secara diam-diam oleh OneHotEncoder(handle_unknown='ignore').
    """
    payload, errors = _require_dict(payload)
    if errors:
        return None, errors

    data = {}

    def pilih(key, choices):
        """Validasi pilihan dengan mempertahankan huruf besar/kecil aslinya.

        _clean_choice() memaksa .upper(), sedangkan kosakata model memakai
        bentuk seperti 'Main Road' dan 'Babakan Sari', sehingga tidak dapat
        dipakai di sini.
        """
        if key not in payload:
            return
        value = payload.get(key)
        if value is None:
            # Mengirim null berarti mengosongkan nilai.
            data[key] = None
            return
        if not isinstance(value, str):
            errors.append(f"Field '{key}' harus berupa string.")
            return
        target = " ".join(value.split())
        for sah in choices:
            if sah.lower() == target.lower():
                data[key] = sah
                return
        errors.append(
            f"Field '{key}' harus salah satu dari: {', '.join(choices)}. "
            f"Nilai '{value}' tidak dikenal model Random Forest."
        )

    pilih("village", RF_VILLAGES)
    pilih("road_type", RF_ROAD_TYPES)
    pilih("area_type", RF_AREA_TYPES)
    pilih("nearby_cctv", RF_YES_NO)
    pilih("nearby_police_post", RF_YES_NO)
    pilih("public_event", RF_YES_NO)
    pilih("holiday", RF_YES_NO)

    # Population_Density: angka bebas, TIDAK ada nilai default.
    # Pipeline memakai 'passthrough' (tanpa scaler), sehingga satuan harus
    # sama dengan dataset training. Server tidak dapat memvalidasi satuan,
    # jadi hanya memastikan nilainya angka non-negatif.
    if "population_density" in payload:
        value = payload.get("population_density")
        if value is None:
            data["population_density"] = None
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append("Field 'population_density' harus berupa angka.")
        elif value < 0:
            errors.append("Field 'population_density' tidak boleh negatif.")
        else:
            data["population_density"] = float(value)

    if errors:
        return None, errors
    if not data:
        return None, ["Tidak ada field konfigurasi yang dikirim."]
    return data, []


def validate_command_ack(payload):
    """POST /api/device/<device_id>/command/ack

    command_id opsional: jika tidak dikirim, server meng-ack command
    aktif terakhir untuk device tersebut.
    """
    payload, errors = _require_dict(payload if payload is not None else {})
    if errors:
        return None, errors

    command_id = payload.get("command_id", None)
    if command_id is not None:
        if isinstance(command_id, bool) or not isinstance(command_id, int):
            errors.append("Field 'command_id' harus berupa integer.")
        elif command_id <= 0:
            errors.append("Field 'command_id' harus lebih besar dari 0.")

    if errors:
        return None, errors
    return {"command_id": command_id}, []


def validate_operator_action(payload):
    """Aksi operator dari dashboard (confirm / false-alarm / close).
    Semua field opsional, hanya catatan tambahan.
    """
    payload, errors = _require_dict(payload if payload is not None else {})
    if errors:
        return None, errors

    note = _clean_string(payload, "note", errors, max_length=255, default="")
    if errors:
        return None, errors
    return {"note": note}, []
