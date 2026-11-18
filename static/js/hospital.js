let selected = { referralId: null, patientId: null, currentState: null };

async function loadQueue() {
  const r = await fetch('/api/hospital/queue');
  const j = await r.json();
  const tbody = document.getElementById('queue-tbody');
  tbody.innerHTML = '';

  if (!j.queue.length) {
    document.getElementById('empty-state').style.display = 'block';
    document.getElementById('queue-wrap').style.display = 'none';
    return;
  }
  document.getElementById('empty-state').style.display = 'none';
  document.getElementById('queue-wrap').style.display = 'block';

  j.queue.forEach((ref, i) => {
    const tr = document.createElement('tr');
    if (selected.referralId === ref.id) tr.classList.add('selected');
    tr.style.animationDelay = (i * 60) + 'ms';
    tr.onclick = (e) => { if (e.target.tagName !== 'BUTTON') openReferral(ref.id, ref.patient_id); };

    const urgClass = ref.urgency === 'emergency' ? 'state-failure'
      : ref.urgency === 'urgent' ? 'state-pending' : 'state-positive';
    const sla = ref.sla_breached
      ? '<span style="color: var(--vermilion); font-weight: 600;">⚠ BREACHED</span>'
      : new Date(ref.sla_deadline).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

    tr.innerHTML = `
      <td><span class="state-pill ${urgClass}">${ref.urgency}</span></td>
      <td class="mono">${ref.systolic}/${ref.diastolic}</td>
      <td class="mono" style="font-size: 11.5px;">${sla}</td>
      <td class="mono" style="font-size: 11.5px;">${ref.patient_id.slice(0, 8)}…</td>
      <td class="mono" style="font-size: 11px;">${ref.status}</td>
      <td><button class="btn btn-sm">Open</button></td>
    `;
    tbody.appendChild(tr);
  });
}

async function openReferral(referralId, patientId) {
  selected = { referralId, patientId, currentState: null };

  const [stateRes, histRes] = await Promise.all([
    fetch(`/api/loop/state/${patientId}`),
    fetch(`/api/referrals/${referralId}/history`),
  ]);
  const state = await stateRes.json();
  const hist = await histRes.json();

  selected.currentState = state.current_state;

  const panel = document.getElementById('panel');
  panel.style.display = 'block';
  panel.innerHTML = `
    <div class="action-panel">
      <div class="flex justify-between items-center" style="flex-wrap: wrap; gap: var(--space-3);">
        <div>
          <h3 style="margin-bottom: 2px;">Referral ${referralId.slice(0, 8)}…</h3>
          <p class="muted" style="font-size: 12px; margin: 0;">Patient · <span class="mono-inline">${patientId}</span></p>
        </div>
        <div class="flex gap-2 items-center">
          <span class="state-pill state-info">${state.current_state}</span>
          <button class="btn btn-sm btn-outline" onclick="closePanel()">Close</button>
        </div>
      </div>

      <div class="ring" id="ring-hospital" style="margin-top: var(--space-6);"></div>

      <div id="actions" class="action-area"></div>
      <div id="action-error" style="display:none; padding: var(--space-3); background: rgba(214,64,43,0.1); border-radius: var(--radius-md); color: var(--vermilion); font-size: 13px; margin-top: var(--space-3);"></div>
    </div>
  `;

  renderRing('ring-hospital', hist.events, { previousTypes: [] });
  renderActions(state.current_state, hist.events);
}

