/* Halaman detail incident: menampilkan alur verifikasi dua tahap,
   data konteks, command, dan log. */

const INCIDENT_ID = document.getElementById('incidentRoot').dataset.incidentId;

/* --- Alur verifikasi -------------------------------------------------- */

/** Susun langkah-langkah alur sesuai keadaan incident.
 *  Setiap langkah punya keadaan: done / active / skip. */
function buildFlow(incident, commands) {
  const lokalValid = incident.local_decision === 'LOCAL_VERIFIED';
  const serverConfirmed = incident.server_decision === 'CONFIRMED';
  const commandTerkirim = commands.some(
    (item) => item.command === 'EMERGENCY_CONFIRMED' &&
              (item.status === 'SENT' || item.status === 'ACKNOWLEDGED')
  );
  const commandAck = commands.some(
    (item) => item.command === 'EMERGENCY_CONFIRMED' && item.status === 'ACKNOWLEDGED'
  );

  return [
    {
      state: incident.sos ? 'done' : 'skip',
      title: 'SOS',
      detail: incident.sos
        ? 'Tombol SOS ditekan di perangkat.'
        : 'Tombol SOS tidak ditekan (kejadian terdeteksi dari audio).',
    },
    {
      state: 'done',
      title: 'LOCAL AUDIO AI',
      detail: 'Kelas audio: ' + escapeHtml(incident.audio_class) +
              ' — keyakinan ' + formatPercent(incident.audio_confidence) +
              '. (Diproses di perangkat.)',
    },
    {
      state: lokalValid ? 'done' : 'skip',
      title: 'LOCAL VERIFICATION',
      detail: lokalValid
        ? 'LOCAL_VERIFIED — perangkat menilai kejadian ini valid.'
        : 'LOCAL_REJECTED — perangkat menolak, tidak dilanjutkan.',
    },
    {
      state: lokalValid ? 'done' : 'skip',
      title: 'STROBE',
      detail: lokalValid
        ? 'Strobe dinyalakan langsung oleh perangkat, tanpa menunggu server (fail-safe lokal).'
        : 'Strobe tidak dinyalakan.',
    },
    {
      state: incident.server_decision === 'PENDING' ? 'active' : 'done',
      title: 'SERVER VERIFICATION',
      detail: 'Verifikasi tahap 2 (rule-based) menghasilkan skor ' +
              (incident.server_score === null ? '-' : incident.server_score.toFixed(2)) + '.',
    },
    {
      state: serverConfirmed ? 'active' : 'skip',
      title: 'DECISION: ' + escapeHtml(incident.server_decision),
      detail: serverConfirmed
        ? 'Kejadian dianggap nyata; respons penuh diaktifkan.'
        : 'Tidak ada aktivasi respons penuh.',
    },
    {
      state: commandTerkirim ? 'done' : (serverConfirmed ? 'active' : 'skip'),
      title: 'COMMAND',
      detail: serverConfirmed
        ? (commandAck
            ? 'Perangkat sudah menjalankan command: sirene dan speaker aktif.'
            : (commandTerkirim
                ? 'Command sudah diambil perangkat, menunggu konfirmasi eksekusi.'
                : 'Command EMERGENCY_CONFIRMED menunggu diambil perangkat.'))
        : 'Tidak ada command emergency yang dibuat.',
    },
  ];
}

function renderFlow(incident, commands) {
  const langkah = buildFlow(incident, commands);

  document.getElementById('flowArea').innerHTML = langkah.map((step, index) => (
    '<div class="flow-step ' + step.state + '">' +
      '<div class="flow-marker">' +
        '<div class="circle">' + (index + 1) + '</div>' +
        '<div class="line"></div>' +
      '</div>' +
      '<div class="flow-content">' +
        '<div class="step-title">' + step.title + '</div>' +
        '<div class="step-detail">' + step.detail + '</div>' +
      '</div>' +
    '</div>'
  )).join('');
}

/* --- Ringkasan & konteks ---------------------------------------------- */

function kv(label, value) {
  return '<div><div class="k">' + label + '</div><div class="v">' + value + '</div></div>';
}

function renderSummary(incident) {
  document.getElementById('statusBadge').innerHTML = badge(incident.status);

  const koordinat = (incident.latitude !== null && incident.longitude !== null)
    ? incident.latitude.toFixed(5) + ', ' + incident.longitude.toFixed(5)
    : '-';

  document.getElementById('summaryArea').innerHTML =
    kv('Device', '<span class="mono">' + escapeHtml(incident.device_id) + '</span>') +
    kv('Nama Device', escapeHtml(incident.device_name || '-')) +
    kv('Lokasi', escapeHtml(incident.device_location || '-')) +
    kv('Koordinat', '<span class="mono">' + koordinat + '</span>') +
    kv('SOS', incident.sos ? 'ya' : 'tidak') +
    kv('Audio', escapeHtml(incident.audio_class) + ' (' + formatPercent(incident.audio_confidence) + ')') +
    kv('Local Verification', badge(incident.local_decision)) +
    kv('Server Verification', badge(incident.server_decision)) +
    kv('Skor Server', incident.server_score === null ? '-' : incident.server_score.toFixed(3)) +
    kv('Dibuat', formatTime(incident.created_at)) +
    kv('Dikonfirmasi', formatTime(incident.confirmed_at)) +
    kv('Ditutup', formatTime(incident.closed_at));
}

