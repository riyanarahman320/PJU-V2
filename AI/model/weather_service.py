import requests


def get_weather(latitude, longitude):
    """
    Mengambil cuaca saat ini berdasarkan koordinat PJU.
    """

    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": [
            "temperature_2m",
            "precipitation",
            "rain",
            "weather_code"
        ],
        "timezone": "Asia/Jakarta"
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=10
        )

        response.raise_for_status()

        data = response.json()

        current = data.get(
            "current",
            {}
        )

        temperature = current.get(
            "temperature_2m"
        )

        precipitation = current.get(
            "precipitation",
            0
        )

        rain = current.get(
            "rain",
            0
        )

        weather_code = current.get(
            "weather_code"
        )

        # ============================================
        # NORMALISASI WEATHER
        # ============================================

        if weather_code is None:

            weather = "Clear"

        elif weather_code == 0:

            weather = "Clear"

        elif weather_code in [1, 2, 3]:

            weather = "Cloudy"

        elif weather_code in [
            51, 53, 55,
            56, 57,
            61, 63, 65,
            66, 67,
            80, 81, 82
        ]:

            weather = "Rain"

        elif weather_code in [
            95, 96, 99
        ]:

            weather = "Storm"

        else:

            weather = "Cloudy"

        return {

            "temperature":
                temperature,

            "rainfall":
                precipitation,

            "rain":
                rain,

            "weather":
                weather,

            "weather_code":
                weather_code,

            "status":
                "success"
        }

    except Exception as e:

        print(
            "Weather API error:",
            e
        )

        return {

            "temperature":
                None,

            "rainfall":
                0,

            "rain":
                0,

            "weather":
                "Unknown",

            "weather_code":
                None,

            "status":
                "error",

            "message":
                str(e)
        }