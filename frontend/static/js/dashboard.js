/* Dashboard ASEP-JAGA: statistik, peta, emergency aktif, status perangkat.
   Data diambil berkala lewat fetch() tanpa reload halaman. */

let map = null;
let markerLayer = null;
let mapSudahDiposisikan = false;

/* --- Peta ------------------------------------------------------------- */

function initMap() {
  // Leaflet dimuat dari CDN. Bila tidak ada internet, bagian lain
  // dashboard tetap jalan.
  if (typeof L === 'undefined') {
    document.getElementById('map').innerHTML =
      '<div class="empty">Leaflet tidak dapat dimuat (perlu koneksi internet). ' +
      'Bagian dashboard lainnya tetap berfungsi.</div>';
    return;
  }

  // Tampilan awal: Bandung.
  map = L.map('map').setView([-6.9175, 107.6191], 13);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map);

  markerLayer = L.layerGroup().addTo(map);
}

/** Gambar ulang penanda perangkat pada peta. */
function renderMap(devices, emergencyDeviceIds) {
  if (!map || !markerLayer) return;

  markerLayer.clearLayers();
  const koordinat = [];

  devices.forEach((device) => {
    if (device.latitude === null || device.longitude === null) return;

    const emergency = emergencyDeviceIds.has(device.device_id);
    const warna = emergency ? '#f85149' : (device.online ? '#2ea043' : '#8b9bb0');

    const marker = L.circleMarker([device.latitude, device.longitude], {
      radius: emergency ? 12 : 8,
      color: warna,
      fillColor: warna,
      fillOpacity: 0.75,
      weight: emergency ? 3 : 1,
    });

    marker.bindPopup(
      '<strong>' + escapeHtml(device.device_id) + '</strong><br>' +
      escapeHtml(device.location || '-') + '<br>' +
      'Status: ' + (device.online ? 'ONLINE' : 'OFFLINE') + '<br>' +
      (emergency ? '<strong style="color:#c00">EMERGENCY AKTIF</strong>' : '')
    );

    marker.addTo(markerLayer);
    koordinat.push([device.latitude, device.longitude]);
  });

  // Peta diposisikan sekali saja supaya tidak melompat setiap polling.
  if (!mapSudahDiposisikan && koordinat.length > 0) {
    map.fitBounds(koordinat, { padding: [50, 50], maxZoom: 16 });
    mapSudahDiposisikan = true;
  }

  document.getElementById('mapNote').textContent =
    koordinat.length + ' dari ' + devices.length + ' perangkat memiliki koordinat';
}

/* --- Kartu statistik -------------------------------------------------- */

function renderStats(stats) {
  document.getElementById('statTotal').textContent = stats.total_devices;
  document.getElementById('statOnline').textContent = stats.online_devices;
  document.getElementById('statOffline').textContent = stats.offline_devices;
  document.getElementById('statActive').textContent = stats.active_emergencies;
  document.getElementById('statConfirmed').textContent = stats.confirmed_today;
  document.getElementById('statFalse').textContent = stats.false_alarms_today;
}

/* --- Banner emergency ------------------------------------------------- */

function renderEmergencyBanner(incidents) {
  const area = document.getElementById('emergencyArea');

  // Hanya kejadian yang benar-benar terkonfirmasi ditampilkan sebagai
  // banner besar.
  const penting = incidents.filter(
    (item) => item.server_decision === 'CONFIRMED' || item.status === 'DISPATCHED'
  );

  if (penting.length === 0) {
    area.innerHTML = '';
    return;
  }

  area.innerHTML = penting.map((incident) => (
    '<div class="emergency-banner">' +
      '<div class="title">&#9888; EMERGENCY ACTIVE</div>' +
      '<div class="fields">' +
        '<div><span>Device:</span> <strong>' + escapeHtml(incident.device_id) + '</strong></div>' +
        '<div><span>Location:</span> ' + escapeHtml(incident.device_location || '-') + '</div>' +
        '<div><span>Waktu:</span> ' + formatTime(incident.created_at) + '</div>' +
        '<div><span>Local Verification:</span> ' +
          (incident.local_decision === 'LOCAL_VERIFIED' ? 'VALID' : 'REJECTED') + '</div>' +
        '<div><span>Audio Confidence:</span> ' + formatPercent(incident.audio_confidence) + '</div>' +
        '<div><span>Server Verification:</span> ' + escapeHtml(incident.server_decision) + '</div>' +
        '<div><span>Status:</span> ' + escapeHtml(incident.status) + '</div>' +
        '<div><span>Incident:</span> <span class="mono">' + escapeHtml(incident.incident_id) + '</span></div>' +
      '</div>' +
      '<div class="actions btn-row">' +
        '<a class="btn btn-sm" href="/incidents/' + encodeURIComponent(incident.incident_id) + '">Detail</a>' +
        '<button class="btn btn-sm btn-warn" data-aksi="dispatch" data-id="' + escapeHtml(incident.incident_id) + '">Dispatch</button>' +
        '<button class="btn btn-sm btn-ok" data-aksi="close" data-id="' + escapeHtml(incident.incident_id) + '">Close</button>' +
        '<button class="btn btn-sm btn-danger" data-aksi="false-alarm" data-id="' + escapeHtml(incident.incident_id) + '">False Alarm</button>' +
      '</div>' +
    '</div>'
  )).join('');
}

