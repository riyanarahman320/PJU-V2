# ASEP-JAGA

Sistem deteksi darurat pada Penerangan Jalan Umum (PJU) untuk wilayah
Kiaracondong, Bandung. Perangkat ESP32 mendeteksi teriakan dan tombol SOS,
server memverifikasi ulang dengan konteks lingkungan sebelum menyalakan sirene.


## Cara verifikasi bekerja

Verifikasi berlangsung dua tahap.

**Tahap 1 (di perangkat).** ESP32 memutuskan sendiri agar tetap berfungsi saat
jaringan mati. Tombol SOS **tidak** dapat melewati verifikasi audio: SOS tanpa
bukti suara menghasilkan `LOCAL_REJECTED`. Ini mencegah tombol yang tertekan
tidak sengaja membangunkan sirene. Strobe menyala sejak tahap ini, tanpa
menunggu server.

**Tahap 2 (di server).** Server menghitung skor berbobot dari beberapa bukti:
SOS, kelas audio, risiko hotspot, riwayat kejadian, kondisi lingkungan, dan
status darurat perangkat. CONFIRMED memerlukan skor melewati
`SERVER_CONFIRM_THRESHOLD`.

Dua sifat yang dijaga oleh test:

- **Tidak ada bukti tunggal yang cukup.** Setiap bobot lebih kecil daripada
  ambang, jadi SOS saja, audio 100% saja, atau hotspot High saja tetap
  menghasilkan `FALSE_ALARM`.
- **Server hanya memperketat.** `LOCAL_REJECTED` tidak dapat dinaikkan menjadi
  CONFIRMED oleh server.

Verifikasi tahap 2 memakai **aturan berbobot tetap yang ditulis manual, bukan
model AI.** `/api/health` melaporkannya sebagai `RULE_BASED_SECOND_LEVEL`
dengan `is_ai_model: false`. Model Random Forest dipakai untuk memperkirakan
risiko hotspot, bukan untuk mengambil keputusan darurat.


## Idempotency emergency (`event_id`)

Perangkat berada di jaringan seluler yang tidak dapat diandalkan. Bila
`POST /api/emergency/evaluate` sampai ke server dan incident berhasil dibuat,
tetapi responsnya hilang karena timeout, perangkat tidak dapat membedakan
keadaan itu dari "request tidak pernah sampai". Perangkat harus mencoba lagi —
diam saja berarti kejadian nyata tidak pernah dilaporkan.

`event_id` adalah idempotency key yang menyelesaikan hal ini. Perangkat membuat
**satu** nilai untuk **satu** kejadian SOS, lalu memakai nilai yang sama pada
setiap percobaan pengiriman.

| Keadaan | Hasil di server |
|---|---|
| `event_id` baru | Incident baru dibuat, `duplicate: false` |
| `event_id` sudah pernah diterima dari device itu | Incident yang ada dikembalikan, `duplicate: true` |
| `event_id` tidak dikirim | Perilaku lama: setiap request membuat incident baru |
| `event_id` kosong / hanya spasi | Sama dengan tidak dikirim |

Pada jalur retry, server **tidak** menjalankan verifikasi ulang, **tidak**
memanggil model atau API konteks, dan **tidak** membuat command tambahan.
Command yang sudah ada tetap disertakan dalam respons, karena retry mungkin
satu-satunya kesempatan perangkat mengetahui command tersebut.

Retry yang tidak menjalankan verifikasi ulang juga menjaga ketepatan penilaian:
verifikasi tahap 2 memakai riwayat kejadian device, sehingga mencatat kejadian
ganda akan menggeser `history_score` dan mengubah penilaian kejadian berikutnya.

Keunikan dijaga per pasangan `(device_id, event_id)`, bukan `event_id` saja.
Nilai itu dibuat dari penghitung lokal perangkat, jadi dua perangkat berbeda
wajar menghasilkan nilai yang sama tanpa berarti kejadian yang sama.
Menyamakannya akan **menghilangkan** emergency nyata di perangkat kedua.

