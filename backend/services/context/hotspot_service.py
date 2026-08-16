"""Hotspot risk service — jembatan antara data konteks dan Random Forest.

Tanggung jawab file ini:

1. Menyusun 18 fitur sesuai `pipeline.feature_names_in_` (urutan dibaca dari
   model, tidak ditulis manual).
2. Memvalidasi setiap nilai kategorikal terhadap kosakata model.
3. MENOLAK memanggil model bila ada fitur wajib yang tidak tersedia,
   alih-alih mengisinya dengan angka karangan.
4. Mengembalikan status terstruktur sehingga kegagalan tidak pernah
   membuat server crash.

MENGAPA HARUS MENOLAK, BUKAN MENGISI NILAI DEFAULT
--------------------------------------------------
Pipeline memakai `'passthrough'` untuk 6 fitur numerik: TIDAK ADA scaler.
Nilai numerik masuk apa adanya ke RandomForestClassifier, sehingga satuan
dan skalanya harus sama dengan saat training. Mengisi `Population_Density`
dengan angka karangan (0, 1, atau 5000) akan menggeser hasil prediksi secara
tidak terkendali, dan kesalahan itu tidak akan terlihat karena model tetap
mengembalikan label yang tampak wajar.

Untuk fitur kategorikal risikonya berbeda tetapi sama seriusnya: encoder
dibuat dengan `handle_unknown='ignore'`, jadi nilai tak dikenal menjadi
vektor nol tanpa peringatan apa pun.

Karena itu:
  - `Population_Density` belum tersedia  -> status MISSING_FEATURES,
    model TIDAK dipanggil, hotspot_risk = None.
  - Verifikasi tahap 2 menangani hotspot None dengan membagi ulang bobot
    (lihat services/verification.py), bukan menganggapnya nol.
"""

from backend.services.ai import model_loader
from backend.services.context import vocab

# Fitur numerik yang WAJIB ada nilainya sebelum model dipanggil.
# Tidak boleh diisi nilai default karena pipeline tidak memakai scaler.
REQUIRED_NUMERIC = (
    "Hour",
    "Temperature",
    "Rainfall",
    "Previous_Incidents_Last30Days",
    "Emergency_Call_Last30Days",
    "Population_Density",
)

# Fitur kategorikal yang WAJIB dikenali kosakata model.
REQUIRED_CATEGORICAL = (
    "Day_of_Week",
    "Month",
    "Village",
    "Weather",
    "Public_Event",
    "Holiday",
    "Traffic_Level",
    "Lighting_Condition",
    "Nearby_CCTV",
    "Nearby_Police_Post",
    "Road_Type",
    "Area_Type",
)


def _risk_level_to_score(risk_level: str) -> float | None:
    """Ubah label kelas model menjadi angka 0.0-1.0 untuk skoring.

    Pemetaan ini adalah keputusan lapisan aplikasi, bukan keluaran model.
    Model hanya menghasilkan label ('High'/'Medium'/'Low') dan probabilitas.
    """
    return {"LOW": 0.25, "MEDIUM": 0.60, "HIGH": 0.90}.get(
        str(risk_level).strip().upper()
    )


