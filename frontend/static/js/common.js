/* Helper bersama untuk seluruh halaman dashboard ASEP-JAGA.
   Dimuat lewat base.html sebelum script khusus tiap halaman. */

/* --- Pemanggilan API --------------------------------------------------- */

/* Server membungkus respons sebagai {success: true, data: {...}}.
   Helper di bawah membuka bungkus itu, sehingga halaman cukup membaca
   isi data-nya saja. */

function unwrap(body) {
  if (!body || body.success !== true) {
    const pesan = (body && body.error) || 'Respons server tidak dikenali.';
    throw new Error(pesan);
  }
  return body.data;
}

async function apiGet(url) {
  let response;
  try {
    response = await fetch(url, { headers: { 'Accept': 'application/json' } });
  } catch (error) {
    setServerStatus(false);
    throw new Error('Tidak dapat menghubungi server.');
  }

  const body = await response.json().catch(() => null);
  setServerStatus(true);
  return unwrap(body);
}

async function apiPost(url, payload) {
  let response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(payload || {}),
    });
  } catch (error) {
    setServerStatus(false);
    throw new Error('Tidak dapat menghubungi server.');
  }

  const body = await response.json().catch(() => null);
  setServerStatus(true);
  return unwrap(body);
}

/* --- Aksi operator ----------------------------------------------------- */

/* Aksi operator (confirm, false-alarm, close, dispatch) dan perubahan
   konfigurasi device memerlukan header X-Operator-Key.

   Kunci TIDAK ditulis di dalam file JavaScript ini. File ini dilayani sebagai
   static asset dan dapat dibaca siapa pun yang membuka dashboard, jadi
   menaruh secret di sini sama dengan mempublikasikannya.

   Selama sistem belum memiliki login operator, kunci diminta kepada operator
   saat pertama kali melakukan aksi, lalu disimpan di sessionStorage: hilang
   ketika tab ditutup, dan tidak pernah ikut ter-commit ke repositori.

   Ini solusi sementara untuk prototype, bukan pengganti sesi login. Kunci
   masih dapat dibaca lewat devtools oleh orang yang memakai komputer operator,
   dan tanpa HTTPS masih terbaca di jaringan. */

const OPERATOR_KEY_STORAGE = 'asepjaga.operatorKey';

function getOperatorKey() {
  return window.sessionStorage.getItem(OPERATOR_KEY_STORAGE) || '';
}

function setOperatorKey(nilai) {
  if (nilai) {
    window.sessionStorage.setItem(OPERATOR_KEY_STORAGE, nilai);
  } else {
    window.sessionStorage.removeItem(OPERATOR_KEY_STORAGE);
  }
  perbaruiIndikatorOperator();
}

/** Minta kunci operator bila belum ada di sesi ini. */
function mintaOperatorKey() {
  const tersimpan = getOperatorKey();
  if (tersimpan) return tersimpan;

  const masukan = window.prompt(
    'Masukkan Operator Key (DEVICE_CONFIG_API_KEY dari .env server).\n' +
    'Kunci disimpan hanya selama tab ini terbuka.'
  );
  if (!masukan) return '';

  setOperatorKey(masukan.trim());
  return getOperatorKey();
}

/** POST untuk aksi operator: menyertakan X-Operator-Key.
 *
 *  Bila server menolak (401 tanpa header, 403 kunci salah), kunci yang
 *  tersimpan dihapus supaya operator dapat memasukkan ulang, dan pesan
 *  server ditampilkan apa adanya. */
async function apiPostOperator(url, payload) {
  const kunci = mintaOperatorKey();
  if (!kunci) {
    throw new Error('Aksi dibatalkan: Operator Key belum dimasukkan.');
  }

  let response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-Operator-Key': kunci,
      },
      body: JSON.stringify(payload || {}),
    });
  } catch (error) {
    setServerStatus(false);
    throw new Error('Tidak dapat menghubungi server.');
  }

  const body = await response.json().catch(() => null);
  setServerStatus(true);

  if (response.status === 401 || response.status === 403) {
    setOperatorKey('');
    throw new Error(
      ((body && body.error) || 'Operator Key ditolak.') +
      ' Masukkan kunci yang benar lalu ulangi aksi.'
    );
  }
  if (response.status === 500 && body && body.error &&
      body.error.indexOf('DEVICE_CONFIG_API_KEY') !== -1) {
    throw new Error(body.error);
  }

  return unwrap(body);
}

/** PUT untuk konfigurasi device (memakai kunci operator yang sama). */
async function apiPutOperator(url, payload) {
  const kunci = mintaOperatorKey();
  if (!kunci) {
    throw new Error('Aksi dibatalkan: Operator Key belum dimasukkan.');
  }

  let response;
  try {
    response = await fetch(url, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-Operator-Key': kunci,
      },
      body: JSON.stringify(payload || {}),
    });
  } catch (error) {
    setServerStatus(false);
    throw new Error('Tidak dapat menghubungi server.');
  }

  const body = await response.json().catch(() => null);
  setServerStatus(true);

  if (response.status === 401 || response.status === 403) {
    setOperatorKey('');
    throw new Error(
      ((body && body.error) || 'Operator Key ditolak.') +
      ' Masukkan kunci yang benar lalu ulangi aksi.'
    );
  }

  return unwrap(body);
}

/* Indikator kecil di bilah atas: memberi tahu apakah kunci operator sudah
   dimasukkan pada sesi ini. Yang ditampilkan hanya ADA/TIDAK, bukan nilainya. */
function perbaruiIndikatorOperator() {
  const wadah = document.getElementById('operatorKeyState');
  if (!wadah) return;

  const ada = Boolean(getOperatorKey());
  wadah.innerHTML = ada
    ? '<span class="badge badge-ok">operator key aktif</span>'
    : '<span class="badge badge-muted">operator key belum diisi</span>';
}

