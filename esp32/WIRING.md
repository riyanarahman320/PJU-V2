# Wiring ASEP-JAGA (ESP32-S3)

**WIRING BELUM FINAL.** Seluruh pin di dokumen ini bertanda `PIN TO CONFIRM`.
Angka yang tercantum adalah pilihan awal yang wajar untuk ESP32-S3 generik,
bukan hasil pengukuran pada board dan aktuator yang benar-benar dipakai.
Periksa datasheet board Anda, lalu perbarui `esp32/include/config.h` dan
dokumen ini bersamaan.

## Pin yang dipakai

| Fungsi | GPIO | Mode | Status |
|---|---|---|---|
| Tombol SOS | 4 | `INPUT_PULLUP` | PIN TO CONFIRM |
| Strobe | 5 | `OUTPUT` via driver | PIN TO CONFIRM |
| Sirene | 6 | `OUTPUT` via driver | PIN TO CONFIRM |
| Speaker / modul suara | 7 | `OUTPUT` via driver | PIN TO CONFIRM |
| LED status jaringan | 15 | `OUTPUT` | PIN TO CONFIRM |
| Mikrofon I2S BCLK | 16 | I2S | PIN TO CONFIRM, belum dipakai |
| Mikrofon I2S LRCL/WS | 17 | I2S | PIN TO CONFIRM, belum dipakai |
| Mikrofon I2S DOUT | 18 | I2S | PIN TO CONFIRM, belum dipakai |

## Pin yang dihindari dan alasannya

ESP32-S3 memiliki beberapa GPIO yang tidak bebas dipakai. Pin di atas dipilih
dengan menghindari:

| GPIO | Alasan |
|---|---|
| 0, 45, 46 | Strapping pin; menentukan mode boot. Beban di sini dapat membuat board gagal boot. |
| 19, 20 | USB D− / D+ untuk USB-Serial-JTAG. Dipakai akan mengganggu upload dan Serial Monitor. |
| 26–32 | Terhubung SPI flash internal. |
| 33–37 | Dipakai bila modul memakai octal PSRAM (mis. varian N8R8). |
| 43, 44 | UART0 TX/RX, dipakai Serial Monitor. |

Bila varian board Anda memakai octal PSRAM, jangan memakai GPIO 33–37 sama
sekali. Periksa penandaan modul (mis. `N16R8`) sebelum menyolder.

## Tombol SOS

```
GPIO 4  ──────┬────[ tombol ]──── GND
              │
        pull-up internal (INPUT_PULLUP)
```

Tombol menghubungkan pin ke GND, jadi `LOW` berarti ditekan. Pull-up internal
sudah diaktifkan firmware sehingga tidak perlu resistor luar. Debounce
dilakukan di software (`BUTTON_DEBOUNCE_MS`, 50 ms), tetapi kapasitor 100 nF
paralel dengan tombol akan membantu bila kabel ke tombol panjang.

Untuk tombol di ruang publik, gunakan tombol dengan penutup pelindung agar
tidak mudah tertekan tanpa sengaja.

## Strobe, sirene, dan speaker

**Jangan menyambungkan beban ini langsung ke GPIO.** Pin ESP32-S3 hanya mampu
mengalirkan arus kecil (orde puluhan mA), sedangkan strobe dan sirene 12 V
menarik jauh lebih besar. Menyambung langsung akan merusak pin atau board.

Gunakan modul relay atau MOSFET:

```
GPIO 5 ──── IN  ┌──────────────┐
                │ modul relay  │  COM/NO ──── strobe 12 V ──── PSU 12 V (+)
GND    ──── GND │ atau MOSFET  │
5V/3V3 ──── VCC └──────────────┘  strobe (−) ──── PSU 12 V (−)
```

Hal yang perlu diperhatikan:

- **Level aktif.** Banyak modul relay murah bersifat *active-LOW*: pin `LOW`
  menyalakan beban. Modul MOSFET umumnya *active-HIGH*. Sesuaikan
  `ACTUATOR_ACTIVE_HIGH` di `config.h`. Salah nilai membuat **sirene berbunyi
  segera saat board dinyalakan** — periksa ini sebelum memasang di lapangan.
- **Tegangan logika.** ESP32-S3 bekerja pada 3,3 V. Modul relay yang menuntut
  sinyal 5 V mungkin tidak andal dipicu dari 3,3 V; pilih modul dengan
  optocoupler yang mendukung 3,3 V.
- **Ground bersama.** GND ESP32 dan GND modul harus tersambung, tetapi jalur
  daya beban 12 V dipisah dari jalur 5 V logika.
- **Beban induktif.** Sirene dan relay menimbulkan lonjakan tegangan saat
  dimatikan. Pasang dioda flyback (mis. 1N4007) paralel dengan beban DC.

## Mikrofon — belum terpasang

**MICROPHONE HARDWARE INTEGRATION REQUIRED.**

Mikrofon belum dipilih, jadi tidak ada driver di firmware dan tidak ada
library audio di `platformio.ini`. Pin I2S di tabel hanya disiapkan.

Bila nanti memakai mikrofon I2S seperti INMP441 atau SPH0645:

```
INMP441        ESP32-S3
-------        --------
VDD    ──────  3V3
GND    ──────  GND
SCK    ──────  GPIO 16   (BCLK)
WS     ──────  GPIO 17   (LRCL)
SD     ──────  GPIO 18   (DOUT)
L/R    ──────  GND       (kanal kiri)
```

Yang perlu diisi di firmware adalah `readAudioFeatures()` di
`esp32/src/main.cpp`: baca blok sampel I2S, hitung `energy`, `peak`,
`zero_crossing_rate`, `dominant_frequency`, `duration_ms`, lalu set
`valid = true`. Nama field itu sudah cocok dengan `AUDIO_FEATURE_KEYS` di
`backend/schemas.py`, sehingga server dapat menjalankan model audionya tanpa
perubahan apa pun.

Selama `valid == false`, firmware tidak mengirim `audio_features` dan
melaporkan `audio: false` pada heartbeat. Ini disengaja: perangkat tidak boleh
mengaku memiliki bukti audio yang tidak diukurnya.

## Daya

Belum ada rancangan daya final. Pertimbangan yang perlu diselesaikan:

- **Dua rel tegangan.** Strobe dan sirene umumnya 12 V, sedangkan ESP32-S3
  butuh 5 V (lewat USB/VIN) atau 3,3 V. Gunakan PSU 12 V ditambah konverter
  step-down ke 5 V.
- **Kapasitas.** Jumlahkan arus puncak strobe dan sirene saat menyala
  bersamaan, lalu beri margin. Sirene adalah beban terbesar.
- **Lonjakan saat sirene menyala.** Sirene yang menyala dapat menurunkan
  tegangan sesaat dan membuat ESP32 reboot. Pasang kapasitor elektrolit besar
  (mis. 1000 µF) pada rel 12 V dekat sirene, dan pisahkan jalur daya logika.
- **Cadangan daya.** PJU mati berarti perangkat mati. Bila kejadian darurat
  justru sering terjadi saat listrik padam, perlu baterai cadangan. Ini belum
  dirancang.

## Yang belum diputuskan

- Varian board ESP32-S3 yang dipakai (memengaruhi pin dan PSRAM).
- Model mikrofon.
- Modul suara untuk `playVoiceMessage()` (DFPlayer Mini, I2S DAC, atau lain).
- Jenis strobe dan sirene beserta arus kerjanya.
- Rancangan daya dan cadangan baterai.
- Enclosure dan ketahanan cuaca untuk pemasangan di tiang PJU.