"""Smoke check FASE 7: memastikan seluruh lapisan tersambung.

Menguji secara langsung (tanpa HTTP):
    1. Pemuatan random_forest_pipeline.pkl
    2. Pemetaan kosakata (ketidakcocokan senyap)
    3. Prediksi hotspot, termasuk penolakan saat fitur belum lengkap
    4. Adapter audio
    5. Verifikasi tahap 1
    6. Verifikasi tahap 2 (rule-based)

Jalankan:
    .venv\\Scripts\\python.exe scripts\\smoke_check.py
"""

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services import verification  # noqa: E402
from backend.services.ai import audio_service, model_loader  # noqa: E402
from backend.services.context import hotspot_service, vocab  # noqa: E402

gagal = []


def cek(nama: str, syarat: bool, detail: str = ""):
    status = "LULUS" if syarat else "GAGAL"
    print(f"[{status}] {nama}" + (f" -- {detail}" if detail else ""))
    if not syarat:
        gagal.append(nama)


def bagian(judul: str):
    print()
    print("=" * 70)
    print(judul)
    print("=" * 70)


def ringkasan() -> int:
    """Cetak hasil akhir. Return exit code: 0 lulus, 1 ada yang gagal."""
    print()
    print("=" * 70)
    if gagal:
        print(f"HASIL: {len(gagal)} pemeriksaan GAGAL")
        for nama in gagal:
            print("  -", nama)
        print("=" * 70)
        return 1
    print("HASIL: SEMUA PEMERIKSAAN LULUS")
    print("=" * 70)
    return 0


# --- Data konteks yang dipakai beberapa bagian ---------------------------
MOMENT = datetime(2026, 8, 13, 22, 30)

WEATHER_OK = {
    "weather": "Clear",
    "weather_model": "Sunny",
    "temperature": 24.5,
    "rainfall": 0.0,
    "status": "REAL_API",
}
TRAFFIC_OK = {
    "traffic_level": "Low",
    "traffic_level_model": "Low",
    "status": "REAL_API",
}
LIGHTING_OK = {
    "lighting_condition": "Poor",
    "lighting_condition_model": "Poor",
    "is_dark": True,
    "status": "ESTIMATED",
}
HISTORY_OK = {
    "previous_incidents_last30days": 2,
    "emergency_call_last30days": 5,
    "history_score": 0.6,
    "status": "REAL_OWN_DATABASE",
}

# Konfigurasi device demo sesuai keputusan pengguna.
# Population_Density sengaja None: nilainya belum diberikan.
CONFIG_TANPA_DENSITY = {
    "village": "Babakan Sari",
    "road_type": "Main Road",
    "area_type": "Public Facility",
    "nearby_cctv": "Yes",
    "nearby_police_post": "No",
    "population_density": None,
    "public_event": "No",
    "holiday": "No",
}