Firmware menyusun nilainya sebagai `<bootId>-<nomor urut>`, misalnya
`a3f19c02-1`. `bootId` acak dibuat sekali per boot karena `millis()` kembali ke
0 setiap reboot: tanpa pembeda itu, kejadian pertama setelah reboot dapat
memakai nilai yang sama dengan kejadian lama dan justru diabaikan sebagai
duplicate.

Field ini opsional supaya firmware lama tetap bekerja. Panjang maksimum 64
karakter; nilai bukan string atau lebih panjang ditolak dengan HTTP 400.

Database yang sudah berisi incident perlu dimigrasi sekali:

```bash
.venv\\Scripts\\python.exe scripts\\migrate_add_event_id.py --dry-run
.venv\\Scripts\\python.exe scripts\\migrate_add_event_id.py
```

Database baru tidak memerlukannya: `db.create_all()` sudah membuat kolom dan
indeksnya. Incident lama tetap tersimpan dengan `event_id = NULL`, yang berarti
"dibuat tanpa idempotency key" — bukan kesalahan.


## Menjalankan

```bash
python -m venv .venv
.venv\\Scripts\\activate          # Windows
pip install -r requirements.txt

copy .env.example .env            # lalu isi nilai CHANGE_ME
python -m backend.app
```

Model `random_forest_pipeline.pkl` (~79 MB) tidak di-commit ke Git. Letakkan di
`backend/models_store/`. Tanpa file itu, server tetap berjalan namun hotspot
berstatus `MODEL_NOT_LOADED`.

Memeriksa seluruh lapisan tanpa HTTP:

```bash
.venv\\Scripts\\python.exe scripts\\smoke_check.py
.venv\\Scripts\\python.exe -m pytest -q
```


## Autentikasi

Ada dua kunci terpisah, keduanya dibaca dari `.env` dan tidak memiliki nilai
default di dalam kode.

| Kunci | Header | Dipakai oleh |
|---|---|---|
| `DEVICE_API_KEY` | `X-API-Key` | Perangkat: register, heartbeat, evaluate, commands |
| `DEVICE_CONFIG_API_KEY` | `X-Operator-Key` | Operator: konfigurasi device + aksi incident |

Endpoint yang memerlukan `X-Operator-Key`:

```
PUT  /api/device/<device_id>/config
POST /api/incidents/<incident_id>/confirm
POST /api/incidents/<incident_id>/false-alarm
POST /api/incidents/<incident_id>/close
POST /api/incidents/<incident_id>/dispatch
```

Kode respons autentikasi, sama untuk kelima endpoint:

| Kode | Arti |
|---|---|
| 401 | Header `X-Operator-Key` tidak dikirim |
| 403 | Kunci operator salah |
| 500 | `DEVICE_CONFIG_API_KEY` belum diisi di server |

Keduanya sengaja dipisah. Kunci perangkat tertanam di firmware dan dipakai
seluruh unit, jadi kunci itu tidak layak memberi wewenang mengubah konfigurasi
yang memengaruhi hasil verifikasi. Perangkat yang memakai `X-API-Key` pada
endpoint konfigurasi akan ditolak dengan 401.

Bila `DEVICE_CONFIG_API_KEY` belum diisi, endpoint konfigurasi menolak **semua**
request dengan HTTP 500. Kunci kosong berarti endpoint tertutup, bukan terbuka:
lupa mengisi `.env` tidak boleh diam-diam menghapus autentikasi.

Membuat nilai acak:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Batasan yang perlu diketahui: ini satu kunci bersama untuk semua operator,
tanpa identitas per pengguna dan tanpa masa berlaku, serta terbaca di jaringan
bila tidak memakai HTTPS. Cukup untuk prototype di jaringan lokal; belum cukup
untuk penggunaan sungguhan.


## Aksi operator