def build_features(
    *,
    moment,
    weather: dict,
    traffic: dict,
    lighting: dict,
    device_config: dict,
    history: dict,
) -> tuple[dict, list[str]]:
    """Susun dict 18 fitur beserta daftar fitur yang bermasalah.

    Return (features, masalah). `masalah` kosong berarti seluruh fitur sah.
    Nilai yang tidak sah diisi None agar mudah ditampilkan di dashboard,
    tetapi keberadaannya dicatat di `masalah` sehingga model tidak dipanggil.
    """
    masalah: list[str] = []

    def catat(nama: str, nilai, alasan: str):
        if nilai is None:
            masalah.append(f"{nama}: {alasan}")
        return nilai

    # --- Waktu (REAL, diturunkan dari waktu server) ---
    hour = moment.hour
    day_of_week = vocab.day_of_week_name(moment)
    month = vocab.month_name(moment)

    # --- Cuaca (REAL API bila berhasil) ---
    weather_model = catat(
        "Weather",
        weather.get("weather_model"),
        f"nilai '{weather.get('weather')}' tidak dapat dipetakan "
        f"(status {weather.get('status')})",
    )
    temperature = catat(
        "Temperature",
        weather.get("temperature"),
        "tidak tersedia dari API cuaca",
    )
    rainfall = weather.get("rainfall")
    if rainfall is None:
        catat("Rainfall", None, "tidak tersedia dari API cuaca")

    # --- Lalu lintas (REAL API bila ada TOMTOM_API_KEY) ---
    traffic_model = catat(
        "Traffic_Level",
        traffic.get("traffic_level_model"),
        f"tidak tersedia (status {traffic.get('status')})",
    )

    # --- Pencahayaan (ESTIMASI, bukan sensor) ---
    lighting_model = catat(
        "Lighting_Condition",
        lighting.get("lighting_condition_model"),
        f"tidak tersedia (status {lighting.get('status')})",
    )

    # --- Konfigurasi per-device (USER CONFIG) ---
    village = catat(
        "Village",
        vocab.map_village(device_config.get("village")),
        (
            f"'{device_config.get('village')}' bukan salah satu dari 6 kelurahan "
            f"yang dikenal model ({', '.join(vocab.MODEL_VILLAGE)})"
        ),
    )
    road_type = catat(
        "Road_Type",
        vocab.map_road_type(device_config.get("road_type")),
        f"'{device_config.get('road_type')}' tidak dikenal model",
    )
    area_type = catat(
        "Area_Type",
        vocab.map_area_type(device_config.get("area_type")),
        f"'{device_config.get('area_type')}' tidak dikenal model",
    )
    nearby_cctv = catat(
        "Nearby_CCTV",
        vocab.map_yes_no(device_config.get("nearby_cctv")),
        "nilai harus Yes atau No",
    )
    nearby_police = catat(
        "Nearby_Police_Post",
        vocab.map_yes_no(device_config.get("nearby_police_post")),
        "nilai harus Yes atau No",
    )

    # Population_Density: TIDAK ADA NILAI DEFAULT.
    # Pipeline tanpa scaler membuat angka karangan berbahaya, jadi selama
    # nilainya belum diisi pengguna, fitur ini dianggap tidak tersedia.
    population_density = device_config.get("population_density")
    if population_density is None:
        masalah.append(
            "Population_Density: NOT_AVAILABLE — belum diisi. Nilai tidak "
            "boleh dikarang karena pipeline tidak memakai scaler; satuan "
            "harus sama dengan dataset training."
        )

    # --- Public_Event / Holiday (STATIC CONFIG / MOCK) ---
    # Tidak ada sumber kalender hari libur maupun jadwal acara. Nilai default
    # 'No' dan dapat diubah manual per device.
    public_event = catat(
        "Public_Event",
        vocab.map_yes_no(device_config.get("public_event", "No")),
        "nilai harus Yes atau No",
    )
    holiday = catat(
        "Holiday",
        vocab.map_yes_no(device_config.get("holiday", "No")),
        "nilai harus Yes atau No",
    )

    # --- Riwayat (REAL, dari database sendiri) ---
    previous_incidents = history.get("previous_incidents_last30days")
    emergency_calls = history.get("emergency_call_last30days")
    if previous_incidents is None:
        catat("Previous_Incidents_Last30Days", None, "gagal dihitung dari database")
    if emergency_calls is None:
        catat("Emergency_Call_Last30Days", None, "gagal dihitung dari database")

    features = {
        "Hour": hour,
        "Day_of_Week": day_of_week,
        "Month": month,
        "Village": village,
        "Weather": weather_model,
        "Temperature": temperature,
        "Rainfall": rainfall,
        "Public_Event": public_event,
        "Holiday": holiday,
        "Traffic_Level": traffic_model,
        "Lighting_Condition": lighting_model,
        "Nearby_CCTV": nearby_cctv,
        "Nearby_Police_Post": nearby_police,
        "Previous_Incidents_Last30Days": previous_incidents,
        "Emergency_Call_Last30Days": emergency_calls,
        "Population_Density": population_density,
        "Road_Type": road_type,
        "Area_Type": area_type,
    }

    return features, masalah


