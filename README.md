# ASEP-JAGA

Sistem deteksi darurat pada Penerangan Jalan Umum (PJU) untuk wilayah
Kiaracondong, Bandung. Perangkat ESP32 mendeteksi teriakan dan tombol SOS,
server memverifikasi ulang dengan konteks lingkungan sebelum menyalakan sirene.

> **Prototype.** Sistem ini berjalan penuh dari perangkat sampai dashboard,
> tetapi belum siap dipasang di jalan umum. Batasan yang diketahui ditulis
> terbuka di dokumen ini, tidak disembunyikan.

**Ringkasan teknis**

| | |
|---|---|
| Perangkat | ESP32-S3 (PlatformIO / Arduino framework) |
| Server | Python 3.13 + Flask + SQLAlchemy + SQLite |
| Model ML | scikit-learn 1.7.2 — `RandomForestClassifier`, 300 pohon, 18 fitur |
| Keputusan darurat | Aturan berbobot manual, **bukan** model ML |
| API eksternal | Open-Meteo (cuaca), TomTom (lalu lintas) |
| Test | 224 test, seluruhnya lulus |


## Daftar isi

- [Cara sistem ini bekerja](#cara-sistem-ini-bekerja)
- [AI dan model apa saja yang dipakai](#ai-dan-model-apa-saja-yang-dipakai)
- [Random Forest: 18 fitur dan asalnya](#random-forest-18-fitur-dan-asalnya)
- [Cara verifikasi bekerja](#cara-verifikasi-bekerja)
- [Sensor tamper](#sensor-tamper)
- [Struktur proyek](#struktur-proyek)
- [Daftar endpoint](#daftar-endpoint)
- [Idempotency emergency (`event_id`)](#idempotency-emergency-event_id)
- [Menjalankan](#menjalankan)
- [Autentikasi](#autentikasi)
- [Aksi operator](#aksi-operator)
- [Konfigurasi konteks device](#konfigurasi-konteks-device)
- [Firmware ESP32-S3](#firmware-esp32-s3)
- [Batasan yang diketahui](#batasan-yang-diketahui)
- [Population_Density](#population_density)


## Cara sistem ini bekerja

Ada satu gagasan pokok: **perangkat tidak pernah dipercaya sepenuhnya, dan
server tidak pernah menjadi satu-satunya penentu.**

Perangkat harus tetap berguna saat jaringan mati, tetapi tidak boleh
membangunkan sirene hanya karena satu tombol tertekan. Server punya konteks
yang lebih luas, tetapi berada jauh dari lokasi dan bisa tidak terjangkau.
Pembagian tugasnya mengikuti kenyataan itu.

```
        WARGA                     ESP32-S3                      SERVER FLASK
          |                           |                              |
   tekan SOS / teriak                 |                              |
          |------------------------->  |                              |
          |                    TAHAP 1: verifikasi lokal              |
          |                    - SOS + bukti audio?                   |
          |                    - ambang 0.60                          |
          |                           |                              |
          |                    LOCAL_REJECTED --> berhenti, diam      |
          |                           |                              |
          |                    LOCAL_VERIFIED                         |
          |                           |                              |
          |                    STROBE MENYALA                         |
          |                    (tanpa menunggu server)                |
          |                           |                              |
          |                           |  POST /api/emergency/evaluate |
          |                           |----------------------------->|
          |                           |                              |
          |                           |         TAHAP 2: verifikasi server
          |                           |         - Random Forest -> hotspot
          |                           |         - Open-Meteo    -> cuaca
          |                           |         - TomTom        -> lalu lintas
          |                           |         - database      -> riwayat
          |                           |         - skor berbobot vs ambang
          |                           |                              |
          |                           |  <---- CONFIRMED / FALSE_ALARM
          |                           |                              |
          |                           |  GET .../command             |
          |                           |----------------------------->|
          |                           |  <---- EMERGENCY_CONFIRMED   |
          |                           |                              |
          |                    SIRENE + SUARA MENYALA                 |
          |                           |                              |
          |                           |                       OPERATOR (dashboard)
          |                           |                       confirm / false-alarm
          |                           |                       dispatch / close
```

Tiga hal yang membuat alur ini berbeda dari "deteksi lalu bunyikan":

**Strobe menyala di tahap 1, sirene menunggu tahap 2.** Strobe hanya menarik
perhatian dan tidak merugikan bila ternyata salah. Sirene mengganggu seluruh
lingkungan dan memanggil orang, jadi ia menunggu keputusan yang lebih matang.

**Perangkat tetap bekerja tanpa server.** Bila WiFi mati, ESP32 masuk LOCAL
MODE: verifikasi tahap 1 tetap jalan dan strobe tetap menyala. Yang hilang
hanya sirene dan pencatatan.

**Server hanya boleh memperketat, tidak melonggarkan.** `LOCAL_REJECTED` tidak
dapat dinaikkan menjadi `CONFIRMED` oleh server. Bila perangkat sudah menilai
tidak ada bukti, server tidak berhak mengarang bukti itu.


## AI dan model apa saja yang dipakai

Bagian ini ditulis apa adanya, termasuk bagian yang **belum** benar-benar AI.
Menyebut heuristik sebagai "AI" akan membuat siapa pun yang membaca kode ini
mengambil kesimpulan yang salah.

| Komponen | Statusnya | Yang sebenarnya berjalan |
|---|---|---|
| **Hotspot risk** | **Model ML nyata** | `random_forest_pipeline.pkl` — scikit-learn `RandomForestClassifier`, 300 pohon, 18 fitur, kelas `High`/`Medium`/`Low` |
| **Keputusan darurat (tahap 2)** | **Bukan ML** | Aturan berbobot yang ditulis manual. `/api/health` melaporkan `RULE_BASED_SECOND_LEVEL` dengan `is_ai_model: false` |
| **Verifikasi lokal (tahap 1)** | **Bukan ML** | Perbandingan ambang di firmware C++ |
| **Klasifikasi audio** | **Adapter, belum ML** | `audio-feature-adapter-v1` — mengubah fitur ringkas menjadi probabilitas secara deterministik. Bukan jaringan saraf |
| **Pencahayaan** | **Estimasi** | Dihitung dari jam + cuaca. Bukan sensor cahaya |

### 1. Random Forest untuk hotspot — satu-satunya ML sungguhan

Model ini menjawab satu pertanyaan: *seberapa rawan lokasi dan waktu ini?*
Jawabannya `High`, `Medium`, atau `Low`, beserta probabilitas tiap kelas.

```
Pipeline
├── preprocessor : ColumnTransformer
│                  ├── OneHotEncoder(handle_unknown='ignore')  -> fitur kategorikal
│                  └── passthrough                             -> fitur numerik
└── classifier   : RandomForestClassifier(n_estimators=300)
```

Hasilnya **bukan** keputusan darurat. Ia hanya satu bukti di antara enam, dan
bobotnya 0.14 — di bawah ambang, sehingga hotspot `High` sendirian tidak pernah
cukup untuk membunyikan sirene.

Dua hal yang perlu diketahui sebelum memakai model ini:

**Model di-pickle dengan scikit-learn 1.7.2**, dan `requirements.txt`
me-*pin* versi itu. Versi lain dapat memunculkan `InconsistentVersionWarning`
atau gagal memuat sama sekali. scikit-learn 1.7.2 belum mendukung Python 3.14,
jadi proyek ini memakai Python 3.13.

**`OneHotEncoder` memakai `handle_unknown='ignore'`.** Nilai yang tidak dikenal
tidak menimbulkan error — ia diubah menjadi vektor nol secara diam-diam, dan
prediksi tetap keluar terlihat sah. Karena itu server memvalidasi seluruh nilai
kategorikal terhadap kosakata model dan menolak yang asing dengan HTTP 400.
Dibiarkan lolos, `"village": "Menteng"` akan menghasilkan angka yang tampak
masuk akal padahal masukannya tidak pernah dikenal model.

### 2. Adapter audio — jujur soal apa yang belum ada

Tidak ada model AI yang berjalan di ESP32, dan tidak ada jalur yang menerima
WAV/PCM mentah. `audio-feature-adapter-v1` menerima dua bentuk masukan:

| Masukan dari perangkat | `audio_source` | Arti |
|---|---|---|
| `class_probabilities` | `hardware-model-output` | Perangkat sudah menjalankan model TinyML sendiri |
| fitur ringkas (energy, peak, ZCR, dll.) | `feature-fallback` | Diubah menjadi probabilitas deterministik oleh adapter |

Jalur pertama sudah siap dipakai begitu model TinyML dipasang di perangkat —
kontrak HTTP-nya tidak perlu berubah. Jalur kedua yang dipakai sekarang, dan
itu **bukan** inferensi audio: ia hanya memetakan angka ke angka.

Mikrofon belum terpasang. Nilai audio saat ini diisi lewat tombol simulasi atau
perintah Serial.

### 3. Ada model sintetis di repo yang TIDAK dipakai

`backend/services/ai/core/ai_models.py` memuat `HotspotPredictor`
(`random-forest-lite-synthetic-v1`) — implementasi random forest murni Python
yang dilatih pada data sintetis. Kelas ini **tidak dipanggil dari mana pun**.

Yang benar-benar dipakai adalah `.pkl` sungguhan lewat
`model_loader.get_rf_pipeline()`. `HotspotPredictor` adalah sisa dari tahap
awal pengembangan, ketika file model belum tersedia. Disebutkan di sini supaya
tidak ada yang salah menyimpulkan bahwa prediksi hotspot berasal dari data
sintetis.

### 4. Mengapa keputusan darurat tidak diserahkan ke ML

Ini pilihan sadar, bukan keterbatasan.

Keputusan membunyikan sirene di ruang publik harus dapat dijelaskan kepada
operator dan warga. Aturan berbobot dapat dibaca baris per baris: setiap
komponen punya angka, dan setiap penolakan dapat dilacak sebab-akibatnya.
Model klasifikasi akan memberi keluaran yang lebih sulit dipertanggungjawabkan
ketika salah.

Selain itu tidak ada dataset kejadian darurat nyata di wilayah ini untuk
melatih model semacam itu. Melatihnya pada data sintetis lalu memakainya untuk
memutuskan keadaan darurat akan menghasilkan keyakinan yang tidak berdasar.

Bobotnya sendiri **dipilih manual dan belum divalidasi terhadap data lapangan.**
Itu batasan yang diketahui, dan ditulis juga di dalam kode.


## Random Forest: 18 fitur dan asalnya

Model butuh 18 fitur. Asalnya berbeda-beda, dan perbedaan itu penting: fitur
dari API bisa gagal, fitur dari operator bisa belum diisi, dan keduanya
ditangani tidak dengan cara yang sama.

| # | Fitur | Sumber | Status kejujuran |
|---|---|---|---|
| 1 | `Hour` | jam server | nyata |
| 2 | `Day_of_Week` | jam server | nyata |
| 3 | `Month` | jam server | nyata |
| 4 | `Village` | operator | konfigurasi |
| 5 | `Weather` | Open-Meteo | **API nyata** |
| 6 | `Temperature` | Open-Meteo | **API nyata** |
| 7 | `Rainfall` | Open-Meteo | **API nyata** |
| 8 | `Public_Event` | operator | statis / belum ada sumber kalender |
| 9 | `Holiday` | operator | statis / belum ada sumber kalender |
| 10 | `Traffic_Level` | TomTom | **API nyata** |
| 11 | `Lighting_Condition` | jam + cuaca | **estimasi, bukan sensor** |
| 12 | `Nearby_CCTV` | operator | konfigurasi |
| 13 | `Nearby_Police_Post` | operator | konfigurasi |
| 14 | `Previous_Incidents_Last30Days` | database sendiri | nyata |
| 15 | `Emergency_Call_Last30Days` | database sendiri | nyata |
| 16 | `Population_Density` | operator (data BPS) | konfigurasi |
| 17 | `Road_Type` | operator | konfigurasi |
| 18 | `Area_Type` | operator | konfigurasi |

Urutan fitur **tidak** ditulis manual di kode. Ia dibaca dari
`feature_names_in_` milik model itu sendiri, sehingga tidak ada kemungkinan
salah tebak urutan.

### Bila ada fitur yang tidak tersedia

Model **tidak dipanggil sama sekali**. Statusnya `MISSING_FEATURES`,
`hotspot_risk` bernilai `null`, dan bobot hotspot dikeluarkan dari perhitungan
lalu bobot sisanya dinormalisasi.

Ini berbeda dari mengisi nol, dan bedanya menentukan. `null` berarti "tidak
diketahui"; `0.0` berarti "lokasi ini aman". Menyamakan keduanya akan
menurunkan skor dan berpotensi **menolak kejadian nyata** di titik yang
kebetulan belum dikonfigurasi.

`Population_Density` khususnya tidak pernah diberi nilai default. Pipeline
memakai `passthrough` tanpa scaler, jadi angka dengan satuan yang salah —
misalnya ribu jiwa/km² alih-alih jiwa/km² — akan menggeser prediksi tanpa
terdeteksi sebagai kesalahan.


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

### Bobot tahap 2

Total 1.0. Angka ini ada di `backend/services/verification.py`.

| Komponen | Bobot | Sumber bukti |
|---|---|---|
| `WEIGHT_AUDIO` | 0.30 | kelas audio + keyakinan/distress |
| `WEIGHT_SOS` | 0.28 | tombol SOS ditekan manusia |
| `WEIGHT_HOTSPOT` | 0.14 | Random Forest |
| `WEIGHT_HISTORY` | 0.12 | riwayat device (database sendiri) |
| `WEIGHT_ENV` | 0.08 | pencahayaan, cuaca, lalu lintas |
| `WEIGHT_EMERGENCY_STATE` | 0.08 | status darurat perangkat |

Perhatikan bahwa **tidak ada satu pun bobot yang mencapai ambang**
`SERVER_CONFIRM_THRESHOLD` (0.70). Itu bukan kebetulan — sifat itu yang membuat
SOS saja, audio 100% saja, atau hotspot `High` saja tidak pernah cukup untuk
membunyikan sirene. Ada test yang menjaganya, sehingga menaikkan satu bobot
melewati ambang akan menggagalkan test lebih dulu.

Bobot ini **dipilih manual dan belum divalidasi terhadap data lapangan.**


## Sensor tamper

Saklar di dalam kotak perangkat mendeteksi pembongkaran paksa. Dilaporkan lewat
`POST /api/device/tamper`, dan keadaannya juga dititipkan di setiap heartbeat
sebagai jaring pengaman bila laporan pertama gagal terkirim.

Tamper **sengaja tidak masuk jalur emergency**, dan alasannya penting:

**Tidak membuat incident.** Verifikasi tahap 2 menilai bukti darurat korban —
SOS dan audio. Pembongkaran kotak tidak punya keduanya, jadi bila dipaksa lewat
jalur itu skornya akan selalu di bawah ambang dan tercatat sebagai
`FALSE_ALARM`. Label itu keliru untuk peristiwa yang benar-benar terjadi, dan
akan mengotori statistik incident.

**Tidak menyalakan sirene atau strobe.** Sirene memberi tahu pelaku bahwa ia
terdeteksi, dan membuat warga menyangka ada korban padahal tidak ada.

Yang dilakukan hanya mencatat dan menandai di dashboard. Operator yang
memutuskan tindakan.

### Jenis saklar menentukan apakah ini berguna

| Mode | Saklar | Level "kotak terbuka" |
|---|---|---|
| `WOKWI_BUILD 1` | pushbutton normally-open | `LOW` |
| `WOKWI_BUILD 0` | **normally-closed** | `HIGH` |

Di lapangan pakailah **normally-closed** yang tertekan oleh tutup kotak. Dengan
susunan itu, **kabel yang dipotong juga terbaca HIGH** dan tetap dianggap
tamper. Dengan normally-open, pelaku cukup memotong kabel sensornya dan
pembongkaran tidak akan pernah terdeteksi — kegagalan yang justru menguntungkan
pelaku.

Konsekuensi yang perlu diingat: GPIO 8 **harus** terpasang di perangkat nyata.
Dibiarkan menggantung dengan `WOKWI_BUILD 0`, pull-up internal membuatnya HIGH,
dan perangkat akan melaporkan tamper terus-menerus.

### Jejak tidak terhapus

Menutup kembali kotak tidak menghapus fakta bahwa ia pernah dibuka:
`ever_tampered` tetap `true` dan dashboard menampilkan `PERNAH DIBONGKAR`. Log
hanya ditulis saat keadaan **berubah** — tanpa itu, heartbeat setiap 8 detik
akan menghasilkan ratusan baris identik dan peristiwa nyata tenggelam di
antaranya.

Database yang sudah ada perlu dimigrasi sekali:

```bash
.venv\Scripts\python.exe scripts\migrate_add_tamper_columns.py
```


## Struktur proyek

```
backend/
  app.py                    factory Flask
  models.py                 4 tabel: devices, incidents, commands, logs
  schemas.py                validasi payload (manual, tanpa library)
  routes/                   endpoint HTTP
  services/
    verification.py         ATURAN BERBOBOT tahap 2 (bukan ML)
    incident_service.py     alur incident
    command_service.py      command ke perangkat
    device_service.py       registrasi, heartbeat, tamper
    ai/
      model_loader.py       memuat .pkl, lazy, tidak crash bila hilang
      audio_service.py      adapter audio
      core/
        rf_predictor.py     PREDIKSI HOTSPOT (memakai .pkl sungguhan)
        ai_models.py        adapter audio + HotspotPredictor (TIDAK dipakai)
    context/
      builder.py            menyusun 18 fitur
      hotspot_service.py    gerbang: model dipanggil hanya bila fitur lengkap
      weather_service.py    Open-Meteo
      traffic_service.py    TomTom
      lighting_service.py   ESTIMASI dari jam + cuaca
      history_service.py    riwayat dari database sendiri
  models_store/
    random_forest_pipeline.pkl    75,6 MB — TIDAK di-commit

esp32/
  include/config.h          pin, ambang, interval (tanpa secret)
  include/secrets.h         WiFi + DEVICE_API_KEY — TIDAK di-commit
  src/main.cpp              firmware
  diagram.json              rangkaian Wokwi
  WOKWI.md                  panduan simulasi
  WIRING.md                 wiring fisik

frontend/                   dashboard (Flask templates + JS biasa)
simulation/simulator.py     menguji seluruh API tanpa board
scripts/                    migrasi database + alat inspeksi model
tests/                      224 test
```

Pola **adapter** dipakai di `services/ai/` dan `services/context/`: file di
`core/` dibiarkan apa adanya, dan lapisan di atasnya yang menambahkan status,
validasi, serta penanganan kegagalan. Dengan begitu perbedaan antara "API
berhasil", "API tidak punya kunci", dan "API error" tidak pernah tersamar
menjadi satu nilai yang sama.


## Daftar endpoint

### Perangkat — `X-API-Key`

| Method | Endpoint | Fungsi |
|---|---|---|
| POST | `/api/device/register` | registrasi saat boot (idempotent) |
| POST | `/api/device/heartbeat` | status berkala + keadaan tamper |
| POST | `/api/device/tamper` | laporan kotak dibuka / tertutup |
| POST | `/api/emergency/evaluate` | **verifikasi tahap 2** |
| GET | `/api/device/<id>/command` | ambil command aktif |
| POST | `/api/device/<id>/command/ack` | konfirmasi command dijalankan |
| POST | `/api/device/<id>/command/clear` | batalkan command |

### Operator — `X-Operator-Key`

| Method | Endpoint | Efek |
|---|---|---|
| PUT | `/api/device/<id>/config` | ubah konfigurasi konteks |
| POST | `/api/incidents/<id>/confirm` | `CONFIRMED` + command sirene |
| POST | `/api/incidents/<id>/false-alarm` | `FALSE_ALARM` + command clear |
| POST | `/api/incidents/<id>/dispatch` | `DISPATCHED`, tanpa command |
| POST | `/api/incidents/<id>/close` | `CLOSED` + command clear |

### Terbuka — dipakai dashboard

| Method | Endpoint | Fungsi |
|---|---|---|
| GET | `/api/health` | status server, model, dan metode verifikasi |
| GET | `/api/devices` | daftar device + `tamper_state` |
| GET | `/api/incidents` | daftar incident |
| GET | `/api/statistics` | ringkasan |
| GET | `/api/logs` | jejak audit |
| GET | `/api/device/config/options` | kosakata sah dari model |

Halaman web: `/dashboard`, `/devices`, `/incidents`, `/history`.

`/api/health` adalah tempat memeriksa kejujuran sistem — ia melaporkan model
apa yang dimuat, berapa fiturnya, dan bahwa metode keputusan adalah
`RULE_BASED_SECOND_LEVEL` dengan `is_ai_model: false`.


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
| `N` | set audio ke nilai yang DITOLAK (0.20, kelas Normal) |
| `S` | simulasi tombol SOS |
| `T` | trigger test (audio 0.90 + SCREAM + SOS) |
| `R` | reset ke READY |
| `C` | poll command sekarang |
| `H` | kirim heartbeat sekarang |
| `G` | register ulang |
| `?` | tampilkan status |

Perintah `N` menggantikan tombol NORMAL AUDIO yang sudah dihapus dari diagram
Wokwi: GPIO 8 sekarang dipakai sensor tamper.

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


## Batasan yang diketahui

Ditulis terbuka supaya tidak ada yang mengira sistem ini lebih siap daripada
kenyataannya.

| Bagian | Keadaan sebenarnya |
|---|---|
| Mikrofon | **Belum terpasang.** Nilai audio berasal dari tombol simulasi atau Serial |
| Klasifikasi audio | Adapter deterministik, **bukan** model ML |
| Bobot verifikasi | Dipilih manual, **belum divalidasi** terhadap data lapangan |
| `Lighting_Condition` | Estimasi dari jam + cuaca, **bukan** sensor cahaya |
| `Public_Event`, `Holiday` | Statis; belum ada sumber kalender |
| Autentikasi | Satu kunci bersama, tanpa identitas per operator, tanpa masa berlaku |
| Mode Wokwi | HTTP tanpa enkripsi; `DEVICE_API_KEY` terkirim polos |
| Cakupan model | Hanya 6 kelurahan di Kiaracondong |
| Pin firmware | Sebagian masih ditandai `PIN TO CONFIRM` |

Catatan tentang cakupan model: `Village` hanya mengenal Babakan Sari, Babakan
Surabaya, Cicaheum, Kebon Jayanti, Kebon Kangkung, dan Sukapura. Device di luar
wilayah itu tidak dapat diprediksi hotspot-nya. Bila dipaksakan,
`handle_unknown='ignore'` akan mengubahnya menjadi vektor nol dan menghasilkan
angka yang tampak sah — itulah sebabnya server menolaknya lebih dulu.


## Population_Density

Satuan fitur ini adalah **jiwa/km²**, dan harus sama dengan dataset training.
Rentang pada data training kira-kira 23.510-35.491 jiwa/km².

Nilainya diisi per device lewat endpoint konfigurasi, memakai data BPS untuk
kelurahan tempat titik PJU berada. Contoh untuk Kelurahan Kebon Kangkung:
13.161 jiwa / 0,58 km² menghasilkan sekitar 22.184 jiwa/km².

Bila belum diisi, nilainya `null` dan inilah yang terjadi:

- Prediksi hotspot berstatus `MISSING_FEATURES`; model **tidak** dipanggil.
- `hotspot_risk` bernilai `null`, bukan `0.0`.
- Verifikasi tahap 2 mengeluarkan bobot hotspot lalu menormalisasi bobot yang
  tersisa, sehingga kejadian nyata di titik yang belum dikonfigurasi tetap
  dapat CONFIRMED bila bukti lain kuat.
- Halaman Devices menampilkan penanda bahwa konfigurasi populasi belum ada.

Nilai ini **tidak pernah** diisi angka perkiraan oleh server. Dua alasannya:
`null` berarti "tidak diketahui" sedangkan `0.0` berarti "tidak ada penduduk".
Menyamakan keduanya akan menurunkan skor dan berpotensi menolak kejadian nyata.
Selain itu pipeline tidak memakai scaler, jadi satuan yang berbeda dari dataset
training akan menggeser prediksi tanpa terdeteksi sebagai kesalahan.