Empat endpoint di bawah mengubah status darurat dan sebagian mengirim command
ke perangkat di lapangan. Semuanya memerlukan header `X-Operator-Key`.

| Endpoint | Efek |
|---|---|
| `POST /api/incidents/<id>/confirm` | Status `CONFIRMED`, membuat command `EMERGENCY_CONFIRMED` |
| `POST /api/incidents/<id>/false-alarm` | Status `FALSE_ALARM`, membuat command `CLEAR_EMERGENCY` |
| `POST /api/incidents/<id>/close` | Status `CLOSED`, membuat command `CLEAR_EMERGENCY` |
| `POST /api/incidents/<id>/dispatch` | Status `DISPATCHED`, tidak membuat command |

Request yang ditolak tidak meninggalkan efek apa pun: status incident tidak
berubah dan tidak ada command yang terbuat. Guard berjalan sebelum logika aksi,
jadi request tanpa kunci yang sah tidak pernah mencapai perangkat.

Contoh confirm:

```bash
curl -X POST http://localhost:5000/api/incidents/INC-20260813-0001/confirm \\
  -H "Content-Type: application/json" \\
  -H "X-Operator-Key: $DEVICE_CONFIG_API_KEY" \\
  -d '{"note": "Terdengar teriakan, petugas menuju lokasi."}'
```

Contoh false-alarm:

```bash
curl -X POST http://localhost:5000/api/incidents/INC-20260813-0001/false-alarm \\
  -H "Content-Type: application/json" \\
  -H "X-Operator-Key: $DEVICE_CONFIG_API_KEY" \\
  -d '{"note": "Ternyata suara petasan."}'
```

Contoh dispatch:

```bash
curl -X POST http://localhost:5000/api/incidents/INC-20260813-0001/dispatch \\
  -H "Content-Type: application/json" \\
  -H "X-Operator-Key: $DEVICE_CONFIG_API_KEY" \\
  -d '{"note": "Unit patroli 2 dikirim."}'
```

Contoh close:

```bash
curl -X POST http://localhost:5000/api/incidents/INC-20260813-0001/close \\
  -H "Content-Type: application/json" \\
  -H "X-Operator-Key: $DEVICE_CONFIG_API_KEY" \\
  -d '{"note": "Situasi tertangani, sirene dimatikan."}'
```

PowerShell:

```powershell
$headers = @{ "X-Operator-Key" = $env:DEVICE_CONFIG_API_KEY }
Invoke-RestMethod -Method Post -Headers $headers `
  -Uri "http://localhost:5000/api/incidents/INC-20260813-0001/dispatch" `
  -ContentType "application/json" -Body '{"note":"Unit patroli 2 dikirim."}'
```

`GET /api/incidents` dan `GET /api/incidents/<id>` tetap terbuka karena
dashboard memerlukannya untuk membaca data.

### Operator key di dashboard

Kunci operator **tidak** ditulis di dalam file JavaScript. File di
`frontend/static/js/` dilayani sebagai static asset dan dapat dibaca siapa pun
yang membuka dashboard, jadi menaruh secret di sana sama dengan
mempublikasikannya.

Karena sistem belum memiliki login operator, dashboard meminta kunci saat
operator pertama kali menekan tombol aksi, lalu menyimpannya di
`sessionStorage` — hilang ketika tab ditutup. Bilah atas menampilkan apakah
kunci sudah dimasukkan (hanya ADA/TIDAK, bukan nilainya) beserta tombol
"Lupakan key". Bila server menolak dengan 401 atau 403, kunci yang tersimpan
dihapus supaya operator dapat memasukkan ulang.

Ini solusi sementara untuk prototype, bukan pengganti sesi login: kunci masih
dapat dibaca lewat devtools oleh orang yang memakai komputer operator, dan
tanpa HTTPS masih terbaca di jaringan.


## Konfigurasi konteks device

