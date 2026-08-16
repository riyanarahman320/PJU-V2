"""Pemetaan kosakata antara service konteks dan Random Forest.


MENGAPA FILE INI ADA
--------------------
Pipeline memakai OneHotEncoder(handle_unknown='ignore'). Artinya nilai yang
tidak dikenal TIDAK menimbulkan error, tetapi diubah menjadi vektor nol
secara diam-diam. Model tetap mengembalikan prediksi yang tampak wajar
padahal fitur tersebut sebenarnya hilang.

Itu berbahaya, karena kosakata sumber data dan kosakata model berbeda:

    weather_service.py  ->  Clear, Cloudy, Rain, Storm, Unknown
    model (Weather)     ->  Sunny, Cloudy, Fog, Rain, Heavy Rain

'Clear', 'Storm', dan 'Unknown' tidak dikenal model. Tanpa pemetaan, tiga
nilai itu hilang tanpa jejak.

File ini menerjemahkan nilai secara eksplisit dan melaporkan apa saja yang
tidak dapat dipetakan, sehingga degradasi selalu terlihat, bukan tersembunyi.

SELURUH KOSAKATA MODEL DI BAWAH DIBACA DARI FILE .pkl (OneHotEncoder
categories_), bukan ditulis berdasarkan dugaan.
"""

# --- Kosakata model (hasil inspeksi random_forest_pipeline.pkl) ----------
# Dipakai sebagai acuan cadangan bila model belum dapat dimuat. Saat model
# tersedia, kosakata diambil langsung dari model lewat model_loader.

MODEL_WEATHER = ("Cloudy", "Fog", "Heavy Rain", "Rain", "Sunny")
MODEL_TRAFFIC = ("High", "Low", "Medium")
MODEL_LIGHTING = ("Good", "Moderate", "Poor")
MODEL_YES_NO = ("No", "Yes")
MODEL_VILLAGE = (
    "Babakan Sari",
    "Babakan Surabaya",
    "Cicaheum",
    "Kebon Jayanti",
    "Kebon Kangkung",
    "Sukapura",
)
MODEL_ROAD_TYPE = ("Alley", "Main Road", "Market Area", "Residential")
MODEL_AREA_TYPE = (
    "Commercial",
    "Public Facility",
    "Residential",
    "School",
    "Terminal",
    "Traditional Market",
)
MODEL_DAY_OF_WEEK = (
    "Friday",
    "Monday",
    "Saturday",
    "Sunday",
    "Thursday",
    "Tuesday",
    "Wednesday",
)
MODEL_MONTH = (
    "April",
    "August",
    "December",
    "February",
    "January",
    "July",
    "June",
    "March",
    "May",
    "November",
    "October",
    "September",
)

# Nama fitur sesuai urutan feature_names_in_ pada pipeline.
RF_FEATURE_ORDER = (
    "Hour",
    "Day_of_Week",
    "Month",
    "Village",
    "Weather",
    "Temperature",
    "Rainfall",
    "Public_Event",
    "Holiday",
    "Traffic_Level",
    "Lighting_Condition",
    "Nearby_CCTV",
    "Nearby_Police_Post",
    "Previous_Incidents_Last30Days",
    "Emergency_Call_Last30Days",
    "Population_Density",
    "Road_Type",
    "Area_Type",
)