/* --- Keamanan tampilan ------------------------------------------------- */

/** Loloskan karakter HTML sebelum disisipkan lewat innerHTML.
 *  Semua nilai dari server harus melewati fungsi ini. */
function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/* --- Format waktu & angka ---------------------------------------------- */

/** Waktu lokal ringkas. Server mengirim ISO 8601 dengan offset. */
function formatTime(value) {
  if (!value) return '<span class="muted">-</span>';

  const waktu = new Date(value);
  if (isNaN(waktu.getTime())) return escapeHtml(value);

  const tanggal = waktu.toLocaleDateString('id-ID', {
    day: '2-digit', month: 'short',
  });
  const jam = waktu.toLocaleTimeString('id-ID', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });

  return tanggal + ' ' + jam;
}

/** Selisih waktu dalam bahasa sehari-hari, misalnya "12 detik lalu". */
function timeAgo(value) {
  if (!value) return '<span class="muted">belum pernah</span>';

  const waktu = new Date(value);
  if (isNaN(waktu.getTime())) return escapeHtml(value);

  const detik = Math.floor((Date.now() - waktu.getTime()) / 1000);

  if (detik < 0) return 'baru saja';
  if (detik < 60) return detik + ' detik lalu';
  if (detik < 3600) return Math.floor(detik / 60) + ' menit lalu';
  if (detik < 86400) return Math.floor(detik / 3600) + ' jam lalu';
  return Math.floor(detik / 86400) + ' hari lalu';
}

/** Angka 0.0-1.0 menjadi persen. */
function formatPercent(value) {
  if (value === null || value === undefined) return '-';
  return (value * 100).toFixed(0) + '%';
}

/** Sel tabel berisi persen keyakinan audio beserta bar kecil. */
function confidenceCell(value) {
  if (value === null || value === undefined) {
    return '<span class="muted">-</span>';
  }

  // Lebar bar dibatasi 0-100 agar nilai di luar dugaan tidak merusak tata letak.
  const persen = Math.max(0, Math.min(100, value * 100));

  return '<div>' + formatPercent(value) + '</div>' +
    '<div class="conf-bar"><i style="width:' + persen.toFixed(0) + '%"></i></div>';
}

/* --- Badge status ------------------------------------------------------ */

// Warna badge per nilai status. Nilai yang tidak terdaftar memakai gaya netral.
const BADGE_STYLES = {
  // Verifikasi & keputusan
  'CONFIRMED': 'badge-danger',
  'FALSE_ALARM': 'badge-muted',
  'PENDING': 'badge-warn',
  'LOCAL_VERIFIED': 'badge-ok',
  'LOCAL_REJECTED': 'badge-muted',
  // Status incident
  'DISPATCHED': 'badge-warn',
  'CLOSED': 'badge-muted',
  'ACTIVE': 'badge-danger',
  // Status perangkat
  'ONLINE': 'badge-ok',
  'OFFLINE': 'badge-muted',
  // Command
  'EMERGENCY_CONFIRMED': 'badge-danger',
  'CLEAR_EMERGENCY': 'badge-info',
  'SENT': 'badge-info',
  'ACKNOWLEDGED': 'badge-ok',
  'CLEARED': 'badge-muted',
  'NONE': 'badge-muted',
};

function badge(value) {
  if (!value) return '<span class="muted">-</span>';

  const teks = String(value);
  const gaya = BADGE_STYLES[teks.toUpperCase()] || 'badge-info';

  return '<span class="badge ' + gaya + '">' + escapeHtml(teks) + '</span>';
}

/* --- Indikator koneksi server ----------------------------------------- */

function setServerStatus(online) {
  const dot = document.getElementById('serverDot');
  const text = document.getElementById('serverText');
  if (!dot || !text) return;

  dot.className = 'dot ' + (online ? 'online' : 'offline');
  text.textContent = online ? 'server terhubung' : 'server tidak terjangkau';
}

/* --- Siklus polling ---------------------------------------------------- */

/** Jalankan fungsi sekarang lalu berulang setiap `interval` milidetik.
 *  Kegagalan satu siklus tidak menghentikan siklus berikutnya. */
function startPolling(fungsi, interval) {
  let sedangJalan = false;

  const jalankan = async () => {
    // Lewati bila siklus sebelumnya belum selesai, supaya permintaan
    // tidak menumpuk saat server lambat.
    if (sedangJalan) return;

    sedangJalan = true;
    try {
      await fungsi();
    } catch (error) {
      console.error('Gagal menyegarkan data:', error.message);
    } finally {
      sedangJalan = false;
    }
  };

  jalankan();
  return setInterval(jalankan, interval);
}

/* --- Navigasi & jam --------------------------------------------------- */

document.addEventListener('DOMContentLoaded', () => {
  // Indikator kunci operator dan tombol untuk melupakannya.
  perbaruiIndikatorOperator();

  const tombolLupakan = document.getElementById('btnLupakanOperatorKey');
  if (tombolLupakan) {
    tombolLupakan.addEventListener('click', () => {
      setOperatorKey('');
    });
  }

  // Tandai menu yang sedang dibuka.
  const halaman = window.location.pathname.split('/')[1] || 'dashboard';
  const menu = document.querySelector('.nav a[data-nav="' + halaman + '"]');
  if (menu) menu.classList.add('active');

  // Jam pada bilah atas.
  const clock = document.getElementById('clock');
  if (clock) {
    const perbaruiJam = () => {
      clock.textContent = new Date().toLocaleTimeString('id-ID', {
        hour: '2-digit', minute: '2-digit', second: '2-digit',
      });
    };
    perbaruiJam();
    setInterval(perbaruiJam, 1000);
  }
});
