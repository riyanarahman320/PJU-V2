"""Simulator perangkat ASEP-JAGA.

Berperilaku seperti ESP32 terhadap server: memakai endpoint, payload, dan
header yang sama persis dengan firmware di esp32/src/main.cpp. Gunanya untuk
menguji seluruh alur API tanpa hardware.

Yang disimulasikan:
    POST /api/device/register
    POST /api/device/heartbeat
    POST /api/emergency/evaluate
    GET  /api/device/<id>/command
    POST /api/device/<id>/command/ack
    POST /api/device/<id>/command/clear

Seperti firmware, simulator ini HANYA memakai DEVICE_API_KEY. Kunci operator
tidak pernah dipakai di sisi perangkat.

IDEMPOTENCY
Sama seperti firmware, simulator membuat satu `event_id` untuk satu kejadian
emergency dan memakai nilai yang sama pada setiap pengiriman ulang. Ini yang
membuat retry akibat timeout tidak menghasilkan incident ganda di server.
Format nilainya mengikuti firmware: `<bootId>-<nomor urut>`.

Cara pakai:
    python simulation/simulator.py                 # mode interaktif
    python simulation/simulator.py --auto           # alur otomatis sekali jalan
    python simulation/simulator.py --device ASEP-012

Kunci dibaca dari environment atau file .env di root project. Tidak ada nilai
default yang ditanam di kode ini.
"""

import argparse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Ambang HARUS sama dengan Config.AUDIO_CONFIDENCE_MIN dan config.h firmware.
AUDIO_CONFIDENCE_MIN = 0.60
AUDIO_CONFIDENCE_STRONG = 0.85
AUDIO_CONFIDENCE_NO_SOS = 0.90

# Kata kunci kelas audio darurat, sama dengan _KATA_DARURAT di
# backend/services/verification.py dan isEmergencyAudioClass() di firmware.
KATA_DARURAT = (
    "SCREAM",
    "TERIAK",
    "HELP",
    "DISTRESS",
    "TOLONG",
    "SHOUT",
    "IMPACT",
    "BENTUR",
    "CRASH",
    "GLASS",
)
KELAS_NORMAL = ("NORMAL", "NONE", "SILENCE", "UNKNOWN", "")


def muat_dotenv(path: Path) -> dict:
    """Baca .env sederhana tanpa dependency tambahan."""
    nilai = {}
    if not path.exists():
        return nilai
    for baris in path.read_text(encoding="utf-8").splitlines():
        baris = baris.strip()
        if not baris or baris.startswith("#") or "=" not in baris:
            continue
        kunci, _, isi = baris.partition("=")
        nilai[kunci.strip()] = isi.strip().strip('"').strip("'")
    return nilai