/* --- Tabel emergency aktif -------------------------------------------- */

function renderActiveTable(incidents) {
  const body = document.getElementById('activeBody');

  if (incidents.length === 0) {
    body.innerHTML =
      '<tr><td colspan="9" class="empty">Tidak ada emergency aktif.</td></tr>';
    return;
  }

  body.innerHTML = incidents.map((incident) => (
    '<tr>' +
      '<td class="mono">' + escapeHtml(incident.device_id) + '</td>' +
      '<td>' + escapeHtml(incident.device_location || '-') + '</td>' +
      '<td class="nowrap">' + formatTime(incident.created_at) + '</td>' +
      '<td>' + (incident.sos ? badge('ACTIVE') : '<span class="muted">tidak</span>') + '</td>' +
      '<td>' + confidenceCell(incident.audio_confidence) + '</td>' +
      '<td>' + badge(incident.local_decision) + '</td>' +
      '<td>' + badge(incident.server_decision) + '</td>' +
      '<td>' + badge(incident.status) + '</td>' +
      '<td><a class="btn btn-sm" href="/incidents/' + encodeURIComponent(incident.incident_id) + '">Detail</a></td>' +
    '</tr>'
  )).join('');
}

/* --- Tabel perangkat -------------------------------------------------- */

function renderDeviceTable(devices) {
  const body = document.getElementById('deviceBody');

  if (devices.length === 0) {
    body.innerHTML =
      '<tr><td colspan="5" class="empty">Belum ada perangkat terdaftar. ' +
      'Jalankan simulator atau ESP32 untuk mendaftar.</td></tr>';
    return;
  }

  body.innerHTML = devices.map((device) => (
    '<tr>' +
      '<td class="mono">' + escapeHtml(device.device_id) + '</td>' +
      '<td>' + escapeHtml(device.location || '-') + '</td>' +
      '<td>' + badge(device.status) + '</td>' +
      '<td class="nowrap">' + timeAgo(device.last_seen) + '</td>' +
      '<td class="mono">' + escapeHtml(device.firmware_version) + '</td>' +
    '</tr>'
  )).join('');
}

/* --- Aksi operator ---------------------------------------------------- */

// Satu listener untuk seluruh tombol aksi (event delegation), supaya
// tombol yang dibuat ulang setiap polling tetap berfungsi.
document.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-aksi]');
  if (!button) return;

  const aksi = button.dataset.aksi;
  const incidentId = button.dataset.id;

  const konfirmasi = {
    'dispatch': 'Tandai petugas sudah dikirim ke lokasi?',
    'close': 'Tutup incident ini? Sirene dan strobe akan dimatikan.',
    'false-alarm': 'Tandai sebagai FALSE ALARM? Sirene dan strobe akan dimatikan.',
    'confirm': 'Konfirmasi incident ini sebagai emergency nyata?',
  }[aksi];

  if (konfirmasi && !window.confirm(konfirmasi)) return;

  button.disabled = true;
  try {
    await apiPostOperator('/api/incidents/' + encodeURIComponent(incidentId) + '/' + aksi, {});
    await refresh();
  } catch (error) {
    window.alert('Gagal menjalankan aksi: ' + error.message);
  } finally {
    button.disabled = false;
  }
});

/* --- Siklus penyegaran ------------------------------------------------ */

async function refresh() {
  // Tiga endpoint diambil bersamaan agar satu siklus lebih cepat.
  const [stats, incidentData, deviceData] = await Promise.all([
    apiGet('/api/statistics'),
    apiGet('/api/incidents?open=true&limit=50'),
    apiGet('/api/devices'),
  ]);

  const incidents = incidentData.incidents;
  const devices = deviceData.devices;

  renderStats(stats);
  renderEmergencyBanner(incidents);
  renderActiveTable(incidents);
  renderDeviceTable(devices);

  const emergencyDeviceIds = new Set(incidents.map((item) => item.device_id));
  renderMap(devices, emergencyDeviceIds);
}

document.addEventListener('DOMContentLoaded', () => {
  initMap();
  startPolling(refresh, 3000);
});
