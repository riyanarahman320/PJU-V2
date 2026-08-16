"""Riwayat kejadian per device — sumber data NYATA (database sendiri).

File ini bukan mock. Seluruh angka dihitung dari tabel `incidents` milik
sistem ini sendiri.

Menyediakan dua hal:

1. Dua fitur untuk Random Forest:
       Previous_Incidents_Last30Days
       Emergency_Call_Last30Days

2. `history_score` (0.0-1.0) untuk verifikasi tahap 2: seberapa dapat
   dipercaya laporan dari device ini berdasarkan rasio CONFIRMED terhadap
   FALSE_ALARM.

CATATAN PENAFSIRAN FITUR
------------------------
Dataset training tidak disertakan, sehingga definisi persis kedua fitur di
sana tidak dapat dipastikan. Penafsiran yang dipakai di sini:

    Previous_Incidents_Last30Days
        Jumlah incident yang TERKONFIRMASI (server_decision = CONFIRMED)
        pada 30 hari terakhir di device tersebut. Alasan: "incident" pada
        konteks kerawanan wajar diartikan sebagai kejadian nyata, bukan
        laporan yang ternyata false alarm.

    Emergency_Call_Last30Days
        Jumlah SELURUH laporan darurat yang masuk (apa pun keputusannya)
        pada 30 hari terakhir. Alasan: "call" adalah panggilan masuk,
        terlepas dari hasil verifikasi.

Dengan definisi ini selalu berlaku:
    Emergency_Call_Last30Days >= Previous_Incidents_Last30Days

Penafsiran ini didokumentasikan supaya dapat dikoreksi bila definisi asli
dataset diketahui kemudian.
"""

from datetime import timedelta

from backend.models import Incident, utcnow

# Jendela waktu mengikuti nama fitur pada model (Last30Days).
WINDOW_DAYS = 30


def get_history(device_id: str) -> dict:
    """Hitung riwayat 30 hari terakhir untuk satu device.

    Return dict dengan kunci:
        previous_incidents_last30days : int | None
        emergency_call_last30days     : int | None
        history_score                 : float 0.0-1.0
        confirmed / false_alarm / total : rincian angka
        status                        : REAL_OWN_DATABASE | ERROR
        source                        : penanda asal data

    Tidak melempar exception; kegagalan database dilaporkan lewat `status`.
    """
    try:
        since = utcnow() - timedelta(days=WINDOW_DAYS)

        semua = Incident.query.filter(
            Incident.device_id == device_id,
            Incident.created_at >= since,
        ).all()

        total = len(semua)
        confirmed = sum(
            1 for item in semua if item.server_decision == "CONFIRMED"
        )
        false_alarm = sum(
            1 for item in semua if item.server_decision == "FALSE_ALARM"
        )

        # history_score memakai Laplace smoothing supaya satu kejadian tidak
        # langsung membuat skor 0.0 atau 1.0. Hanya menghitung laporan yang
        # sudah punya keputusan akhir.
        berkeputusan = confirmed + false_alarm
        if berkeputusan == 0:
            history_score = 0.5  # netral, belum ada rekam jejak
        else:
            history_score = round((confirmed + 1) / (berkeputusan + 2), 2)

        return {
            "previous_incidents_last30days": confirmed,
            "emergency_call_last30days": total,
            "history_score": history_score,
            "confirmed": confirmed,
            "false_alarm": false_alarm,
            "total": total,
            "window_days": WINDOW_DAYS,
            "status": "REAL_OWN_DATABASE",
            "source": "ASEPJAGA_DB",
        }

    except Exception as error:  # noqa: BLE001 - jangan sampai crash server
        return {
            "previous_incidents_last30days": None,
            "emergency_call_last30days": None,
            "history_score": 0.5,
            "confirmed": None,
            "false_alarm": None,
            "total": None,
            "window_days": WINDOW_DAYS,
            "status": "ERROR",
            "source": "ERROR",
            "message": f"{type(error).__name__}: {error}",
        }