class SimulatorPerangkat:
    """Tiruan ESP32 dengan state yang sama seperti firmware."""

    def __init__(self, base_url: str, device_id: str, api_key: str,
                 latitude: float, longitude: float, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.device_id = device_id
        self.api_key = api_key
        self.latitude = latitude
        self.longitude = longitude
        self.timeout = timeout

        # State, mencerminkan variabel firmware.
        self.local_emergency_active = False
        self.server_confirmed = False
        self.registered = False
        self.audio_confidence = 0.0
        self.audio_class = "Normal"
        self.active_incident_id = None

        # --- Idempotency, mencerminkan bootId / eventCounter / currentEventId
        # di firmware.
        #
        # boot_id dibuat sekali per proses dan menjadi bagian dari setiap
        # event_id. Tanpa pembeda ini, dua kali menjalankan simulator dapat
        # menghasilkan event_id yang sama, dan kejadian yang benar-benar baru
        # akan dianggap retry lalu diabaikan server. Itu kegagalan yang lebih
        # berbahaya daripada incident ganda, karena kejadian nyata hilang.
        self.boot_id = f"{secrets.randbits(32):08x}"
        self.event_counter = 0
        self.current_event_id = None
        # sos kejadian yang sedang berjalan; retry harus mengirim nilai yang
        # sama, sama seperti firmware yang memakai sosLatched.
        self.event_sos = False

    # --- HTTP ------------------------------------------------------------

    def _request(self, method: str, path: str, payload=None):
        """Kembalikan (status, body_dict). status 0 bila server tak terjangkau."""
        url = self.base_url + path
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        # Perangkat memakai DEVICE_API_KEY, sama seperti firmware.
        request.add_header("X-API-Key", self.api_key)

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as respons:
                isi = respons.read().decode("utf-8")
                return respons.status, json.loads(isi) if isi else {}
        except urllib.error.HTTPError as error:
            isi = error.read().decode("utf-8")
            try:
                return error.code, json.loads(isi) if isi else {}
            except json.JSONDecodeError:
                return error.code, {"error": isi}
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            print(f"  [HTTP] Server tidak terjangkau: {error}")
            return 0, {}

    # --- Verifikasi lokal (TAHAP 1) --------------------------------------

    @staticmethod
    def kelas_darurat(kelas: str) -> bool:
        teks = str(kelas or "").strip().upper()
        if teks in KELAS_NORMAL:
            return False
        return any(kata in teks for kata in KATA_DARURAT)

    def verifikasi_lokal(self, sos: bool) -> str:
        """Cermin verify_local() server dan localAudioVerified() firmware.

        SOS TIDAK PERNAH melewati verifikasi audio: tidak ada cabang yang
        mengembalikan LOCAL_VERIFIED hanya karena sos bernilai True.
        """
        relevan = self.kelas_darurat(self.audio_class)
        kuat = self.audio_confidence >= AUDIO_CONFIDENCE_MIN

        if sos and kuat and relevan:
            return "LOCAL_VERIFIED"
        if sos and self.audio_confidence >= AUDIO_CONFIDENCE_STRONG:
            return "LOCAL_VERIFIED"
        if not sos and relevan and self.audio_confidence >= AUDIO_CONFIDENCE_NO_SOS:
            return "LOCAL_VERIFIED"
        return "LOCAL_REJECTED"

    # --- Aksi perangkat --------------------------------------------------

    def register(self) -> bool:
        """POST /api/device/register (idempotent di server)."""
        status, body = self._request(
            "POST",
            "/api/device/register",
            {
                "device_id": self.device_id,
                "name": f"Simulator {self.device_id}",
                "location": "Jl. Babakan Sari, Kiaracondong",
                "latitude": self.latitude,
                "longitude": self.longitude,
                "firmware_version": "simulator-1.0.0",
            },
        )

        if status in (200, 201):
            baru = body.get("data", {}).get("created")
            self.registered = True
            print(f"  [REGISTER] HTTP {status} — "
                  f"{'device baru' if baru else 'data diperbarui'}")
            return True

        if status == 401:
            print("  [REGISTER] HTTP 401: DEVICE_API_KEY salah atau tidak "
                  "dikirim. Periksa .env server.")
        else:
            print(f"  [REGISTER] Gagal, HTTP {status}: {body.get('error', '')}")
        return False

    def heartbeat(self) -> bool:
        """POST /api/device/heartbeat."""
        status, body = self._request(
            "POST",
            "/api/device/heartbeat",
            {
                "device_id": self.device_id,
                "status": "ONLINE",
                "network": True,
                # Mikrofon belum ada, jadi dilaporkan False — sama seperti
                # firmware. Melaporkan True akan menyesatkan operator.
                "audio": False,
                "camera": False,
                "firmware_version": "simulator-1.0.0",
            },
        )

        if status == 404:
            print("  [HEARTBEAT] HTTP 404: device belum terdaftar.")
            self.registered = False
            return False
        if status != 200:
            print(f"  [HEARTBEAT] Gagal, HTTP {status}")
            return False

        data = body.get("data", {})
        pending = data.get("has_pending_command")
        insiden = data.get("active_incident_id")
        print(f"  [HEARTBEAT] OK"
              f"{' — ada command menunggu' if pending else ''}"
              f"{f' — incident aktif {insiden}' if insiden else ''}")
        return True

    def mulai_kejadian_baru(self, sos: bool) -> str:
        """Buat satu event_id untuk satu kejadian emergency.

        Cermin beginNewEvent() di firmware. Dipanggil TEPAT SEKALI per
        kejadian, pada saat verifikasi lokal berhasil. Retry TIDAK boleh
        memanggilnya: kunci baru membuat server tidak lagi dapat mengenali
        pengiriman ulang sebagai kejadian yang sama, dan justru itu yang
        menghasilkan incident ganda.
        """
        self.event_counter += 1
        self.current_event_id = f"{self.boot_id}-{self.event_counter}"
        self.event_sos = sos
        print(f"  [EVENT] Kejadian baru, event_id = {self.current_event_id}")
        return self.current_event_id

    def _kirim_payload_emergency(self, sos: bool, keputusan: str) -> dict | None:
        """Satu percobaan POST /api/emergency/evaluate.

        Dipakai jalur kejadian baru dan jalur retry. Keduanya mengirim payload
        yang sama, termasuk event_id yang sama, sehingga server dapat mengenali
        retry tanpa perangkat perlu memberi tahu bahwa ini pengiriman ulang.
        """
        payload = {
            "device_id": self.device_id,
            "sos": sos,
            "audio_confidence": self.audio_confidence,
            "audio_class": self.audio_class,
            "local_decision": keputusan,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }

        # IDEMPOTENCY KEY. Hanya dikirim bila ada isinya: string kosong tidak
        # dianggap kunci oleh server, jadi lebih jujur tidak mengirimnya.
        if self.current_event_id:
            payload["event_id"] = self.current_event_id

        status, body = self._request(
            "POST", "/api/emergency/evaluate", payload
        )

        if status == 0:
            print("  [EVENT] Server tidak terjangkau. STROBE TETAP ON.")
            print("  [EVENT] Kejadian dapat dikirim ulang dengan event_id "
                  "yang sama tanpa risiko incident ganda.")
            return None
        if status != 200:
            print(f"  [EVENT] Gagal, HTTP {status}: {body.get('error', '')}")
            for rincian in body.get("details", []):
                print(f"          - {rincian}")
            print("  [EVENT] STROBE TETAP ON (kegagalan HTTP tidak "
                  "mengakhiri keadaan darurat lokal).")
            return None

        data = body.get("data", {})
        self.active_incident_id = data.get("incident_id")
        duplicate = bool(data.get("duplicate"))

        print(f"  [EVENT] {data.get('incident_id')} -> "
              f"{data.get('server_decision')} "
              f"(skor {data.get('server_score')}, "
              f"metode {data.get('verification_method')})")

        if duplicate:
            print("  [EVENT] duplicate=true — server mengenali ini sebagai "
                  "pengiriman ulang; incident TIDAK digandakan.")

        konteks = data.get("context", {})
        hotspot = konteks.get("hotspot_risk")
        print(f"  [KONTEKS] hotspot={hotspot if hotspot is not None else 'null'}"
              f" ({konteks.get('hotspot_status')})"
              f", cuaca={konteks.get('weather')}"
              f", lalu lintas={konteks.get('traffic')}"
              f", pencahayaan={konteks.get('lighting_condition')}")
        if hotspot is None:
            print("  [KONTEKS] hotspot null = TIDAK DIKETAHUI (bukan nol). "
                  "Bobotnya dikeluarkan lalu dinormalisasi.")

        return data

    def kirim_emergency(self, sos: bool) -> dict | None:
        """POST /api/emergency/evaluate setelah verifikasi lokal lolos.

        Mengikuti urutan firmware: strobe menyala LEBIH DULU, baru event
        dikirim. Strobe tidak menunggu jaringan.

        Setiap pemanggilan dianggap KEJADIAN BARU dan mendapat event_id baru.
        Untuk mengirim ulang kejadian yang sama, pakai kirim_emergency_ulang().
        """
        keputusan = self.verifikasi_lokal(sos)
        print(f"  [VERIFY] {keputusan} "
              f"(audio {self.audio_confidence:.2f}, kelas {self.audio_class})")

        if keputusan == "LOCAL_REJECTED":
            print("  [STROBE] TETAP OFF — verifikasi lokal menolak.")
            print("  [VERIFY] SOS saja tidak cukup; verifikasi audio wajib "
                  "dilewati juga.")
            # Tidak ada event_id yang dibuat: kejadian ini tidak pernah ada
            # bagi server.
            return None

        # Kunci dibuat di sini, sejalan dengan firmware yang memanggil
        # beginNewEvent() tepat setelah verifikasi lokal berhasil.
        self.mulai_kejadian_baru(sos)

        # Fail-safe lokal: strobe menyala sebelum HTTP apa pun.
        self.local_emergency_active = True
        print("  [STROBE] ON (fail-safe lokal, tidak menunggu server)")

        return self._kirim_payload_emergency(sos, keputusan)

    def kirim_emergency_ulang(self) -> dict | None:
        """Kirim ulang kejadian yang sedang berjalan, memakai event_id yang sama.

        Meniru retry firmware: pada loop berikutnya sendEmergencyEvent()
        dipanggil lagi untuk kejadian yang sama, TANPA menjalankan verifikasi
        lokal ulang dan TANPA membuat kunci baru.

        Dipakai untuk menguji bahwa server benar-benar mencegah duplicate:
        hasilnya harus incident yang sama dengan `duplicate: true`.
        """
        if not self.current_event_id:
            print("  [EVENT] Tidak ada kejadian berjalan untuk dikirim ulang.")
            print("  [EVENT] Jalankan trigger emergency lebih dulu (S / T).")
            return None

        print(f"  [EVENT] RETRY kejadian yang sama "
              f"(event_id {self.current_event_id})")
        # local_decision tidak dihitung ulang: keputusan tahap 1 milik
        # kejadian ini sudah diambil dan tidak berubah karena jaringan gagal.
        return self._kirim_payload_emergency(self.event_sos, "LOCAL_VERIFIED")

    def poll_command(self) -> dict | None:
        """GET /api/device/<id>/command lalu jalankan perintahnya."""
        status, body = self._request(
            "GET", f"/api/device/{self.device_id}/command"
        )

        if status != 200:
            print(f"  [COMMAND] Gagal, HTTP {status}")
            return None

        data = body.get("data", {})
        command = data.get("command", "NONE")

        if command == "NONE":
            # Tidak mematikan strobe: "NONE" hanya berarti tidak ada perintah
            # baru, bukan bahwa kejadian sudah berakhir.
            print("  [COMMAND] NONE (strobe tidak diubah)")
            return data

        print(f"  [COMMAND] {command} (id {data.get('command_id')})")

        if command == "EMERGENCY_CONFIRMED":
            self.server_confirmed = True
            if data.get("strobe"):
                self.local_emergency_active = True
                print("  [STROBE] ON")
            if data.get("siren"):
                print("  [SIREN] ON (server CONFIRMED)")
            if data.get("speaker"):
                print(f"  [SPEAKER] {data.get('voice_message')}")
                print("  [SPEAKER] CATATAN: hardware suara belum terpasang.")
            self.ack_command(data.get("command_id"))

        elif command == "CLEAR_EMERGENCY":
            print("  [COMMAND] CLEAR_EMERGENCY: mengakhiri keadaan darurat.")
            self.ack_command(data.get("command_id"))
            self.reset()

        return data

    def ack_command(self, command_id) -> bool:
        """POST /api/device/<id>/command/ack."""
        if not command_id:
            return False
        status, _ = self._request(
            "POST",
            f"/api/device/{self.device_id}/command/ack",
            {"command_id": command_id},
        )
        print(f"  [ACK] command {command_id} -> HTTP {status}")
        return status == 200

    def clear_command(self) -> bool:
        """POST /api/device/<id>/command/clear."""
        status, body = self._request(
            "POST", f"/api/device/{self.device_id}/command/clear", {}
        )
        if status == 200:
            jumlah = body.get("data", {}).get("cleared", 0)
            print(f"  [CLEAR] {jumlah} command dibatalkan.")
            return True
        print(f"  [CLEAR] Gagal, HTTP {status}")
        return False

    def reset(self):
        """Kembali ke READY, sama seperti resetEmergency() firmware."""
        self.local_emergency_active = False
        self.server_confirmed = False
        self.audio_confidence = 0.0
        self.audio_class = "Normal"
        self.active_incident_id = None
        # Kejadian ini selesai. Kunci dikosongkan supaya kejadian berikutnya
        # mendapat kunci baru dan tidak dianggap retry dari kejadian yang sudah
        # ditutup. event_counter TIDAK direset: nilainya harus terus naik.
        self.current_event_id = None
        self.event_sos = False
        print("  [RESET] Semua output OFF. Perangkat READY.")

    def status(self):
        print("  --------------- STATUS ---------------")
        print(f"  device_id            : {self.device_id}")
        print(f"  server               : {self.base_url}")
        print(f"  registered           : {'ya' if self.registered else 'belum'}")
        print(f"  localEmergencyActive : {self.local_emergency_active}")
        print(f"  serverConfirmed      : {self.server_confirmed}")
        print(f"  audio_confidence     : {self.audio_confidence:.2f} "
              f"(nilai uji, bukan hasil model)")
        print(f"  audio_class          : {self.audio_class}")
        print(f"  incident aktif       : {self.active_incident_id or '-'}")
        print(f"  boot_id              : {self.boot_id}")
        print(f"  event_id kejadian    : {self.current_event_id or '-'}")
        print(f"  jumlah kejadian      : {self.event_counter}")
        print("  --------------------------------------")


# --- Mode otomatis --------------------------------------------------------


def jalankan_alur_otomatis(perangkat: SimulatorPerangkat) -> int:
    """Jalankan alur ESP32 sekali dari awal sampai reset.

    Return 0 bila seluruh langkah wajib berhasil, 1 bila ada yang gagal.
    """
    gagal = []

    print("\n[1] REGISTER")
    if not perangkat.register():
        gagal.append("register")
        # Tanpa registrasi, langkah lain pasti gagal 404.
        print("\nAlur dihentikan: registrasi gagal.")
        return 1

    print("\n[2] HEARTBEAT")
    if not perangkat.heartbeat():
        gagal.append("heartbeat")

    print("\n[3] SOS + AUDIO RENDAH (harus LOCAL_REJECTED)")
    perangkat.audio_confidence = 0.20
    perangkat.audio_class = "Normal"
    if perangkat.kirim_emergency(sos=True) is not None:
        gagal.append("audio rendah seharusnya ditolak lokal")
    if perangkat.local_emergency_active:
        gagal.append("strobe menyala padahal LOCAL_REJECTED")

    print("\n[4] SOS + AUDIO TINGGI (harus LOCAL_VERIFIED)")
    perangkat.audio_confidence = 0.92
    perangkat.audio_class = "SCREAM"
    hasil = perangkat.kirim_emergency(sos=True)
    if hasil is None:
        gagal.append("emergency gagal terkirim")
    if not perangkat.local_emergency_active:
        gagal.append("strobe tidak menyala padahal LOCAL_VERIFIED")

    insiden_pertama = (hasil or {}).get("incident_id")
    event_pertama = perangkat.current_event_id

    print("\n[5] RETRY EVENT YANG SAMA (tidak boleh membuat incident baru)")
    print("    Meniru keadaan responsnya hilang karena timeout: perangkat")
    print("    mengirim ulang kejadian yang sama, bukan kejadian baru.")
    ulang = perangkat.kirim_emergency_ulang()
    if hasil is None:
        print("    Dilewati: kejadian pertama tidak terkirim.")
    elif ulang is None:
        gagal.append("retry gagal terkirim")
    else:
        if perangkat.current_event_id != event_pertama:
            gagal.append("retry memakai event_id baru, bukan yang sama")
        if ulang.get("incident_id") != insiden_pertama:
            gagal.append("RETRY MEMBUAT INCIDENT DUPLICATE")
        if not ulang.get("duplicate"):
            gagal.append("retry tidak ditandai duplicate oleh server")

    print("\n[6] KEJADIAN BARU (event_id berbeda -> incident baru)")
    # Kejadian sebelumnya diakhiri lebih dulu, sama seperti firmware yang
    # hanya memulai kejadian baru setelah kembali ke READY.
    perangkat.reset()
    perangkat.audio_confidence = 0.95
    perangkat.audio_class = "HELP"
    kedua = perangkat.kirim_emergency(sos=True)
    if kedua is None:
        gagal.append("kejadian kedua gagal terkirim")
    else:
        if perangkat.current_event_id == event_pertama:
            gagal.append("kejadian kedua memakai event_id yang sama")
        if kedua.get("duplicate"):
            gagal.append("kejadian baru salah ditandai duplicate")
        if insiden_pertama and kedua.get("incident_id") == insiden_pertama:
            gagal.append("event_id berbeda tidak menghasilkan incident baru")

    print("\n[7] POLLING COMMAND")
    # Server membuat command hanya bila keputusannya CONFIRMED.
    time.sleep(0.5)
    perangkat.poll_command()

    print("\n[8] POLLING BERIKUTNYA (setiap command diambil tepat sekali)")
    print("    Satu command PENDING hanya dikirim sekali; setelah diambil")
    print("    statusnya menjadi SENT. Alur ini menghasilkan dua incident")
    print("    CONFIRMED, jadi ada dua command dan polling ini mengambil")
    print("    command kedua — bukan NONE. NONE baru muncul setelah semua")
    print("    command pending terambil.")
    perangkat.poll_command()

    print("\n[9] STATUS")
    perangkat.status()

    print("\n[10] RESET")
    perangkat.clear_command()
    perangkat.reset()

    print("\n" + "=" * 60)
    if gagal:
        print("HASIL: ADA LANGKAH YANG GAGAL")
        for item in gagal:
            print(f"  - {item}")
        print("=" * 60)
        return 1

    print("HASIL: SELURUH ALUR BERHASIL")
    print("=" * 60)
    return 0


# --- Mode interaktif ------------------------------------------------------

BANTUAN = """
Perintah (mengikuti Serial test mode firmware):
  A <nilai>   set audio confidence, contoh: A 0.90
  K <kelas>   set audio class, contoh: K SCREAM
  S           trigger SOS (menjalankan verifikasi lokal)
  N           trigger tanpa SOS (hanya audio)
  T           trigger emergency test (audio 0.90 + SCREAM + SOS)
  Y           kirim ulang kejadian yang sama (uji idempotency)
  R           reset ke READY
  C           cek server (poll command)
  H           kirim heartbeat
  G           register ulang
  X           clear command di server
  ?           tampilkan status
  Q           keluar
"""


def jalankan_interaktif(perangkat: SimulatorPerangkat) -> int:
    print(BANTUAN)
    perangkat.register()

    while True:
        try:
            baris = input("\nsimulator> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not baris:
            continue

        perintah = baris[0].upper()
        argumen = baris[1:].strip()

        if perintah == "Q":
            return 0

        if perintah == "A":
            try:
                nilai = float(argumen)
            except ValueError:
                print("  Contoh: A 0.90")
                continue
            if not 0.0 <= nilai <= 1.0:
                print("  Nilai harus 0.0 - 1.0.")
                continue
            perangkat.audio_confidence = nilai
            print(f"  audio_confidence = {nilai:.2f} (nilai uji)")

        elif perintah == "K":
            if not argumen:
                print("  Contoh: K SCREAM")
                continue
            perangkat.audio_class = argumen
            relevan = perangkat.kelas_darurat(argumen)
            print(f"  audio_class = {argumen} "
                  f"(relevan: {'ya' if relevan else 'tidak'})")

        elif perintah == "S":
            perangkat.kirim_emergency(sos=True)

        elif perintah == "N":
            perangkat.kirim_emergency(sos=False)

        elif perintah == "T":
            perangkat.audio_confidence = 0.90
            perangkat.audio_class = "SCREAM"
            print("  Trigger test: audio 0.90, kelas SCREAM, SOS aktif.")
            perangkat.kirim_emergency(sos=True)

        elif perintah == "Y":
            perangkat.kirim_emergency_ulang()

        elif perintah == "R":
            perangkat.reset()

        elif perintah == "C":
            perangkat.poll_command()

        elif perintah == "H":
            perangkat.heartbeat()

        elif perintah == "G":
            perangkat.register()

        elif perintah == "X":
            perangkat.clear_command()

        elif perintah == "?":
            perangkat.status()
            print(BANTUAN)

        else:
            print(f"  Perintah '{perintah}' tidak dikenal. Tekan ? untuk bantuan.")


# --- Titik masuk ----------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simulator perangkat ASEP-JAGA (tiruan ESP32)."
    )
    parser.add_argument(
        "--url", default=None,
        help="Base URL server. Default: http://127.0.0.1:5000",
    )
    parser.add_argument(
        "--device", default="ASEP-012",
        help="device_id yang dipakai. Default: ASEP-012",
    )
    parser.add_argument("--latitude", type=float, default=-6.9200)
    parser.add_argument("--longitude", type=float, default=107.6400)
    parser.add_argument(
        "--auto", action="store_true",
        help="Jalankan alur lengkap sekali lalu keluar (untuk pengujian).",
    )
    argumen = parser.parse_args()

    # Kunci dibaca dari environment atau .env. Tidak ada default di kode.
    dotenv = muat_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("DEVICE_API_KEY") or dotenv.get("DEVICE_API_KEY", "")
    base_url = (
        argumen.url
        or os.getenv("SERVER_BASE_URL")
        or dotenv.get("SERVER_BASE_URL")
        or "http://127.0.0.1:5000"
    )

    if not api_key:
        print("DEVICE_API_KEY tidak ditemukan.")
        print()
        print("Simulator memerlukan kunci perangkat yang sama dengan server.")
        print("Isi DEVICE_API_KEY di file .env pada root project, atau set")
        print("environment variable dengan nama yang sama, lalu ulangi.")
        print()
        print("Membuat nilai acak:")
        print('  python -c "import secrets; print(secrets.token_urlsafe(32))"')
        return 2

    print("=" * 60)
    print("  SIMULATOR PERANGKAT ASEP-JAGA")
    print(f"  device_id : {argumen.device}")
    print(f"  server    : {base_url}")
    print("=" * 60)
    print("  Memakai endpoint dan payload yang sama dengan firmware ESP32.")
    print("  Nilai audio adalah nilai uji, bukan hasil inferensi model.")
    print("=" * 60)

    perangkat = SimulatorPerangkat(
        base_url=base_url,
        device_id=argumen.device,
        api_key=api_key,
        latitude=argumen.latitude,
        longitude=argumen.longitude,
    )

    if argumen.auto:
        return jalankan_alur_otomatis(perangkat)
    return jalankan_interaktif(perangkat)


if __name__ == "__main__":
    sys.exit(main())