/* Halaman History: incident yang sudah selesai dan log sistem. */

// Daftar device untuk dropdown filter; diisi sekali agar pilihan
// pengguna tidak hilang setiap penyegaran.
let daftarDeviceTerisi = false;

/* --- Dropdown filter device ------------------------------------------- */

async function isiFilterDevice() {
  if (daftarDeviceTerisi) return;

  const data = await apiGet('/api/devices');
  const select = document.getElementById('filterDevice');

  data.devices.forEach((device) => {
    const option = document.createElement('option');
    option.value = device.device_id;
    option.textContent = device.device_id +
      (device.location ? ' — ' + device.location : '');
    select.appendChild(option);
  });

  daftarDeviceTerisi = true;
}

/* --- Query string ----------------------------------------------------- */

function buildHistoryQuery() {
  const params = new URLSearchParams({ limit: '200' });

  const device = document.getElementById('filterDevice').value;
  const decision = document.getElementById('filterDecision').value;

  if (device) params.set('device_id', device);
  if (decision) params.set('decision', decision);

  return '/api/history?' + params.toString();
}

function buildLogQuery() {
  const params = new URLSearchParams({ limit: '100' });

  // Log mengikuti filter device supaya sejalan dengan tabel di atasnya.
  const device = document.getElementById('filterDevice').value;
  if (device) params.set('device_id', device);

  return '/api/logs?' + params.toString();
}

/* --- Tabel riwayat ---------------------------------------------------- */

function renderHistory(incidents) {
  const body = document.getElementById('historyBody');

  if (incidents.length === 0) {
    body.innerHTML =
      '<tr><td colspan="11" class="empty">Belum ada incident yang selesai ' +
      'sesuai filter ini.</td></tr>';
    return;
  }

  body.innerHTML = incidents.map((incident) => {
    // closed_at diisi saat ditutup; FALSE_ALARM otomatis bisa belum punya nilai.
    const selesai = incident.closed_at || incident.confirmed_at;

    return (
      '<tr>' +
        '<td class="mono">' + escapeHtml(incident.incident_id) + '</td>' +
        '<td class="mono">' + escapeHtml(incident.device_id) + '</td>' +
        '<td>' + escapeHtml(incident.device_location || '-') + '</td>' +
        '<td class="nowrap">' + formatTime(incident.created_at) + '</td>' +
        '<td class="nowrap">' + formatTime(selesai) + '</td>' +
        '<td>' + escapeHtml(incident.audio_class) +
          ' <span class="muted">(' + formatPercent(incident.audio_confidence) + ')</span></td>' +
        '<td>' + badge(incident.local_decision) + '</td>' +
        '<td>' + badge(incident.server_decision) + '</td>' +
        '<td class="mono">' +
          (incident.server_score === null ? '-' : incident.server_score.toFixed(2)) + '</td>' +
        '<td>' + badge(incident.status) + '</td>' +
        '<td><a class="btn btn-sm" href="/incidents/' +
          encodeURIComponent(incident.incident_id) + '">Detail</a></td>' +
      '</tr>'
    );
  }).join('');
}

/* --- Tabel log -------------------------------------------------------- */

function renderLogs(logs) {
  const body = document.getElementById('logBody');
  document.getElementById('logCount').textContent = logs.length + ' baris terakhir';

  if (logs.length === 0) {
    body.innerHTML = '<tr><td colspan="4" class="empty">Belum ada log.</td></tr>';
    return;
  }

  body.innerHTML = logs.map((log) => (
    '<tr>' +
      '<td class="nowrap">' + formatTime(log.created_at) + '</td>' +
      '<td class="mono">' + escapeHtml(log.device_id || '-') + '</td>' +
      '<td class="mono">' + escapeHtml(log.event_type) + '</td>' +
      '<td>' + escapeHtml(log.message) + '</td>' +
    '</tr>'
  )).join('');
}

/* --- Siklus penyegaran ------------------------------------------------ */

async function refresh() {
  await isiFilterDevice();

  const [historyData, logData] = await Promise.all([
    apiGet(buildHistoryQuery()),
    apiGet(buildLogQuery()),
  ]);

  renderHistory(historyData.history);
  renderLogs(logData.logs);
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('filterDevice').addEventListener('change', refresh);
  document.getElementById('filterDecision').addEventListener('change', refresh);
  document.getElementById('btnRefresh').addEventListener('click', refresh);

  // Riwayat tidak berubah secepat dashboard, jadi interval lebih panjang.
  startPolling(refresh, 10000);
});