def _urutkan_sesuai_model(features: dict) -> dict:
    """Susun ulang fitur mengikuti urutan feature_names_in_ dari model.

    predict() memakai DataFrame dengan nama kolom, jadi urutan sebenarnya
    tidak wajib. Ini dilakukan agar sisi kita tetap konsisten dan agar
    ketidakcocokan nama kolom terdeteksi lebih awal.
    """
    urutan = model_loader.expected_features() or list(vocab.RF_FEATURE_ORDER)
    tersusun = {nama: features.get(nama) for nama in urutan}
    # Sertakan fitur tambahan yang mungkin belum ada di daftar urutan.
    for nama, nilai in features.items():
        tersusun.setdefault(nama, nilai)
    return tersusun


def predict_hotspot(
    *,
    moment,
    weather: dict,
    traffic: dict,
    lighting: dict,
    device_config: dict,
    history: dict,
) -> dict:
    """Prediksi hotspot risk memakai random_forest_pipeline.pkl.

    Return dict dengan kunci tetap:
        status          : OK | MISSING_FEATURES | MODEL_ERROR | PREDICT_ERROR
        risk_level      : High | Medium | Low, atau None
        risk_score      : 0.0-1.0 (turunan risk_level), atau None
        confidence      : persen keyakinan model, atau None
        priority        : HIGH | MEDIUM | LOW, atau None
        probability     : dict per kelas, atau {}
        recommendation  : list saran, atau []
        features        : fitur yang dipakai/dicoba
        missing         : daftar fitur bermasalah
        model           : metadata singkat model
        message         : penjelasan bila tidak OK

    Fungsi ini TIDAK PERNAH melempar exception.
    """
    features, masalah = build_features(
        moment=moment,
        weather=weather,
        traffic=traffic,
        lighting=lighting,
        device_config=device_config,
        history=history,
    )
    features = _urutkan_sesuai_model(features)

    dasar = {
        "risk_level": None,
        "risk_score": None,
        "confidence": None,
        "priority": None,
        "probability": {},
        "recommendation": [],
        "features": features,
        "missing": masalah,
        "model": "random_forest_pipeline.pkl",
    }

    # Model tidak dipanggil bila ada fitur yang tidak sah.
    if masalah:
        dasar["status"] = "MISSING_FEATURES"
        dasar["message"] = (
            f"{len(masalah)} fitur belum sah, prediksi hotspot dilewati agar "
            "tidak menghasilkan angka yang menyesatkan."
        )
        return dasar

    status_model = model_loader.model_status()
    if status_model["status"] == "ERROR":
        dasar["status"] = "MODEL_ERROR"
        dasar["message"] = status_model["error"]
        return dasar

    try:
        # Import di dalam fungsi supaya modul context tetap dapat diimpor
        # walau pandas/scikit-learn belum terpasang.
        from backend.services.ai.core import rf_predictor

        hasil = rf_predictor.predict_risk(features)
    except Exception as error:  # noqa: BLE001 - fail-safe
        dasar["status"] = "PREDICT_ERROR"
        dasar["message"] = f"{type(error).__name__}: {error}"
        return dasar

    risk_level = hasil.get("risk_level")

    dasar.update(
        status="OK",
        risk_level=risk_level,
        risk_score=_risk_level_to_score(risk_level),
        confidence=hasil.get("confidence"),
        priority=hasil.get("priority"),
        probability=hasil.get("probability", {}),
        recommendation=hasil.get("recommendation", []),
        status_color=hasil.get("status_color"),
    )
    return dasar