def main() -> int:
    bagian("1. MODEL LOADING")

    model_loader.configure(
        str(
            PROJECT_ROOT
            / "backend"
            / "models_store"
            / "random_forest_pipeline.pkl"
        )
    )
    # Model dimuat lazy, jadi pemuatan dipicu lebih dulu sebelum status
    # dibaca. try_load() tidak melempar exception.
    berhasil = model_loader.try_load()
    status = model_loader.model_status()
    cek("model dimuat", berhasil and status["loaded"], status.get("error") or status["status"])
    cek(
        "tidak ada warning versi sklearn",
        not status["load_warnings"],
        str(status["load_warnings"]),
    )

    meta = model_loader.model_metadata()
    cek("18 fitur", meta.get("n_features_in") == 18, str(meta.get("n_features_in")))
    cek(
        "3 kelas High/Low/Medium",
        meta.get("classes") == ["High", "Low", "Medium"],
        str(meta.get("classes")),
    )
    cek(
        "urutan fitur cocok dengan vocab.RF_FEATURE_ORDER",
        meta.get("feature_names") == list(vocab.RF_FEATURE_ORDER),
    )

    vocab_model = model_loader.category_vocabulary()
    cek(
        "kosakata Weather terbaca dari model",
        vocab_model.get("Weather")
        == ["Cloudy", "Fog", "Heavy Rain", "Rain", "Sunny"],
        str(vocab_model.get("Weather")),
    )
    cek(
        "kosakata Village 6 kelurahan",
        len(vocab_model.get("Village", [])) == 6,
        str(vocab_model.get("Village")),
    )

    bagian("2. PEMETAAN KOSAKATA (ketidakcocokan senyap)")

    cek("Clear -> Sunny", vocab.map_weather("Clear") == "Sunny")
    cek("Storm -> Heavy Rain", vocab.map_weather("Storm") == "Heavy Rain")
    cek("Unknown -> None (tidak dipaksakan)", vocab.map_weather("Unknown") is None)
    cek("Rain + 15mm -> Heavy Rain", vocab.map_weather("Rain", 15.0) == "Heavy Rain")
    cek("Low -> Low", vocab.map_traffic("Low") == "Low")
    cek("QUIET (kosakata lama) -> Low", vocab.map_traffic("QUIET") == "Low")
    cek(
        "Babakan Sari dikenal",
        vocab.map_village("babakan sari") == "Babakan Sari",
    )
    cek("kelurahan luar wilayah -> None", vocab.map_village("Menteng") is None)

    bagian("3. HOTSPOT PREDICTION")

    # 3a. Population_Density belum diisi -> model TIDAK dipanggil.
    hasil = hotspot_service.predict_hotspot(
        moment=MOMENT,
        weather=WEATHER_OK,
        traffic=TRAFFIC_OK,
        lighting=LIGHTING_OK,
        device_config=CONFIG_TANPA_DENSITY,
        history=HISTORY_OK,
    )
    cek(
        "tanpa Population_Density -> MISSING_FEATURES",
        hasil["status"] == "MISSING_FEATURES",
        hasil["status"],
    )
    cek("risk_score None (bukan 0.0)", hasil["risk_score"] is None)
    cek(
        "alasan menyebut Population_Density",
        any("Population_Density" in m for m in hasil["missing"]),
        str(hasil["missing"]),
    )

    # 3b. Seluruh 18 fitur terisi.
    # CATATAN PENTING: angka 12000 di bawah HANYA untuk membuktikan pipeline
    # dapat memprediksi ketika 18 fitur lengkap. Angka ini BUKAN nilai yang
    # direkomendasikan dan TIDAK dipakai sebagai default di mana pun dalam
    # sistem. Nilai sebenarnya harus diberikan pengguna sesuai satuan pada
    # dataset training.
    config_lengkap = dict(CONFIG_TANPA_DENSITY, population_density=12000.0)

    hasil2 = hotspot_service.predict_hotspot(
        moment=MOMENT,
        weather=WEATHER_OK,
        traffic=TRAFFIC_OK,
        lighting=LIGHTING_OK,
        device_config=config_lengkap,
        history=HISTORY_OK,
    )
    cek("18 fitur lengkap -> OK", hasil2["status"] == "OK", str(hasil2.get("message")))
    cek(
        "risk_level salah satu High/Medium/Low",
        hasil2["risk_level"] in ("High", "Medium", "Low"),
        str(hasil2["risk_level"]),
    )
    cek(
        "probability berjumlah ~100%",
        abs(sum(hasil2["probability"].values()) - 100.0) < 0.5,
        str(hasil2["probability"]),
    )
    print(
        f"        -> risk={hasil2['risk_level']} "
        f"conf={hasil2['confidence']}% prob={hasil2['probability']}"
    )

    # 3c. Cuaca tak dikenal harus menolak, bukan diam-diam jadi vektor nol.
    weather_unknown = dict(
        WEATHER_OK, weather="Unknown", weather_model=None, status="ERROR"
    )
    hasil3 = hotspot_service.predict_hotspot(
        moment=MOMENT,
        weather=weather_unknown,
        traffic=TRAFFIC_OK,
        lighting=LIGHTING_OK,
        device_config=config_lengkap,
        history=HISTORY_OK,
    )
    cek(
        "cuaca Unknown -> MISSING_FEATURES (tidak jadi vektor nol)",
        hasil3["status"] == "MISSING_FEATURES",
        hasil3["status"],
    )

    bagian("4. ADAPTER AUDIO")

    info = audio_service.model_info()
    cek("model audio tersedia", info["status"] == "OK")
    cek("4 kelas audio", len(info["classes"]) == 4, str(info["classes"]))

    hasil_audio = audio_service.analyze(
        {
            "energy": 0.9,
            "peak": 0.95,
            "zero_crossing_rate": 0.5,
            "dominant_frequency": 2800,
            "duration_ms": 1200,
        }
    )
    cek("inferensi fitur ringkas OK", hasil_audio["ai_status"] == "OK")
    cek(
        "source feature-fallback (tidak diklaim CNN)",
        hasil_audio["source"] == "feature-fallback",
        str(hasil_audio["source"]),
    )
    print(
        f"        -> kelas={hasil_audio['audio_class']} "
        f"distress={hasil_audio['audio_distress_probability']:.3f}"
    )

    hasil_hw = audio_service.analyze(
        {"class_probabilities": {"Normal": 0.05, "Scream/Teriakan": 0.95}}
    )
    cek(
        "class_probabilities perangkat dipakai",
        hasil_hw["source"] == "hardware-model-output",
        str(hasil_hw["source"]),
    )
    cek(
        "distress tinggi untuk teriakan",
        hasil_hw["audio_distress_probability"] > 0.9,
        str(hasil_hw["audio_distress_probability"]),
    )

    hasil_rusak = audio_service.analyze({"energy": "bukan angka"})
    cek(
        "input rusak tidak melempar exception",
        hasil_rusak["ai_status"] in ("OK", "ERROR"),
        hasil_rusak["ai_status"],
    )

    bagian("5. VERIFIKASI TAHAP 1 (SOS tidak boleh bypass audio)")

    cek(
        "SOS saja (audio 0.0) -> LOCAL_REJECTED",
        verification.verify_local(True, 0.0, "Normal", 0.60) == "LOCAL_REJECTED",
    )
    cek(
        "SOS + teriakan 0.8 -> LOCAL_VERIFIED",
        verification.verify_local(True, 0.8, "Scream/Teriakan", 0.60)
        == "LOCAL_VERIFIED",
    )
    cek(
        "tanpa SOS + teriakan 0.95 -> LOCAL_VERIFIED",
        verification.verify_local(False, 0.95, "Scream/Teriakan", 0.60)
        == "LOCAL_VERIFIED",
    )
    cek(
        "kosakata ai_models dikenali relevan",
        verification.is_emergency_audio_class("Scream/Teriakan"),
    )
    cek(
        "kosakata firmware dikenali relevan",
        verification.is_emergency_audio_class("CRY_FOR_HELP"),
    )
    cek(
        "Normal tidak relevan",
        not verification.is_emergency_audio_class("Normal"),
    )

    bagian("6. VERIFIKASI TAHAP 2 (RULE-BASED)")

    context_lengkap = {
        "summary": {
            "hotspot_risk": 0.90,
            "hotspot_level": "High",
            "hotspot_status": "OK",
            "history_score": 0.6,
            "weather": "Clear",
            "traffic_level": "Low",
            "is_dark": True,
        }
    }

    # SOS saja, tanpa bukti audio, di lokasi rawan: tetap FALSE_ALARM.
    hasil_sos = verification.verify_emergency(
        {
            "sos": True,
            "audio_confidence": 0.0,
            "audio_class": "Normal",
            "audio_distress_probability": 0.0,
            "local_decision": "LOCAL_VERIFIED",
            "context": context_lengkap,
            "threshold": 0.70,
        }
    )
    cek(
        "SOS saja + hotspot High -> FALSE_ALARM",
        hasil_sos["decision"] == "FALSE_ALARM",
        f"skor {hasil_sos['score']}",
    )

    # Audio 100% tanpa SOS dan tanpa konteks: belum cukup sendirian.
    hasil_audio_saja = verification.verify_emergency(
        {
            "sos": False,
            "audio_confidence": 1.0,
            "audio_class": "Scream/Teriakan",
            "audio_distress_probability": 1.0,
            "local_decision": "LOCAL_VERIFIED",
            "context": {"summary": {"hotspot_status": "MISSING_FEATURES"}},
            "threshold": 0.70,
        }
    )
    cek(
        "audio 100% tanpa SOS & tanpa konteks -> FALSE_ALARM",
        hasil_audio_saja["decision"] == "FALSE_ALARM",
        f"skor {hasil_audio_saja['score']}",
    )

    # Bukti berlapis: SOS + teriakan + hotspot High + gelap + jalan lengang.
    hasil_lengkap = verification.verify_emergency(
        {
            "sos": True,
            "audio_confidence": 0.95,
            "audio_class": "Scream/Teriakan",
            "audio_distress_probability": 0.95,
            "local_decision": "LOCAL_VERIFIED",
            "context": context_lengkap,
            "emergency_state": "EMERGENCY",
            "emergency_state_support": 1.0,
            "threshold": 0.70,
        }
    )
    cek(
        "bukti berlapis -> CONFIRMED",
        hasil_lengkap["decision"] == "CONFIRMED",
        f"skor {hasil_lengkap['score']}",
    )
    cek(
        "method RULE_BASED_SECOND_LEVEL",
        hasil_lengkap["method"] == "RULE_BASED_SECOND_LEVEL",
        hasil_lengkap["method"],
    )

    # LOCAL_REJECTED tidak boleh dinaikkan server.
    hasil_ditolak = verification.verify_emergency(
        {
            "sos": True,
            "audio_confidence": 1.0,
            "audio_class": "Scream/Teriakan",
            "local_decision": "LOCAL_REJECTED",
            "context": context_lengkap,
            "threshold": 0.70,
        }
    )
    cek(
        "LOCAL_REJECTED tetap FALSE_ALARM",
        hasil_ditolak["decision"] == "FALSE_ALARM",
        f"skor {hasil_ditolak['score']}",
    )

    # Hotspot tidak tersedia: bobot dikeluarkan, tidak dianggap nol.
    hasil_tanpa_hotspot = verification.verify_emergency(
        {
            "sos": True,
            "audio_confidence": 0.95,
            "audio_class": "Scream/Teriakan",
            "audio_distress_probability": 0.95,
            "local_decision": "LOCAL_VERIFIED",
            "context": {
                "summary": {
                    "hotspot_risk": None,
                    "hotspot_status": "MISSING_FEATURES",
                    "history_score": 0.6,
                    "weather": "Clear",
                    "traffic_level": "Low",
                    "is_dark": True,
                }
            },
            "emergency_state_support": 1.0,
            "threshold": 0.70,
        }
    )
    komponen = hasil_tanpa_hotspot["components"]
    cek(
        "hotspot None -> bobot dikeluarkan & dinormalisasi",
        komponen["hotspot"] is None and komponen["weight_used"] < 1.0,
        f"weight_used={komponen['weight_used']}",
    )
    cek(
        "tanpa hotspot masih dapat CONFIRMED bila bukti lain kuat",
        hasil_tanpa_hotspot["decision"] == "CONFIRMED",
        f"skor {hasil_tanpa_hotspot['score']}",
    )

    return ringkasan()


if __name__ == "__main__":
    raise SystemExit(main())
