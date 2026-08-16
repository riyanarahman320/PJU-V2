/* Halaman Incidents: daftar seluruh incident dengan filter status. */

/** Bangun query string sesuai pilihan filter. */
function buildQuery() {
  const pilihan = document.getElementById('filterStatus').value;
  if (pilihan === 'open') return '/api/incidents?open=true&limit=200';
  if (pilihan) return '/api/incidents?status=' + encodeURIComponent(pilihan) + '&limit=200';
  return '/api/incidents?limit=200';
}

/** Tombol aksi ditampilkan sesuai status incident.
 *  Incident yang sudah CLOSED tidak menampilkan tombol apa pun. */
function actionButtons(incident) {
  const id = escapeHtml(incident.incident_id);
  const detail = '<a class="btn btn-sm" href="/incidents/' +
    encodeURIComponent(incident.incident_id) + '">Detail</a>';

  if (incident.status === 'CLOSED') return detail;

  if (incident.status === 'FALSE_ALARM') {
    // Operator masih dapat mengoreksi keputusan otomatis.
    return detail +
      ' <button class="btn btn-sm btn-danger" data-aksi="confirm" data-id="' + id + '">Konfirmasi</button>';
  }

  return detail +
    ' <button class="btn btn-sm btn-warn" data-aksi="dispatch" data-id="' + id + '">Dispatch</button>' +
    ' <button class="btn btn-sm btn-ok" data-aksi="close" data-id="' + id + '">Close</button>';
}

function renderRows(incidents) {
  const body = document.getElementById('incidentBody');

  if (incidents.length === 0) {
    body.innerHTML =
      '<tr><td colspan="11" class="empty">Belum ada incident yang sesuai filter.</td></tr>';
    return;
  }

  body.innerHTML = incidents.map((incident) => (
    '<tr>' +
      '<td class="mono">' + escapeHtml(incident.incident_id) + '</td>' +
      '<td class="mono">' + escapeHtml(incident.device_id) + '</td>' +
      '<td>' + escapeHtml(incident.device_location || '-') + '</td>' +
      '<td class="nowrap">' + formatTime(incident.created_at) + '</td>' +
      '<td>' + (incident.sos ? 'ya' : '<span class="muted">tidak</span>') + '</td>' +
      '<td>' + escapeHtml(incident.audio_class) + ' ' +
        '<span class="muted">(' + formatPercent(incident.audio_confidence) + ')</span></td>' +
      '<td>' + badge(incident.local_decision) + '</td>' +
      '<td>' + badge(incident.server_decision) + '</td>' +
      '<td class="mono">' +
        (incident.server_score === null ? '-' : incident.server_score.toFixed(2)) + '</td>' +
      '<td>' + badge(incident.status) + '</td>' +
      '<td class="nowrap">' + actionButtons(incident) + '</td>' +
    '</tr>'
  )).join('');
}

async function refresh() {
  const data = await apiGet(buildQuery());
  renderRows(data.incidents);
}

/* Aksi operator (event delegation supaya tetap bekerja setelah render ulang) */
document.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-aksi]');
  if (!button) return;

  const aksi = button.dataset.aksi;
  const incidentId = button.dataset.id;

  const konfirmasi = {
    'dispatch': 'Tandai petugas sudah dikirim?',
    'close': 'Tutup incident ini? Sirene dan strobe akan dimatikan.',
    'confirm': 'Konfirmasi incident ini sebagai emergency nyata? Sirene akan diaktifkan.',
  }[aksi];

  if (konfirmasi && !window.confirm(konfirmasi)) return;

  button.disabled = true;
  try {
    await apiPostOperator('/api/incidents/' + encodeURIComponent(incidentId) + '/' + aksi, {});
    await refresh();
  } catch (error) {
    window.alert('Gagal: ' + error.message);
  } finally {
    button.disabled = false;
  }
});

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('filterStatus').addEventListener('change', refresh);
  document.getElementById('btnRefresh').addEventListener('click', refresh);
  startPolling(refresh, 3000);
});
