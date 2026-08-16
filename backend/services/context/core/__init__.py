"""File service konteks asli milik pengguna.


ISI FILE DI FOLDER INI IDENTIK dengan yang diberikan pengguna:

    weather_service.py   berasal dari AI/model/weather_service.py
    traffic_service.py   berasal dari AI/model/traffic_service.py
    lighting_service.py  berasal dari AI/model/lighting_service.py

Fungsi publik yang dipertahankan:
    get_weather(latitude, longitude)
    get_traffic(latitude, longitude)
    get_lighting_condition(hour, weather, rainfall)

Penyesuaian untuk kebutuhan model dan dashboard dilakukan di lapisan adapter
satu tingkat di atas folder ini, bukan dengan mengubah file ini.
"""