function renderActions(state, events) {
  const c = document.getElementById('actions');
  c.innerHTML = '';

  if (state === 'REFERRAL_CREATED') {
    c.innerHTML = `
      <div style="display: grid; gap: var(--space-3);">
        <button id="accept-btn" class="btn btn-green btn-full">✓ Accept referral</button>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); align-items: end;">
          <label style="font-size: 12px; color: var(--slate);">Decline reason
            <input class="input" id="decline-reason" value="no_slots" style="margin-top: 4px;">
          </label>
          <label style="font-size: 12px; color: var(--slate);">Redirect to
            <input class="input" id="decline-next" value="HOSP-B" style="margin-top: 4px;">
          </label>
        </div>
        <button id="decline-btn" class="btn btn-outline btn-full">Decline + auto-redirect</button>
      </div>
    `;
    document.getElementById('accept-btn').onclick = (e) => doAction(e.currentTarget, `/api/referrals/${selected.referralId}/accept`,
      { actor_id: 'hospital@onecare.demo' }, 'Accepting…', 'Accepted', events);
    document.getElementById('decline-btn').onclick = (e) => doAction(e.currentTarget, `/api/referrals/${selected.referralId}/decline`, {
      actor_id: 'hospital@onecare.demo',
      reason_code: document.getElementById('decline-reason').value,
      owner: 'care_navigator',
      next_facility_id: document.getElementById('decline-next').value,
    }, 'Declining…', 'Declined', events);

  } else if (state === 'FACILITY_ACCEPTED') {
    c.innerHTML = `
      <div style="display: grid; gap: var(--space-3);">
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3);">
          <label style="font-size: 12px; color: var(--slate);">Slot start
            <input type="datetime-local" id="slot-start" class="input" value="2026-11-20T09:00" style="margin-top: 4px;">
          </label>
          <label style="font-size: 12px; color: var(--slate);">Slot end
            <input type="datetime-local" id="slot-end" class="input" value="2026-11-20T09:30" style="margin-top: 4px;">
          </label>
        </div>
        <button id="book-btn" class="btn btn-green btn-full">Book appointment →</button>
      </div>
    `;
    document.getElementById('book-btn').onclick = (e) => doAction(e.currentTarget, `/api/referrals/${selected.referralId}/book`, {
      actor_id: 'hospital@onecare.demo',
      slot_start: new Date(document.getElementById('slot-start').value).toISOString(),
      slot_end: new Date(document.getElementById('slot-end').value).toISOString(),
    }, 'Booking…', 'Booked', events);

  } else if (state === 'APPOINTMENT_BOOKED') {
    c.innerHTML = `<button id="attest-btn" class="btn btn-green btn-full">✓ Mark patient attended</button>`;
    document.getElementById('attest-btn').onclick = (e) => doAction(e.currentTarget, `/api/referrals/${selected.referralId}/attest`,
      { actor_id: 'hospital@onecare.demo', clinician_id: 'clinician@onecare.demo', notes: 'seen' },
      'Recording attendance…', 'Attended', events);

  } else if (state === 'CLINICAL_ENCOUNTER_COMPLETED') {
    c.innerHTML = `
      <div style="display: grid; gap: var(--space-3);">
        <label style="font-size: 12px; color: var(--slate);">Clinical outcome
          <input class="input" id="outcome" value="started_medication" style="margin-top: 4px;">
        </label>
        <label style="font-size: 12px; color: var(--slate);">Next step
          <input class="input" id="next-step" value="BP review in 30 days" style="margin-top: 4px;">
        </label>
        <button id="counter-btn" class="btn btn-green btn-full">Close the loop → counter-refer</button>
      </div>
    `;
    document.getElementById('counter-btn').onclick = (e) => doAction(e.currentTarget, `/api/referrals/${selected.referralId}/counter-refer`, {
      actor_id: 'clinician@onecare.demo',
      clinician_id: 'clinician@onecare.demo',
      outcome: document.getElementById('outcome').value,
      next_step: document.getElementById('next-step').value,
    }, 'Closing the loop…', 'Loop closed', events, { isClose: true });

  } else if (state === 'CLINICAL_DISPOSITION_RETURNED') {
    c.innerHTML = `<div class="pill-status" style="animation: stamp-in 500ms var(--ease-spring);"><span>✓</span><span>Loop closed</span></div>`;
  } else {
    c.innerHTML = `<p class="muted">No action for state <span class="mono-inline">${state}</span></p>`;
  }
}

async function doAction(button, url, body, loadingText, successText, previousEvents, opts = {}) {
  const errBox = document.getElementById('action-error');
  errBox.style.display = 'none';

  try {
    const result = await ButtonEngine.run(button, {
      loadingText, successText, successDuration: 700,
      action: async () => {
        const r = await fetch(url, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const j = await r.json();
        if (!r.ok || !j.ok) throw new Error(j.message || j.error || 'action failed');
        return j;
      },
    });

    const patientId = selected.patientId;
    const referralId = selected.referralId;

    // Fetch updated history + state
    const [histRes, stateRes] = await Promise.all([
      fetch(`/api/referrals/${referralId}/history`),
      fetch(`/api/loop/state/${patientId}`),
    ]);
    const hist = await histRes.json();
    const state = await stateRes.json();

    // Animate the ring — new node draws in
    renderRing('ring-hospital', hist.events, { previousTypes: previousEvents.map(e => e.event_type) });

    // If loop closed, pulse the last node
    if (opts.isClose) {
      const lastNode = document.querySelector('#ring-hospital .ring-node.done:last-of-type .ring-circle');
      if (lastNode) lastNode.style.animation = 'pulse-green 800ms var(--ease-out)';
    }

    // Slide new action panel in
    setTimeout(() => renderActions(state.current_state, hist.events), 200);

    // Update the state pill in the header
    const pill = document.querySelector('.action-panel .state-pill');
    if (pill) { pill.textContent = state.current_state; }

    // Refresh queue in background
    if (state.current_state === 'CLINICAL_DISPOSITION_RETURNED' || state.current_state === 'REFERRAL_DECLINED') {
      setTimeout(loadQueue, 400);
    }
  } catch (err) {
    errBox.textContent = err.message;
    errBox.style.display = 'block';
  }
}

function closePanel() {
  document.getElementById('panel').style.display = 'none';
  selected = { referralId: null, patientId: null, currentState: null };
  loadQueue();
}

window.addEventListener('DOMContentLoaded', loadQueue);