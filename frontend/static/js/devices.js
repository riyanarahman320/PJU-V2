/* Halaman Devices: daftar perangkat, status online, dan riwayat command.

   Catatan: endpoint clear command (POST /api/device/<id>/command/clear)
   dilindungi API key perangkat, sehingga tidak dipanggil dari dashboard.
   Pembatalan command dilakukan lewat aksi incident (Close / False Alarm). */

// Device yang riwayat command-nya sedang dibuka (null bila panel tertutup).
let deviceCommandTerbuka = null;

/* --- Tabel perangkat -------------------------------------------------- */

/* Ringkas keadaan konfigurasi konteks sebuah device.

   Kolom ini ada supaya operator tahu titik PJU mana yang belum dapat
   diprediksi hotspot-nya. Tanpa penanda ini, hotspot yang kosong terlihat
   seperti "tidak ada risiko", padahal sebenarnya model belum pernah
   dipanggil untuk titik tersebut. */
function configCell(device) {
  const config = device.context_config || {};

  if (device.rf_config_complete) {
    return '<span class="badge badge-ok">LENGKAP</span>';
  }

  // Population_Density diperlakukan khusus: nilainya belum tersedia untuk
  // seluruh device produksi, dan tidak boleh diisi angka karangan karena
  // pipeline tidak memakai scaler.
  const densityKosong = config.population_density === null ||
    config.population_density === undefined;

  const kurang = [];
  ['village', 'road_type', 'area_type', 'nearby_cctv', 'nearby_police_post',
   'public_event', 'holiday'].forEach((nama) => {
    if (!config[nama]) kurang.push(nama);
  });

  const bagian = [];
  if (densityKosong) {
    bagian.push(
      '<div><span class="badge badge-warn">POPULASI BELUM TERSEDIA</span></div>'
    );
  }
  if (kurang.length > 0) {
    bagian.push(
      '<div class="muted" style="font-size:11px">belum diisi: ' +
      escapeHtml(kurang.join(', ')) + '</div>'
    );
  }
  if (bagian.length === 0) {
    bagian.push('<span class="badge badge-warn">BELUM LENGKAP</span>');
  }

  bagian.push(
    '<div class="muted" style="font-size:11px">hotspot: MISSING_FEATURES</div>'
  );

  return bagian.join('');
}

/* Keadaan sensor tamper sebuah device.

   Dua hal ditampilkan terpisah dan itu disengaja:

     tamper        -> kotak SEDANG terbuka (perlu tindakan sekarang)
     ever_tampered -> kotak PERNAH dibuka (jejak, walau sudah ditutup)

   Menutup kotak kembali tidak menghapus fakta bahwa ia pernah dibuka, jadi
   penanda kedua tetap muncul. Tanpa itu, pelaku yang membuka lalu menutup
   kotak akan hilang dari pandangan operator. */
function tamperCell(device) {
  const state = device.tamper_state || {};

  if (state.tamper) {
    const bagian = [
      '<div><span class="badge badge-danger">KOTAK TERBUKA</span></div>',
    ];
    if (state.tamper_since) {
      bagian.push(
        '<div class="muted" style="font-size:11px">sejak ' +
        timeAgo(state.tamper_since) + '</div>'
      );
    }
    return bagian.join('');
  }

  if (state.ever_tampered) {
    return (
      '<div><span class="badge badge-warn">PERNAH DIBONGKAR</span></div>' +
      '<div class="muted" style="font-size:11px">laporan terakhir ' +
      timeAgo(state.tamper_last_report) + '</div>'
    );
  }

  // Belum pernah ada laporan sama sekali. Ini TIDAK sama dengan "aman":
  // firmware lama tidak mengirim field tamper, jadi keadaannya tidak
  // diketahui, bukan terbukti utuh.
  return '<span class="muted">tidak ada laporan</span>';
}