Model Random Forest membutuhkan 18 fitur. Sebagian berasal dari API (cuaca,
lalu lintas), sebagian dari waktu, dan sebagian harus diisi operator per titik
PJU. Tanpa konfigurasi ini, hotspot tidak dapat diprediksi.

Melihat pilihan nilai yang sah (terbuka, tanpa kunci):

```bash
curl http://localhost:5000/api/device/config/options
```

Melihat konfigurasi satu device (terbuka, tanpa kunci):

```bash
curl http://localhost:5000/api/device/PJU-001/config
```

Mengubah konfigurasi (memerlukan kunci operator):

```bash
curl -X PUT http://localhost:5000/api/device/PJU-001/config \\
  -H "Content-Type: application/json" \\
  -H "X-Operator-Key: $DEVICE_CONFIG_API_KEY" \\
  -d '{
        "village": "Babakan Sari",
        "road_type": "Main Road",
        "area_type": "Public Facility",
        "nearby_cctv": "Yes",
        "nearby_police_post": "No",
        "public_event": "No",
        "holiday": "No"
      }'
```

PowerShell:

```powershell
$headers = @{ "X-Operator-Key" = $env:DEVICE_CONFIG_API_KEY }
$body = '{"village":"Babakan Sari","road_type":"Main Road"}'
Invoke-RestMethod -Method Put -Headers $headers `
  -Uri "http://localhost:5000/api/device/PJU-001/config" `
  -ContentType "application/json" -Body $body
```

Kode respons:

| Kode | Arti |
|---|---|
| 200 | Konfigurasi diperbarui |
| 400 | Nilai di luar kosakata model, atau `population_density` negatif |
| 401 | Header `X-Operator-Key` tidak dikirim |
| 403 | Kunci operator salah |
| 404 | Device belum terdaftar |
| 500 | `DEVICE_CONFIG_API_KEY` belum diisi di server |

Nilai di luar kosakata model ditolak dengan 400, bukan diterima. Ini penting:
pipeline memakai `OneHotEncoder(handle_unknown='ignore')`, sehingga nilai asing
seperti `"village": "Menteng"` akan diubah menjadi vektor nol dan prediksi tetap
keluar terlihat sah walaupun masukannya tidak dikenal model. Model hanya
mengenal 6 kelurahan di Kiaracondong.


## Firmware ESP32-S3

Kode ada di `esp32/`. Firmware memakai API server yang sudah ada; tidak ada
endpoint baru yang dibuat untuknya.

```
esp32/
  platformio.ini            konfigurasi board & dependency
  include/config.h          pin, ambang batas, interval (tanpa secret)
  include/secrets.h.example template WiFi + DEVICE_API_KEY
  include/secrets.h         dibuat manual, TIDAK di-commit
  src/main.cpp              firmware
  WIRING.md                 wiring (semua pin PIN TO CONFIRM)
```

### Persiapan

```bash
pip install platformio          # bila belum ada
cd esp32
copy include\\secrets.h.example include\\secrets.h    # lalu isi nilainya
```

Isi `secrets.h`: `WIFI_SSID`, `WIFI_PASSWORD`, `SERVER_BASE_URL_REAL` dan
`SERVER_BASE_URL_WOKWI` (keduanya tanpa garis miring di akhir; lihat
`esp32/WOKWI.md` bagian 6b soal dua mode), `DEVICE_ID`, dan
`DEVICE_API_KEY` yang sama dengan `.env`
server. Firmware **hanya** memakai `DEVICE_API_KEY`; `DEVICE_CONFIG_API_KEY`
tidak boleh masuk ke firmware karena flash perangkat di ruang publik dapat
dibaca ulang.

### Build dan upload

```bash
cd esp32
pio run                    # compile
pio run --target upload     # upload ke board
pio device monitor          # Serial Monitor, 115200 baud
```

Board di `platformio.ini` adalah `esp32-s3-devkitc-1` (ESP32-S3 generik).
**Sesuaikan dengan board Anda sebelum upload**, terutama bila modul memakai
octal PSRAM — lihat `esp32/WIRING.md`.

