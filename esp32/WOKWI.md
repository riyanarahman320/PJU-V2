# Simulasi Hardware Wokwi - ASEP-JAGA

Dokumen ini menjelaskan cara menjalankan firmware ESP32-S3 ASEP-JAGA di
simulator Wokwi, tanpa perangkat keras.

**Yang dibuktikan simulasi ini:** logika firmware, logika GPIO, alur jaringan,
integrasi API, alur command, dan perilaku fail-safe di tingkat software.

**Yang TIDAK dibuktikan:** apa pun tentang perangkat keras nyata. Lihat bagian
12 (Batasan simulasi) di akhir dokumen - bagian itu penting dan sebaiknya tidak
dilewati.


## 1. Tujuan simulasi

Membuktikan bahwa firmware, backend, verification engine, command system, dan
dashboard bekerja sebagai satu sistem end-to-end **sebelum** perangkat keras
dirakit.

Alur yang diuji:

```
WOKWI ESP32-S3
  -> SOS BUTTON (pushbutton / Serial)
  -> LOCAL AUDIO VERIFICATION (tahap 1, di perangkat)
  -> LOCAL_VERIFIED
  -> STROBE LED ON              <- fail-safe, tidak menunggu server
  -> WIFI (Wokwi-GUEST)
  -> NGROK
  -> FLASK
  -> CONTEXT ENGINE (hotspot / weather / traffic / lighting / history)
  -> SECOND-LEVEL VERIFICATION (tahap 2, rule-based)
  -> CONFIRMED / FALSE_ALARM
  -> COMMAND
  -> WOKWI ESP32
  -> SIREN BUZZER ON + SPEAKER INDICATOR ON
  -> DASHBOARD UPDATE
```

Firmware yang dipakai adalah firmware yang sudah ada (`src/main.cpp`). Tidak
ada firmware khusus Wokwi, dan tidak ada arsitektur yang diubah.


## 2. Komponen Wokwi

| Bagian | Komponen Wokwi | ID | Mewakili |
|---|---|---|---|
| Board | `board-esp32-s3-devkitc-1` | `esp` | ESP32-S3-DevKitC-1 |
| Tombol SOS | `wokwi-pushbutton` (merah) | `btnSos` | tombol SOS di tiang PJU |
| NORMAL AUDIO | `wokwi-pushbutton` (hijau) | `btnNormal` | **alat uji**, bukan hardware |
| DISTRESS AUDIO | `wokwi-pushbutton` (kuning) | `btnDistress` | **alat uji**, bukan hardware |
| POLL SERVER | `wokwi-pushbutton` (biru) | `btnPoll` | **alat uji**, bukan hardware |
| RESET | `wokwi-pushbutton` (putih) | `btnReset` | **alat uji**, bukan hardware |
| Strobe | `wokwi-led` kuning + resistor 330 ohm | `ledStrobe` | lampu strobe |
| Sirene | `wokwi-buzzer` | `buzzSiren` | sirene |
| Speaker | `wokwi-led` biru + resistor 330 ohm | `ledSpeaker` | modul suara |
| Status jaringan | `wokwi-led` hijau + resistor 330 ohm | `ledStatus` | indikator WiFi |
| Serial | `$serialMonitor` | - | Serial Monitor 115200 baud |

Empat tombol yang ditandai **alat uji** tidak mewakili perangkat keras apa
pun. Keduanya ada supaya pengujian dapat dilakukan dengan klik, menggantikan
pengetikan Serial. Di tiang PJU sungguhan hanya ada **satu** tombol: SOS.

Tombol NORMAL/DISTRESS AUDIO khususnya tidak boleh pernah ada di lapangan.
Keduanya memalsukan hasil audio; di perangkat nyata nilai itu harus datang
dari mikrofon.

**Mikrofon tidak disimulasikan.** Dua alasan:

1. Wokwi belum mengimplementasikan I2S untuk ESP32-S3 (ditandai "tidak
   diimplementasikan" di dokumentasi Wokwi), jadi mikrofon I2S tidak dapat
   disimulasikan walaupun kita mau.
2. Firmware sendiri belum memiliki driver mikrofon. `readAudioFeatures()`
   mengembalikan `valid = false`; keyakinan audio berasal dari Serial test
   mode.

Konsekuensinya harus dinyatakan terang-terangan: **model Audio AI tidak
berjalan di ESP32, baik di Wokwi maupun di hardware.** Model audio Python ada
di sisi server/prototype. Nilai `A 0.90` adalah nilai uji yang dimasukkan
manusia, bukan hasil inferensi.

Speaker memakai LED, bukan komponen suara. LED itu hanya menandakan bahwa
firmware mengaktifkan pin speaker - **bukan** bukti bahwa suara terdengar.


## 3. Pin mapping

Sumber kebenaran adalah `include/config.h`. Diagram Wokwi mengikutinya, tidak
sebaliknya. Tidak ada pin yang diubah demi Wokwi.

| Fungsi | Makro di `config.h` | GPIO | Pin Wokwi | Komponen |
|---|---|---|---|---|
| Tombol SOS | `PIN_SOS_BUTTON` | 4 | `esp:4` | `btnSos` ke GND |
| NORMAL AUDIO | `PIN_BTN_AUDIO_NORMAL` | 8 | `esp:8` | `btnNormal` ke GND |
| DISTRESS AUDIO | `PIN_BTN_AUDIO_DISTRESS` | 9 | `esp:9` | `btnDistress` ke GND |
| POLL SERVER | `PIN_BTN_POLL_SERVER` | 10 | `esp:10` | `btnPoll` ke GND |
| RESET | `PIN_BTN_RESET` | 11 | `esp:11` | `btnReset` ke GND |
| Strobe | `PIN_STROBE` | 5 | `esp:5` | `ledStrobe` |
| Sirene | `PIN_SIREN` | 6 | `esp:6` | `buzzSiren` |
| Speaker | `PIN_SPEAKER` | 7 | `esp:7` | `ledSpeaker` |
| Status LED | `PIN_STATUS_LED` | 15 | `esp:15` | `ledStatus` |
| Serial TX | (UART0) | 43 | `esp:TX` | `$serialMonitor:RX` |
| Serial RX | (UART0) | 44 | `esp:RX` | `$serialMonitor:TX` |
| Mic I2S | `PIN_MIC_I2S_*` | 16/17/18 | - | tidak dipakai |

### Hasil pemeriksaan konflik

Seluruh pin diperiksa terhadap definisi board resmi Wokwi (repositori
wokwi-boards) dan terhadap fungsi tetap ESP32-S3. **Tidak ditemukan konflik.
Tidak ada pin yang perlu diganti.**

GPIO 4, 5, 6, 7, 15, dan tombol uji 8, 9, 10, 11 semuanya tersedia sebagai
pin bebas di header DevKitC-1 dan tidak bertabrakan dengan:

- strapping pin (0, 45, 46)
- USB D-/D+ (19, 20)
- SPI flash internal (26-32)
- pin PSRAM octal (33-37)
- UART0 Serial Monitor (43, 44)

Dua catatan yang perlu diketahui:

- **GPIO 38 sudah terpakai di board.** DevKitC-1 memiliki LED RGB WS2812
  bawaan di GPIO 38. Firmware tidak memakainya, jadi tidak ada masalah - tetapi
  jangan memilih GPIO 38 untuk fungsi baru.
- Status pin di `config.h` masih ditandai **PIN TO CONFIRM**. Simulasi ini
  tidak mengubah status itu. Wokwi membuktikan pin tersebut benar secara
  *logika*, bukan bahwa wiring fisiknya sudah final. Lihat `WIRING.md`.
- GPIO 8, 9, 10, 11 ditandai **WOKWI SIMULATION PIN** di `config.h`. Pin ini
  tidak dipakai di perangkat sungguhan. Tanpa tombol terpasang, pull-up
  internal membuat pin terbaca HIGH sehingga tidak pernah terpicu - firmware
  yang sama aman diupload ke board nyata.

### Board attribute

`diagram.json` menyetel `flashSize: "8"`. Ini bukan pilihan sembarangan:
PlatformIO menargetkan varian **N8 (8 MB flash, tanpa PSRAM)** dengan tabel
partisi `default_8MB.csv`, sedangkan default Wokwi adalah 4 MB. Bila dibiarkan
4 MB, tabel partisi tidak cocok dengan flash yang disimulasikan.

`psramSize` sengaja **tidak** disetel, karena varian N8 tidak memiliki PSRAM.


## 4. Cara menjalankan

Ada dua cara. Keduanya memakai `wokwi.toml` dan `diagram.json` yang sama.

### Prasyarat: build firmware lebih dulu

Wokwi **tidak** mengompilasi apa pun. Wokwi memuat hasil build PlatformIO.

```bash
cd esp32
pio run
```

Harus `SUCCESS`. Ini juga yang mencegah adanya dua firmware berbeda:
`wokwi.toml` menunjuk langsung ke
`.pio/build/esp32-s3-devkitc-1/firmware.bin`, berkas yang sama persis dengan
yang diupload ke board sungguhan.

Bila `secrets.h` belum ada, compile akan gagal. Lihat bagian 8.

### Cara A - VS Code (disarankan untuk pengujian interaktif)

1. Pasang ekstensi **Wokwi for VS Code**, lalu jalankan `Wokwi: Request a
   License` sekali.
2. Buka folder `esp32/`.
3. Jalankan `Wokwi: Start Simulator` (F1).

Diagram akan tampil dan Serial Monitor dapat diketik langsung - inilah yang
dibutuhkan untuk mengirim `A 0.90`, `S`, `C`, `R`.

### Cara B - CLI (untuk otomatisasi / CI)

Pasang CLI:

```powershell
iwr https://wokwi.com/ci/install.ps1 -useb | iex
```

Token CI diambil dari https://wokwi.com/dashboard/ci

```powershell
$env:WOKWI_CLI_TOKEN = "<token>"        # PowerShell
```

```bash
export WOKWI_CLI_TOKEN="<token>"        # bash
```

Jalankan:

```bash
cd esp32
wokwi-cli . --timeout 20000
```

Menjalankan skenario otomatis:

```bash
wokwi-cli . --scenario test/scenario-local-reject.yaml    --timeout 30000
wokwi-cli . --scenario test/scenario-local-verified.yaml  --timeout 60000
```

Memeriksa diagram tanpa menjalankan simulasi:

```bash
wokwi-cli lint .
```

Catatan: token VS Code (`~/.wokwi/user.tok`) **bukan** token CI. Memakainya
menghasilkan error `Invalid character in header ["Authorization"]`.


## 5. Menjalankan Flask

```bash
# dari root project
python -m backend.app
```

Server mendengarkan di port 5000. Verifikasi:

```bash
curl http://localhost:5000/api/health
```

Jalankan ini **sebelum** ngrok.


## 6. Menjalankan ngrok

### Mengapa ngrok dibutuhkan

Wokwi berjalan di cloud dan menyambung ke internet lewat **Public Gateway**.
Gateway itu **tidak dapat menjangkau `localhost` komputer Anda.** Karena itu
`http://localhost:5000` dan `http://127.0.0.1:5000` **tidak akan pernah
berfungsi** dari Wokwi.

Ada dua jalan keluar:

| Cara | Bisa akses localhost? | Biaya |
|---|---|---|
| Public Gateway + ngrok | ya, lewat tunnel publik | ngrok gratis cukup |
| Private Gateway + `host.wokwi.internal` | ya, langsung | **Wokwi berbayar** |

Dokumen ini memakai ngrok karena tidak memerlukan langganan Wokwi.

```bash
ngrok http 5000
```

Ambil URL `https://` dari keluarannya, misalnya:

```
https://a1b2-c3d4.ngrok-free.app
```

### Peringatan keamanan

ngrok membuat server Flask Anda **dapat dijangkau siapa pun di internet**
selama tunnel hidup. Endpoint perangkat dilindungi `DEVICE_API_KEY`, tetapi:

- `GET /api/incidents` dan `GET /api/health` **terbuka tanpa kunci**
- tanpa HTTPS sampai ujung akhir, kunci dapat terbaca di jaringan
- URL ngrok gratis dapat ditemukan orang lain

Matikan tunnel setelah selesai menguji (Ctrl+C di jendela ngrok). Jangan
biarkan berjalan tanpa pengawasan.


## 6b. Dua mode server: WOKWI_BUILD

ESP32-S3 di simulator Wokwi **gagal melakukan TLS handshake** ke tunnel HTTPS
publik. Gejalanya di Serial Monitor:

```
start_ssl_client: -80
SSL EOF
connection refused
```

Ini bukan kesalahan konfigurasi Anda: Flask sehat, ngrok sehat, dan URL HTTPS
yang sama dapat dibuka dari browser. Kegagalan ada di tumpukan TLS simulator.

Karena itu firmware memiliki dua mode, dipilih saat compile lewat
`WOKWI_BUILD` di `config.h`:

| | `WOKWI_BUILD 1` | `WOKWI_BUILD 0` (default) |
|---|---|---|
| Protokol | HTTP biasa | HTTPS |
| URL dipakai | `SERVER_BASE_URL_WOKWI` | `SERVER_BASE_URL_REAL` |
| Enkripsi | **tidak ada** | ada |
| Peruntukan | prototype/simulasi | hardware nyata |

Defaultnya **0**. Ini disengaja: bila firmware ini diupload ke perangkat
sungguhan tanpa membaca dokumen ini, yang aktif adalah HTTPS. Mode tidak aman
harus selalu dipilih secara sadar.

Saat `WOKWI_BUILD = 1`, compiler mengeluarkan `#warning` di setiap build, dan
Serial Monitor mencetak mode aktif saat boot. Keduanya sengaja bising.

### Apa yang hilang di mode Wokwi

HTTP biasa mengirim `DEVICE_API_KEY` dan seluruh isi payload **tanpa
enkripsi**. Siapa pun di jalur jaringan dapat membacanya dan memalsukan
command ke perangkat.

Ini hanya dapat diterima untuk prototype dengan kunci uji di jaringan yang
Anda kendalikan. **Jangan** memakai kunci produksi saat mode ini aktif, dan
jangan pernah memakai mode ini di lapangan.

Authentication sendiri **tidak** dilemahkan: header `X-API-Key` tetap dikirim
dan server tetap memverifikasinya. Yang hilang hanya lapisan enkripsinya.

### Cara mengganti mode

1. Ubah `WOKWI_BUILD` di `esp32/include/config.h` menjadi `1`.
2. Isi `SERVER_BASE_URL_WOKWI` di `secrets.h`.
3. `pio run`.

Atau tanpa mengubah file, lewat environment:

```powershell
$env:PLATFORMIO_BUILD_FLAGS='-DWOKWI_BUILD=1'; pio run
```

### PENTING: host.wokwi.internal memerlukan Private Gateway berbayar

`http://host.wokwi.internal:5000` **hanya** berfungsi bila **Wokwi Private IoT
Gateway** berjalan di komputer Anda. Hostname itu tidak ada di Public Gateway.

Private Gateway adalah **fitur berlangganan** (Wokwi Club). Bila tidak aktif,
mode Wokwi akan gagal dengan cara berbeda: bukan error TLS, melainkan host
tidak dapat di-resolve.

Memeriksa apakah gateway berjalan:

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 9011 -InformationLevel Quiet
```

`True` = gateway aktif. `False` = tidak aktif.

Bila tidak berlangganan, pakai **tunnel HTTP biasa** sebagai
`SERVER_BASE_URL_WOKWI`, misalnya localtunnel:

```bash
npx localtunnel --port 5000
```

lalu isi `SERVER_BASE_URL_WOKWI "http://xxxx.loca.lt"` (perhatikan `http`,
bukan `https`).

Catatan tentang ngrok: ngrok gratis mengembalikan **redirect 307 ke HTTPS**
untuk request HTTP, dan `HTTPClient` ESP32 tidak mengikuti redirect secara
bawaan. Jadi ngrok **tidak dapat** dipakai sebagai URL mode Wokwi. Flag
`--scheme http` sudah dihapus di ngrok 3.39.


## 7. Mengganti SERVER_BASE_URL

Diubah di `include/secrets.h` (file ini tidak di-commit). Sejak ada dua mode
(bagian 6b), yang diisi adalah **dua** makro, bukan satu:

```c
#define SERVER_BASE_URL_WOKWI "http://xxxx.loca.lt"                /* HTTP  */
#define SERVER_BASE_URL_REAL  "https://a1b2-c3d4.ngrok-free.app"   /* HTTPS */
```

`SERVER_BASE_URL` sendiri **tidak** diisi manual; nilainya dipilih otomatis
dari salah satu makro di atas berdasarkan `WOKWI_BUILD`.

Aturan:

- **tanpa** garis miring di akhir
- pakai `https://` untuk ngrok
- jangan pernah menulis `localhost` atau `127.0.0.1` di sini - dari Wokwi
  keduanya menunjuk ke simulator itu sendiri, bukan ke komputer Anda

Setelah diubah, **build ulang**. URL tertanam di firmware:

```bash
pio run
```

Catatan TLS: firmware memanggil `setInsecure()` untuk `https://`, jadi
sertifikat **tidak** diverifikasi. Cukup untuk prototype, tidak untuk
produksi.


## 8. Memasukkan DEVICE_API_KEY

`secrets.h` tidak ada di repositori. Buat sekali:

```bash
cd esp32
copy include\secrets.h.example include\secrets.h    # Windows
cp include/secrets.h.example include/secrets.h      # Linux/macOS
```

Isi untuk Wokwi:

```c
#define WIFI_SSID "Wokwi-GUEST"      /* satu-satunya AP Wokwi */
#define WIFI_PASSWORD ""             /* AP terbuka, tanpa password */
#define SERVER_BASE_URL_WOKWI "http://xxxx.loca.lt"
#define SERVER_BASE_URL_REAL "https://xxxx.ngrok-free.app"
#define DEVICE_ID "ASEP-WOKWI-01"
#define DEVICE_API_KEY "<sama dengan DEVICE_API_KEY di .env server>"
```

Saat `WOKWI_BUILD = 1`, kunci ini dikirim **tanpa enkripsi**. Pakai kunci uji,
bukan kunci produksi.

`DEVICE_API_KEY` harus **sama persis** dengan `.env` server, jika tidak semua
request ditolak HTTP 401.

### Yang tidak boleh masuk firmware

**Hanya `DEVICE_API_KEY`.** Jangan pernah memasukkan `DEVICE_CONFIG_API_KEY`
(kunci operator), `SECRET_KEY` Flask, atau `TOMTOM_API_KEY`.

Alasannya bukan formalitas: flash perangkat yang dipasang di ruang publik dapat
dibaca ulang. Apa pun di firmware harus dianggap dapat diketahui orang lain.
Kunci operator dapat mengubah konfigurasi yang memengaruhi hasil verifikasi,
jadi kunci itu tidak layak berada di perangkat.

Kunci juga tidak boleh muncul di `diagram.json`, screenshot, atau dokumen yang
di-commit. `secrets.h` dan `.pio/` sudah ada di `.gitignore`.


## 9. Tombol Simulasi dan Serial command

### Tombol Simulasi

Pengujian utama **tidak lagi memerlukan input Serial**. Cukup klik tombol di
diagram Wokwi:

| Tombol | Fungsi |
|---|---|
| NORMAL AUDIO | simulasi audio non-distress (0.20, kelas Normal) |
| DISTRESS AUDIO | simulasi audio distress (0.90, kelas SCREAM) |
| SOS | trigger emergency (lewat verifikasi lokal) |
| POLL SERVER | mengambil command dari server |
| RESET | reset emergency ke READY |

Tiga hal yang perlu dipahami tentang tombol ini:

**1. Tombol audio tidak menjalankan emergency.** NORMAL/DISTRESS AUDIO hanya
menyetel keadaan audio, sama seperti `A` dan `K` di Serial. Emergency tetap
harus dimulai dari tombol SOS. Ini disengaja: kalau tombol audio langsung
memicu emergency, aturan "SOS tidak pernah melewati verifikasi audio" tidak
dapat diuji lagi.

**2. Keadaan audio bertahan sampai reset.** Klik DISTRESS AUDIO lalu SOS, dan
SOS memakai 0.90. Keadaan itu hanya dikosongkan oleh `resetEmergency()`
(tombol RESET atau `CLEAR_EMERGENCY` dari server), bukan oleh tombol SOS.

**3. Ketiga jalur masuk memakai fungsi yang sama.** Tombol Wokwi, tombol
fisik, dan Serial `S` semuanya memanggil `triggerSosPath()`. Tidak ada logika
verifikasi yang diduplikasi - kalau tombol dan Serial bisa berbeda perilaku,
pengujian lewat tombol tidak membuktikan apa pun tentang tombol nyata.

Tombol audio **bukan** AI. Keduanya hanya menyetel angka. Tidak ada mikrofon
dan tidak ada inferensi di perangkat.

### Serial command

Serial Monitor: **115200 baud**. Tetap dipertahankan untuk debugging.
Perintah firmware yang sudah ada, tidak ada yang dihapus:

| Perintah | Arti |
|---|---|
| `A <nilai>` | set audio confidence 0.0-1.0, mis. `A 0.90` |
| `K <kelas>` | set audio class, mis. `K SCREAM` |
| `S` | simulasi tombol SOS |
| `T` | trigger test (audio 0.90 + SCREAM + SOS) |
| `R` | reset ke READY |
| `C` | poll command sekarang |
| `H` | kirim heartbeat sekarang |
| `G` | register ulang |
| `?` | tampilkan status |

Catatan: firmware **tidak** memiliki perintah `N` (trigger tanpa SOS) yang ada
di simulator Python. Untuk kasus tanpa SOS, pakai `A`/`K` dengan keyakinan
minimal 0.90 lalu tunggu jalur audio-only.

Contoh - ditolak lokal:

```
A 0.20
K Normal
S        -> LOCAL_REJECTED, STROBE TETAP OFF
```

Contoh - lolos lokal:

```
A 0.90
K SCREAM
S        -> LOCAL_VERIFIED, STROBE ON, event dikirim
C        -> ambil command; bila server CONFIRMED: SIREN ON
R        -> READY
```

Tombol `btnSos` di diagram menjalankan jalur yang sama dengan `S`, termasuk
verifikasi audio. Menekan tombol saja **tidak** cukup: `A`/`K` harus diisi
lebih dulu, jika tidak hasilnya `LOCAL_REJECTED`. Itu memang perilaku yang
benar, bukan kekurangan.


## 10. Test cases

Skenario 1, 2, 5, dan 7 tidak memerlukan server. Skenario 3, 4, dan 6
memerlukan Flask + ngrok.

### 1 - LOCAL REJECT (tanpa server)

```
A 0.20
K Normal
S
```

Atau cukup klik: **NORMAL AUDIO** lalu **SOS**.

Diharapkan:

```
[AUDIO TEST] NORMAL
  confidence = 0.20
  class      = Normal
[SOS] BUTTON PRESSED (tombol)
[LOCAL] REJECTED (audio 0.20, kelas Normal). STROBE TETAP OFF.
[LOCAL] SOS saja tidak cukup: verifikasi audio wajib dilewati juga.
```

LED STROBE tetap gelap, buzzer diam, tidak ada event terkirim.
Otomatis: `test/scenario-local-reject.yaml`

### 2 - LOCAL VERIFIED (tanpa server)

```
A 0.90
K SCREAM
S
```

Atau cukup klik: **DISTRESS AUDIO** lalu **SOS**.

Diharapkan:

```
[AUDIO TEST] DISTRESS
  confidence = 0.90
  class      = SCREAM
[SOS] BUTTON PRESSED (tombol)
[LOCAL] VERIFIED (audio 0.90, kelas SCREAM)
[EVENT] Kejadian baru, event_id = <bootId>-1
[STROBE] ON (fail-safe lokal, tidak menunggu server)
```

LED STROBE berkedip. **Buzzer harus tetap diam** - verifikasi lokal tidak
pernah cukup untuk menyalakan sirene.
Otomatis: `test/scenario-local-verified.yaml`

### 3 - SERVER CONFIRMED (perlu Flask + ngrok)

Setelah skenario 2, klik **POLL SERVER** (atau tekan `C`). Bila verifikasi
tahap 2 menghasilkan `CONFIRMED`:

```
[COMMAND] EMERGENCY_CONFIRMED (id N)
[SIREN] ON (server CONFIRMED)
[SPEAKER] Petugas sedang menuju lokasi.
```

Buzzer berbunyi berpola (non-blocking), LED SPEAKER menyala. Dashboard
menampilkan incident `CONFIRMED`.

### 4 - FALSE ALARM (perlu Flask + ngrok)

Bukti lemah (mis. `A 0.62`, `K SCREAM`, tanpa konteks pendukung) menghasilkan
`FALSE_ALARM`. Server tidak membuat command `EMERGENCY_CONFIRMED`, sehingga
sirene dan speaker **tetap mati**. Strobe tetap menyala sampai
`CLEAR_EMERGENCY` datang atau `R` ditekan - server tidak boleh diam-diam
mematikan fail-safe lokal.

### 5 - SERVER OFFLINE (tanpa server)

Jalankan skenario 2, lalu matikan Flask (atau biarkan `SERVER_BASE_URL` tidak
terjangkau).

Diharapkan: HTTP gagal, firmware melaporkan kegagalan, **STROBE TETAP ON**.
Strobe tidak boleh mati hanya karena server tidak tersedia.
Otomatis: bagian tengah `test/scenario-local-verified.yaml`

### 6 - RETRY / IDEMPOTENCY (perlu Flask + ngrok)

Satu kejadian memakai satu `event_id`, dipakai ulang pada setiap retry.

| Pengiriman | event_id | Hasil server |
|---|---|---|
| pertama | `<bootId>-1` | incident baru, `duplicate: false` |
| retry | `<bootId>-1` | incident **sama**, `duplicate: true`, tanpa command baru |
| kejadian baru | `<bootId>-2` | incident baru |

Logika ini tidak diubah untuk Wokwi. Sudah diverifikasi terpisah lewat
simulator Python: tiga POST menghasilkan dua incident di database.

### 7 - RESET (tanpa server)

Klik **RESET** (atau tekan `R`).

Diharapkan `[RESET] Semua output OFF. Perangkat READY.` - strobe, sirene, dan
speaker mati.

Penting: reset **tidak** mengembalikan `event_counter` ke nol. Kejadian
berikutnya memakai `-2`, bukan `-1`. Bila kembali ke `-1`, server akan
menganggapnya retry dan **emergency nyata akan hilang** - kegagalan yang jauh
lebih berbahaya daripada incident ganda.
Otomatis: bagian akhir `test/scenario-local-verified.yaml`

### Dashboard

Dashboard yang sudah ada dipakai, tidak ada yang baru dibuat. Saat Wokwi
mengirim emergency, dashboard menampilkan device ONLINE, incident, bukti audio,
hasil verifikasi lokal, hotspot/weather/traffic/lighting, keputusan server, dan
command.

`hotspot_risk` akan bernilai `null` (`MISSING_FEATURES`) sampai
`population_density` device diisi. Itu perilaku yang benar, bukan bug - lihat
bagian Population_Density di README utama.


## 11. Troubleshooting

| Gejala | Penyebab yang paling sering |
|---|---|
| `secrets.h tidak ditemukan` saat compile | Belum menyalin dari `secrets.h.example` |
| `SERVER_BASE_URL tidak terdefinisi` | `secrets.h` masih format lama. Tambahkan `SERVER_BASE_URL_WOKWI` dan `SERVER_BASE_URL_REAL` (bagian 7) |
| Wokwi: firmware tidak ditemukan | `pio run` belum dijalankan |
| `Missing WOKWI_CLI_TOKEN` | Token CI belum diset; ambil di wokwi.com/dashboard/ci |
| `start_ssl_client: -80` / `SSL EOF` | TLS simulator gagal ke tunnel HTTPS. Pakai `WOKWI_BUILD = 1` (bagian 6b) |
| Mode Wokwi: host tidak dapat di-resolve | `host.wokwi.internal` perlu Private Gateway berbayar. Pakai tunnel HTTP biasa |
| Mode Wokwi: HTTP 307 / redirect | URL mode Wokwi memakai ngrok. ngrok memaksa HTTPS; pakai tunnel HTTP lain |
| `Invalid character in header ["Authorization"]` | Memakai token VS Code (`~/.wokwi/user.tok`), bukan token CI. Keduanya berbeda |
| WiFi tidak tersambung | SSID bukan `Wokwi-GUEST`, atau password tidak dikosongkan |
| HTTP gagal terus padahal WiFi normal | `SERVER_BASE_URL` memakai localhost/127.0.0.1. Public Gateway tidak dapat menjangkaunya - pakai ngrok |
| HTTP 401 | `DEVICE_API_KEY` berbeda dengan `.env` server |
| HTTP 404 saat heartbeat | Device belum terdaftar; firmware mendaftar ulang otomatis |
| Sirene berbunyi saat boot | `ACTUATOR_ACTIVE_HIGH` tidak cocok dengan asumsi modul |
| Serial Monitor kosong | Baud bukan 115200, atau `$serialMonitor` tidak tersambung ke TX/RX |
| Serial tidak menerima input | Pakai VS Code atau `wokwi-cli --interactive` |
| Boot berulang / partisi salah | `flashSize` di `diagram.json` tidak 8 MB |
| Simulasi lambat | Normal; Wokwi membatasi CPU sekitar 8 MHz agar simulasi lebih cepat |


## 12. Batasan simulasi

**Wokwi simulation TIDAK SAMA DENGAN real hardware validation.**

Simulasi yang berhasil membuktikan firmware benar secara *logika*. Simulasi
tidak membuktikan apa pun tentang listrik, mekanik, atau akustik.

### Belum diuji sama sekali

- **Mikrofon nyata.** Hardware belum dipilih. `readAudioFeatures()` masih
  placeholder (`valid = false`). Wokwi juga belum mendukung I2S di ESP32-S3.
- **Audio AI di edge.** Tidak ada model AI yang berjalan di ESP32, baik di
  Wokwi maupun di hardware. Keyakinan audio diisi manusia lewat Serial.
- **Speaker fisik.** Yang ada hanya LED indikator. LED menyala bukan berarti
  ada suara.
- **Strobe fisik.** LED dengan resistor 330 ohm bukan lampu strobe. Arus,
  tegangan, dan driver belum diuji.
- **Sirene fisik.** Buzzer Wokwi bukan sirene. Kebutuhan daya dan tingkat
  kebisingan belum diuji.
- **Power supply.** Tidak ada rancangan daya final. Lonjakan arus saat sirene
  menyala adalah risiko nyata yang tidak akan pernah muncul di simulasi.
- **Pin final.** `config.h` masih `PIN TO CONFIRM`.
- **Relay / driver aktuator.** `ACTUATOR_ACTIVE_HIGH` belum dicocokkan dengan
  modul nyata. Nilai yang salah membuat sirene menyala saat boot.
- **Enclosure, cuaca, vandalisme, dan jaringan seluler nyata.**

### Yang benar-benar dibuktikan

- logika firmware dan state machine
- logika GPIO (pin mana menyala, kapan)
- alur jaringan: boot -> WiFi -> register -> heartbeat -> command polling
- integrasi API dengan backend yang sudah ada
- alur command termasuk ack
- perilaku fail-safe **di tingkat software** (strobe tetap ON saat server mati)
- idempotency `event_id` end-to-end

### Cara menulis hasilnya

Benar:

- "Hardware simulation berhasil."
- "LED dipakai sebagai simulasi strobe."
- "Keyakinan audio diisi lewat Serial test mode."

Salah:

- "Hardware berhasil."
- "Strobe fisik berhasil."
- "Audio AI sudah berjalan di ESP32."

Perbedaannya bukan soal kehati-hatian berbahasa. Sistem ini dimaksudkan untuk
merespons keadaan darurat nyata; salah menggambarkan apa yang sudah diuji dapat
membuat orang menaruh kepercayaan pada perangkat yang belum layak dipercaya.