function renderContext(context) {
  document.getElementById('contextArea').innerHTML =
    kv('Hotspot Risk', context.hotspot_risk === null ? '-' : context.hotspot_risk.toFixed(2)) +
    kv('Weather', escapeHtml(context.weather || '-')) +
    kv('Traffic', escapeHtml(context.traffic || '-')) +
    kv('History Score', context.history_score === null ? '-' : context.history_score.toFixed(2));
}

/* --- Command & log ---------------------------------------------------- */

function boolCell(value) {
  return value
    ? '<span class="badge badge-ok">ON</span>'
    : '<span class="muted">off</span>';
}

function renderCommands(commands) {
  const body = document.getElementById('commandBody');

  if (commands.length === 0) {
    body.innerHTML =
      '<tr><td colspan="9" class="empty">Belum ada command untuk incident ini.</td></tr>';
    return;
  }

  body.innerHTML = commands.map((command) => (
    '<tr>' +
      '<td class="mono">' + command.id + '</td>' +
      '<td>' + badge(command.command) + '</td>' +
      '<td>' + boolCell(command.strobe) + '</td>' +
      '<td>' + boolCell(command.siren) + '</td>' +
      '<td>' + boolCell(command.speaker) + '</td>' +
      '<td>' + escapeHtml(command.voice_message || '-') + '</td>' +
      '<td>' + badge(command.status) + '</td>' +
      '<td class="nowrap">' + formatTime(command.created_at) + '</td>' +
      '<td class="nowrap">' + formatTime(command.executed_at) + '</td>' +
    '</tr>'
  )).join('');
}

function renderLogs(logs) {
  const body = document.getElementById('logBody');

  if (logs.length === 0) {
    body.innerHTML = '<tr><td colspan="3" class="empty">Belum ada log.</td></tr>';
    return;
  }

  body.innerHTML = logs.map((log) => (
    '<tr>' +
      '<td class="nowrap">' + formatTime(log.created_at) + '</td>' +
      '<td class="mono">' + escapeHtml(log.event_type) + '</td>' +
      '<td>' + escapeHtml(log.message) + '</td>' +
    '</tr>'
  )).join('');
}

/* --- Aksi operator ---------------------------------------------------- */

function renderActions(incident) {
  const id = escapeHtml(incident.incident_id);
  let html = '';

  if (incident.status === 'CLOSED') {
    html = '<span class="muted">Incident sudah ditutup. Tidak ada aksi tersisa.</span>';
  } else {
    if (incident.server_decision !== 'CONFIRMED') {
      html += '<button class="btn btn-danger" data-aksi="confirm" data-id="' + id + '">Confirm</button>';
    }
    if (incident.status !== 'DISPATCHED') {
      html += '<button class="btn btn-warn" data-aksi="dispatch" data-id="' + id + '">Dispatch</button>';
    }
    if (incident.status !== 'FALSE_ALARM') {
      html += '<button class="btn" data-aksi="false-alarm" data-id="' + id + '">False Alarm</button>';
    }
    html += '<button class="btn btn-ok" data-aksi="close" data-id="' + id + '">Close</button>';
  }

  document.getElementById('actionArea').innerHTML = html;
}

document.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-aksi]');
  if (!button) return;

  const aksi = button.dataset.aksi;

  const konfirmasi = {
    'confirm': 'Konfirmasi incident ini sebagai emergency nyata? Sirene akan diaktifkan.',
    'dispatch': 'Tandai petugas sudah dikirim ke lokasi?',
    'false-alarm': 'Tandai sebagai FALSE ALARM? Sirene dan strobe akan dimatikan.',
    'close': 'Tutup incident ini? Sirene dan strobe akan dimatikan.',
  }[aksi];

  if (konfirmasi && !window.confirm(konfirmasi)) return;

  button.disabled = true;
  try {
    await apiPostOperator('/api/incidents/' + encodeURIComponent(INCIDENT_ID) + '/' + aksi, {});
    await refresh();
  } catch (error) {
    window.alert('Gagal: ' + error.message);
  } finally {
    button.disabled = false;
  }
});

/* --- Siklus penyegaran ------------------------------------------------ */

async function refresh() {
  let data;
  try {
    data = await apiGet('/api/incidents/' + encodeURIComponent(INCIDENT_ID));
  } catch (error) {
    document.getElementById('errorArea').innerHTML =
      '<div class="notice">Gagal memuat incident: ' + escapeHtml(error.message) + '</div>';
    throw error;
  }

  const incident = data.incident;
  document.getElementById('errorArea').innerHTML = '';

  renderSummary(incident);
  renderContext(incident.context);
  renderFlow(incident, data.commands);
  renderCommands(data.commands);
  renderLogs(data.logs);
  renderActions(incident);

  document.getElementById('reasonArea').textContent = incident.server_reason || '-';
}

document.addEventListener('DOMContentLoaded', () => {
  startPolling(refresh, 3000);
});