### Serial test mode

Mikrofon belum terpasang, jadi keyakinan audio diisi lewat Serial. Nilai ini
**bukan** hasil inferensi di perangkat; tidak ada model AI yang berjalan di
ESP32.

| Perintah | Arti |
|---|---|
| `A 0.90` | set audio confidence (0.0–1.0) |
| `K SCREAM` | set audio class |
| `S` | simulasi tombol SOS |
| `T` | trigger test (audio 0.90 + SCREAM + SOS) |
| `R` | reset ke READY |
| `C` | poll command sekarang |
| `H` | kirim heartbeat sekarang |
| `G` | register ulang |
| `?` | tampilkan status |

Menguji alur tanpa hardware:

```
A 0.90      -> audio confidence 0.90
K SCREAM    -> kelas audio relevan
S           -> LOCAL_VERIFIED, STROBE ON, event dikirim
C           -> ambil command; bila server CONFIRMED: SIREN ON
R           -> READY
```

Menguji bahwa SOS tidak dapat melewati verifikasi audio:

```
A 0.10
K Normal
S           -> LOCAL_REJECTED, STROBE TETAP OFF
```

### Simulator tanpa hardware

`simulation/simulator.py` memakai endpoint, payload, dan header yang sama
dengan firmware, sehingga alur API dapat diuji tanpa board:

```bash
python simulation/simulator.py --auto              # alur lengkap sekali jalan
python simulation/simulator.py                     # mode interaktif
python simulation/simulator.py --device ASEP-012
```

Simulator membaca `DEVICE_API_KEY` dari environment atau `.env`; tidak ada
kunci default di kodenya.

### Troubleshooting

| Gejala | Penyebab yang paling sering |
|---|---|
| `secrets.h tidak ditemukan` saat compile | Belum menyalin dari `secrets.h.example` |
| HTTP 401 pada register/heartbeat | `DEVICE_API_KEY` di `secrets.h` berbeda dengan `.env` server |
| HTTP 404 pada heartbeat | Device belum terdaftar; firmware akan mendaftar ulang otomatis |
| Sirene berbunyi saat boot | `ACTUATOR_ACTIVE_HIGH` di `config.h` tidak cocok dengan modul relay |
| WiFi gagal, board tetap jalan | Perilaku yang benar: perangkat masuk LOCAL MODE, strobe tetap berfungsi |
| Board reboot saat sirene menyala | Daya kurang; lihat bagian Daya di `WIRING.md` |
| Serial Monitor kosong | Baud rate bukan 115200, atau memakai GPIO 43/44 untuk hal lain |


## Population_Density belum tersedia

Data kepadatan penduduk per titik PJU belum dimiliki, jadi seluruh device
produksi memiliki `population_density = null`.

Akibatnya, dan ini disengaja:

- Prediksi hotspot berstatus `MISSING_FEATURES`; model **tidak** dipanggil.
- `hotspot_risk` bernilai `null`, bukan `0.0`.
- Verifikasi tahap 2 mengeluarkan bobot hotspot lalu menormalisasi bobot yang
  tersisa, sehingga kejadian nyata di titik yang belum dikonfigurasi tetap
  dapat CONFIRMED bila bukti lain kuat.
- Halaman Devices menampilkan penanda bahwa konfigurasi populasi belum ada.

Nilai ini **tidak** diisi angka perkiraan. Dua alasannya: `null` berarti "tidak
diketahui" sedangkan `0.0` berarti "tidak ada penduduk" — menyamakan keduanya
akan menurunkan skor dan berpotensi menolak kejadian nyata; dan pipeline tidak
memakai scaler, jadi satuan yang berbeda dari dataset training akan menggeser
prediksi tanpa terdeteksi. Bila nanti datanya tersedia, isi lewat endpoint
konfigurasi dengan satuan yang sama seperti dataset training.