RF_CATEGORICAL = (
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

RF_NUMERIC = (
    "Hour",
    "Temperature",
    "Rainfall",
    "Previous_Incidents_Last30Days",
    "Emergency_Call_Last30Days",
    "Population_Density",
)


# --- Pemetaan cuaca ------------------------------------------------------
# Kiri: keluaran weather_service.py (Open-Meteo, sudah dinormalisasi).
# Kanan: kategori yang dikenal model.
#
# Alasan tiap pemetaan:
#   Clear -> Sunny        : model tidak punya 'Clear'; 'Sunny' padanan terdekat.
#   Storm -> Heavy Rain   : model tidak punya 'Storm'; badai (kode WMO 95/96/99)
#                           selalu disertai hujan deras.
#   Unknown -> None       : TIDAK dipetakan. Cuaca tidak diketahui tidak boleh
#                           dipaksa menjadi kategori tertentu.
WEATHER_TO_MODEL = {
    "CLEAR": "Sunny",
    "SUNNY": "Sunny",
    "CLOUDY": "Cloudy",
    "FOG": "Fog",
    "RAIN": "Rain",
    "HEAVY RAIN": "Heavy Rain",
    "HEAVY_RAIN": "Heavy Rain",
    "STORM": "Heavy Rain",
    "THUNDERSTORM": "Heavy Rain",
}

# Ambang curah hujan (mm) untuk menaikkan 'Rain' menjadi 'Heavy Rain'.
# Konsisten dengan lighting_service.py yang memakai rainfall >= 10.
HEAVY_RAIN_MM = 10.0

TRAFFIC_TO_MODEL = {
    "LOW": "Low",
    "MEDIUM": "Medium",
    "HIGH": "High",
    # Istilah lama context_data.py (mock generasi pertama) tetap didukung
    # supaya incident lama dan test lama tidak rusak.
    "QUIET": "Low",
    "NORMAL": "Medium",
    "CONGESTED": "High",
}

LIGHTING_TO_MODEL = {
    "GOOD": "Good",
    "MODERATE": "Moderate",
    "POOR": "Poor",
}

YES_NO_TO_MODEL = {
    "YES": "Yes",
    "NO": "No",
    "TRUE": "Yes",
    "FALSE": "No",
    "1": "Yes",
    "0": "No",
}


def _lookup(table: dict, value) -> str | None:
    """Cari nilai pada tabel pemetaan tanpa memedulikan huruf besar/kecil."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    key = str(value).strip().upper()
    if not key:
        return None
    return table.get(key)


def map_weather(weather, rainfall=None) -> str | None:
    """Terjemahkan cuaca ke kategori model.

    Bila curah hujan >= HEAVY_RAIN_MM, 'Rain' dinaikkan menjadi 'Heavy Rain'
    karena model membedakan keduanya sedangkan Open-Meteo (lewat weather_code)
    tidak selalu memisahkannya.

    Return None bila cuaca tidak dapat dipetakan (mis. 'Unknown' saat API gagal).
    """
    hasil = _lookup(WEATHER_TO_MODEL, weather)

    if rainfall is not None:
        try:
            curah = float(rainfall)
        except (TypeError, ValueError):
            curah = 0.0
        if curah >= HEAVY_RAIN_MM and hasil in ("Rain", "Cloudy", "Sunny", "Fog"):
            hasil = "Heavy Rain"

    return hasil


def map_traffic(traffic) -> str | None:
    """Terjemahkan tingkat lalu lintas ke kategori model."""
    return _lookup(TRAFFIC_TO_MODEL, traffic)


def map_lighting(lighting) -> str | None:
    """Terjemahkan kondisi pencahayaan ke kategori model."""
    return _lookup(LIGHTING_TO_MODEL, lighting)


def map_yes_no(value) -> str | None:
    """Terjemahkan nilai boolean/teks menjadi 'Yes' atau 'No'."""
    return _lookup(YES_NO_TO_MODEL, value)


def map_village(village) -> str | None:
    """Cocokkan nama kelurahan dengan kosakata model.

    Pencocokan tidak memedulikan huruf besar/kecil dan spasi berlebih, tetapi
    TIDAK melakukan pencocokan samar (fuzzy). Kelurahan di luar 6 nilai yang
    dikenal model mengembalikan None, dan itu memang disengaja: model hanya
    dilatih untuk wilayah Kiaracondong, Bandung.
    """
    if not village:
        return None
    target = " ".join(str(village).split()).upper()
    for sah in MODEL_VILLAGE:
        if sah.upper() == target:
            return sah
    return None


def _match_enum(value, allowed) -> str | None:
    if not value:
        return None
    target = " ".join(str(value).split()).upper()
    for sah in allowed:
        if sah.upper() == target:
            return sah
    return None


def map_road_type(value) -> str | None:
    return _match_enum(value, MODEL_ROAD_TYPE)


def map_area_type(value) -> str | None:
    return _match_enum(value, MODEL_AREA_TYPE)


def day_of_week_name(moment) -> str:
    """Nama hari dalam bahasa Inggris sesuai kosakata model.

    Memakai indeks weekday() Python, bukan strftime('%A'), supaya hasilnya
    tidak berubah mengikuti locale sistem.
    """
    nama = (
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    )
    return nama[moment.weekday()]


def month_name(moment) -> str:
    """Nama bulan dalam bahasa Inggris sesuai kosakata model."""
    nama = (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    )
    return nama[moment.month - 1]
