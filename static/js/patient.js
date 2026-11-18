let currentPatientId = null;

async function loadReceipt(patientId) {
  const r = await fetch(`/api/patient/${patientId}/receipt?viewer_id=patient-self`);
  if (!r.ok) throw new Error('Patient not found');
  const j = await r.json();
  currentPatientId = patientId;

  document.querySelector('.thread-wrap .card').style.display = 'none';
  document.getElementById('thread-content').style.display = 'block';

  const badge = document.getElementById('thread-badge');
  const status = document.getElementById('thread-status');
  if (j.verified) {
    badge.className = 'state-pill state-positive';
    badge.textContent = 'VERIFIED ✓';
    status.textContent = 'Verified · ' + j.messages.length + ' events · chain intact';
  } else {
    badge.className = 'state-pill state-failure';
    badge.textContent = 'BROKEN';
    status.textContent = 'Chain broken at seq ' + (j.broken_at?.seq || '?');
  }

  const thread = document.getElementById('thread');
  thread.innerHTML = '';
  j.messages.forEach((m, i) => {
    const div = document.createElement('div');
    div.className = 'msg';
    div.style.animationDelay = (i * 120) + 'ms';
    div.innerHTML = `
      <div class="msg-headline">${m.headline}</div>
      ${m.detail ? `<div class="msg-detail">${m.detail}</div>` : ''}
      <div class="msg-meta">
        <span>${new Date(m.occurred_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
        <span class="msg-verified">${m.verified ? '✓ verified' : '✗ broken'} · ${m.hash_short}</span>
      </div>
    `;
    thread.appendChild(div);
  });
}

window.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(location.search);
  const preset = params.get('patient_id');
  const input = document.getElementById('patient-input');
  const loadBtn = document.getElementById('load-btn');

  if (preset) {
    input.value = preset;
    loadReceipt(preset).catch(err => alert(err.message));
  }

  loadBtn.onclick = () => {
    const id = input.value.trim();
    if (!id) return;
    loadReceipt(id).catch(err => alert(err.message));
  };

  document.getElementById('verify-btn').onclick = async (e) => {
    if (!currentPatientId) return;
    await ButtonEngine.run(e.currentTarget, {
      loadingText: 'Verifying…', successText: 'Chain intact',
      action: async () => {
        const r = await fetch(`/api/audit/verify/${currentPatientId}`);
        const j = await r.json();
        if (!j.ok) throw new Error('Chain broken at seq ' + (j.broken_at?.seq || '?'));
        return j;
      },
    });
  };

  document.getElementById('confirm-btn').onclick = async (e) => {
    if (!currentPatientId) return;
    await ButtonEngine.run(e.currentTarget, {
      loadingText: 'Recording…', successText: 'Confirmed',
      action: async () => {
        const r = await fetch(`/api/patient/${currentPatientId}/confirm-attendance`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ note: 'I attended' }),
        });
        const j = await r.json();
        if (!j.ok) throw new Error(j.message);
        return j;
      },
    });
  };
});