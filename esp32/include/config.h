/* Konfigurasi firmware ASEP-JAGA (ESP32-S3).
 *
 * File ini memuat pin, ambang batas, dan interval. TIDAK ADA secret di sini;
 * WiFi dan API key berada di include/secrets.h yang tidak di-commit.
 */

#ifndef ASEPJAGA_CONFIG_H
#define ASEPJAGA_CONFIG_H

/* =====================================================================
 * PIN MAPPING - PIN TO CONFIRM
 * =====================================================================
 * Pin di bawah dipilih dari GPIO ESP32-S3 yang umumnya bebas dipakai,
 * dengan menghindari pin yang sudah punya fungsi tetap:
 *
 *   GPIO 0, 45, 46      -> strapping pin (menentukan mode boot)
 *   GPIO 19, 20         -> USB D- / D+ (dipakai USB-Serial-JTAG)
 *   GPIO 26-32          -> SPI flash internal
 *   GPIO 33-37          -> dipakai bila modul memakai octal PSRAM
 *   GPIO 43, 44         -> UART0 TX/RX (Serial Monitor)
 *
 * Pin di sini BELUM final. Sesuaikan dengan wiring dan varian board yang
 * benar-benar dipakai, lalu perbarui esp32/WIRING.md.
 */
#define PIN_SOS_BUTTON 4  /* tombol SOS, ke GND, memakai pull-up internal */
#define PIN_STROBE 5      /* strobe/lampu peringatan (lewat driver/relay)  */
#define PIN_SIREN 6       /* sirene (lewat driver/relay)                   */
#define PIN_SPEAKER 7     /* modul suara / amplifier                       */
#define PIN_STATUS_LED 15 /* indikator status jaringan                     */

/* =====================================================================
 * TOMBOL PENGUJIAN - WOKWI SIMULATION PINS
 * =====================================================================
 * Empat tombol di bawah HANYA untuk simulasi/pengujian. Tombol ini
 * menggantikan pengetikan Serial ('A 0.90', 'K SCREAM', 'C', 'R') supaya
 * demo Wokwi terasa seperti perangkat nyata.
 *
 * PADA PERANGKAT SUNGGUHAN, TOMBOL INI TIDAK DIPASANG.
 * Hanya PIN_SOS_BUTTON yang menjadi tombol nyata di tiang PJU. Tombol
 * NORMAL/DISTRESS AUDIO khususnya tidak boleh pernah ada di lapangan:
 * keduanya memalsukan hasil audio, dan di perangkat nyata nilai itu harus
 * datang dari mikrofon.
 *
 * Pin dipilih dari GPIO yang bebas di header ESP32-S3-DevKitC-1 dan tidak
 * bertabrakan dengan strapping pin (0, 3, 45, 46), USB (19, 20), UART0
 * (43, 44), flash internal (26-32), PSRAM octal (33-37), maupun LED RGB
 * bawaan board (38).
 *
 * Semua tombol dipasang ke GND dengan INPUT_PULLUP: LOW berarti ditekan.
 */
#define PIN_BTN_AUDIO_NORMAL 8    /* WOKWI SIMULATION PIN: audio normal   */
#define PIN_BTN_AUDIO_DISTRESS 9  /* WOKWI SIMULATION PIN: audio distress */
#define PIN_BTN_POLL_SERVER 10    /* WOKWI SIMULATION PIN: poll command   */
#define PIN_BTN_RESET 11          /* WOKWI SIMULATION PIN: reset          */

/* Nilai audio yang dipakai tombol simulasi.
 * Angka ini sengaja mengapit AUDIO_CONFIDENCE_MIN (0.60): 0.20 harus
 * ditolak, 0.90 harus lolos. Bila ambang di bawah diubah, periksa kembali
 * kedua nilai ini supaya kedua tombol tetap bermakna.
 */
#define SIM_AUDIO_NORMAL_CONFIDENCE 0.20f
#define SIM_AUDIO_DISTRESS_CONFIDENCE 0.90f