function renderDevices(devices, incidentByDevice) {
  const body = document.getElementById('deviceBody');

  if (devices.length === 0) {
    body.innerHTML =
      '<tr><td colspan="11" class="empty">Belum ada perangkat terdaftar. ' +
      'Jalankan <span class="mono">simulation/simulator.py</span> atau ESP32 untuk mendaftar.</td></tr>';
    return;
  }

  body.innerHTML = devices.map((device) => {
    const koordinat = (device.latitude !== null && device.longitude !== null)
      ? device.latitude.toFixed(5) + ', ' + device.longitude.toFixed(5)
      : '<span class="muted">-</span>';

    const incidentId = incidentByDevice.get(device.device_id);
    const incidentCell = incidentId
      ? '<a class="mono" href="/incidents/' + encodeURIComponent(incidentId) + '">' +
        escapeHtml(incidentId) + '</a>'
      : '<span class="muted">-</span>';

    const id = escapeHtml(device.device_id);

    return (
      '<tr>' +
        '<td class="mono">' + id + '</td>' +
        '<td>' + escapeHtml(device.name || '-') + '</td>' +
        '<td>' + escapeHtml(device.location || '-') + '</td>' +
        '<td class="mono nowrap">' + koordinat + '</td>' +
        '<td>' + badge(device.status) + '</td>' +
        '<td class="nowrap">' + timeAgo(device.last_seen) +
          '<div class="muted" style="font-size:11px">' + formatTime(device.last_seen) + '</div></td>' +
        '<td class="mono">' + escapeHtml(device.firmware_version) + '</td>' +
        '<td>' + tamperCell(device) + '</td>' +
        '<td>' + configCell(device) + '</td>' +
        '<td>' + incidentCell + '</td>' +
        '<td class="nowrap">' +
          '<button class="btn btn-sm" data-commands="' + id + '">Command</button>' +
        '</td>' +
      '</tr>'
    );
  }).join('');
}

/* --- Riwayat command per perangkat ------------------------------------ */

function boolCell(value) {
  return value
    ? '<span class="badge badge-ok">ON</span>'
    : '<span class="muted">off</span>';
}

async function tampilkanCommand(deviceId) {
  deviceCommandTerbuka = deviceId;

  const data = await apiGet(
    '/api/device/' + encodeURIComponent(deviceId) + '/commands'
  );

  document.getElementById('commandDeviceId').textContent = deviceId;
  document.getElementById('commandPanel').style.display = '';

  const body = document.getElementById('commandBody');

  if (data.commands.length === 0) {
    body.innerHTML =
      '<tr><td colspan="8" class="empty">Belum ada command untuk perangkat ini.</td></tr>';
    return;
  }

  body.innerHTML = data.commands.map((command) => (
    '<tr>' +
      '<td class="mono">' + command.id + '</td>' +
      '<td>' + badge(command.command) + '</td>' +
      '<td>' + boolCell(command.strobe) + '</td>' +
      '<td>' + boolCell(command.siren) + '</td>' +
      '<td>' + boolCell(command.speaker) + '</td>' +
      '<td>' + badge(command.status) + '</td>' +
      '<td>' + (command.incident_id
        ? '<a class="mono" href="/incidents/' + encodeURIComponent(command.incident_id) + '">' +
          escapeHtml(command.incident_id) + '</a>'
        : '<span class="muted">-</span>') + '</td>' +
      '<td class="nowrap">' + formatTime(command.created_at) + '</td>' +
    '</tr>'
  )).join('');
}

document.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-commands]');
  if (!button) return;

  button.disabled = true;
  try {
    await tampilkanCommand(button.dataset.commands);
  } catch (error) {
    window.alert('Gagal memuat command: ' + error.message);
  } finally {
    button.disabled = false;
  }
});

/* --- Siklus penyegaran ------------------------------------------------ */

async function refresh() {
  const [deviceData, incidentData, health] = await Promise.all([
    apiGet('/api/devices'),
    apiGet('/api/incidents?open=true&limit=200'),
    apiGet('/api/health'),
  ]);

  // Peta device_id -> incident aktif, supaya kolom incident dapat diisi.
  const incidentByDevice = new Map();
  incidentData.incidents.forEach((incident) => {
    if (!incidentByDevice.has(incident.device_id)) {
      incidentByDevice.set(incident.device_id, incident.incident_id);
    }
  });

  document.getElementById('timeoutInfo').textContent =
    health.device_offline_timeout + ' detik';

  renderDevices(deviceData.devices, incidentByDevice);

  // Jaga panel command tetap mutakhir bila sedang terbuka.
  if (deviceCommandTerbuka) {
    await tampilkanCommand(deviceCommandTerbuka);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('btnRefresh').addEventListener('click', refresh);

  document.getElementById('btnCloseCommands').addEventListener('click', () => {
    deviceCommandTerbuka = null;
    document.getElementById('commandPanel').style.display = 'none';
  });

  startPolling(refresh, 3000);
});