/* =====================================================================
 * MODE SERVER: WOKWI PROTOTYPE vs HARDWARE NYATA
 * =====================================================================
 * ESP32-S3 di Wokwi gagal melakukan TLS handshake ke tunnel HTTPS publik
 * (gejalanya: start_ssl_client: -80, SSL EOF). Untuk prototype, jalur HTTP
 * biasa dipakai supaya seluruh arsitektur tetap dapat diuji end-to-end.
 *
 *   WOKWI_BUILD 1 -> HTTP biasa   (prototype/simulasi saja)
 *   WOKWI_BUILD 0 -> HTTPS        (hardware nyata, default)
 *
 * Nilai bawaan 0 disengaja: bila seseorang mengupload firmware ini ke
 * perangkat sungguhan tanpa membaca dokumentasi, yang aktif adalah jalur
 * HTTPS, bukan HTTP. Mode tidak aman harus selalu dipilih secara sadar.
 *
 * APA YANG HILANG DI MODE WOKWI
 * -----------------------------
 * HTTP biasa berarti DEVICE_API_KEY dan seluruh isi payload dikirim tanpa
 * enkripsi. Siapa pun di jalur jaringan dapat membacanya dan memalsukan
 * command. Ini HANYA dapat diterima untuk prototype dengan kunci uji.
 * JANGAN memakai mode ini di lapangan, dan jangan memakai kunci produksi
 * saat mode ini aktif.
 *
 * Cara mengubah: ubah angka di bawah lalu `pio run`. URL untuk masing-masing
 * mode diisi di secrets.h (SERVER_BASE_URL_WOKWI / SERVER_BASE_URL_REAL).
 */
#ifndef WOKWI_BUILD
#define WOKWI_BUILD 1
#endif

/* Mikrofon: pin I2S disiapkan tetapi BELUM dipakai.
 * MICROPHONE HARDWARE INTEGRATION REQUIRED - lihat readAudioFeatures().
 */
#define PIN_MIC_I2S_BCLK 16 /* PIN TO CONFIRM */
#define PIN_MIC_I2S_LRCL 17 /* PIN TO CONFIRM */
#define PIN_MIC_I2S_DOUT 18 /* PIN TO CONFIRM */

/* Level aktif untuk aktuator.
 * Modul relay murah umumnya active-LOW; MOSFET module umumnya active-HIGH.
 * Salah nilai membuat sirene menyala terus saat boot, jadi periksa modul
 * yang dipakai sebelum menyalakan daya penuh.
 */
#define ACTUATOR_ACTIVE_HIGH 1

/* =====================================================================
 * AMBANG VERIFIKASI LOKAL
 * =====================================================================
 * Nilai HARUS sama dengan backend/services/verification.py::verify_local()
 * dan Config.AUDIO_CONFIDENCE_MIN. Bila berbeda, perangkat dan server dapat
 * mengambil keputusan berbeda atas kejadian yang sama.
 */
#define AUDIO_CONFIDENCE_MIN 0.60f /* Config.AUDIO_CONFIDENCE_MIN         */
#define AUDIO_CONFIDENCE_STRONG 0.85f /* SOS + suara sangat kuat          */
#define AUDIO_CONFIDENCE_NO_SOS 0.90f /* tanpa SOS, ambang lebih tinggi   */

/* =====================================================================
 * INTERVAL (milidetik)
 * =====================================================================
 */
#define HEARTBEAT_INTERVAL_MS 8000UL   /* 5-10 detik untuk prototype      */
#define COMMAND_POLL_INTERVAL_MS 2000UL /* saat emergency aktif           */
#define COMMAND_POLL_IDLE_MS 5000UL     /* saat keadaan normal            */
#define WIFI_RETRY_INTERVAL_MS 15000UL  /* jarak percobaan sambung ulang  */
#define WIFI_CONNECT_TIMEOUT_MS 12000UL /* batas menunggu saat boot       */
#define REGISTER_RETRY_INTERVAL_MS 20000UL
#define EVENT_RETRY_INTERVAL_MS 10000UL /* retry kirim emergency          */
#define BUTTON_DEBOUNCE_MS 50UL
#define SIREN_BEEP_ON_MS 700UL  /* pola sirene non-blocking               */
#define SIREN_BEEP_OFF_MS 300UL
#define STROBE_BLINK_MS 250UL

/* Timeout HTTP dibuat singkat supaya loop utama tidak membeku puluhan detik
 * saat server tidak terjangkau. Strobe harus tetap responsif.
 */
#define HTTP_TIMEOUT_MS 4000

/* =====================================================================
 * IDENTITAS PERANGKAT
 * =====================================================================
 */
#define FIRMWARE_VERSION "1.0.0-prototype"

/* Kelas audio yang dikirim ke server.
 * Nilai ini dikenali backend/services/verification.py::EMERGENCY_AUDIO_CLASSES.
 * Jangan mengarang nama kelas baru: kelas yang tidak dikenal membuat bobot
 * audio dipotong setengah di verifikasi tahap 2.
 */
#define AUDIO_CLASS_SCREAM "SCREAM"
#define AUDIO_CLASS_HELP "CRY_FOR_HELP"
#define AUDIO_CLASS_IMPACT "IMPACT"
#define AUDIO_CLASS_NORMAL "Normal"

#endif /* ASEPJAGA_CONFIG_H */