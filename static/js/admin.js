// Admin dashboard — counters, tamper shockwave.

function countUp(el, target, opts = {}) {
  const { suffix = '', duration = 900, isFloat = false } = opts;
  const start = performance.now();
  function tick(now) {
    const p = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - p, 3);
    const val = target * eased;
    el.textContent = (isFloat ? val.toFixed(2) : Math.round(val).toLocaleString()) + suffix;
    if (p < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

async function loadStats() {
  const r = await fetch('/api/metrics');
  const j = await r.json();

  const grid = document.getElementById('stats');
  grid.innerHTML = '';

  const stats = [
    { label: 'Patients', value: j.total_patients, suffix: '' },
    { label: 'Closed loops', value: j.closed_loops, suffix: '' },
    { label: 'Closure rate', value: (j.closure_rate * 100), suffix: '%', isFloat: true },
    { label: 'Median time-to-care', value: j.time_to_care_median_hours || 0, suffix: 'h', isFloat: true },
    { label: 'Money recovered (simulated)', value: j.money_recovered_naira, prefix: '₦' },
  ];

  stats.forEach((s, i) => {
    const card = document.createElement('div');
    card.className = 'stat';
    card.style.animation = `fade-up 500ms var(--ease-out) ${i * 80}ms both`;
    card.innerHTML = `
      <div class="stat-value" data-target="${s.value}" data-suffix="${s.suffix || ''}" data-prefix="${s.prefix || ''}" data-float="${s.isFloat || false}">0</div>
      <div class="stat-label">${s.label}</div>
    `;
    grid.appendChild(card);
    const valueEl = card.querySelector('.stat-value');
    if (s.prefix) {
      countUp({ textContent: '' }, 0); // noop
      setTimeout(() => {
        const prefixed = document.createElement('span');
        prefixed.textContent = s.prefix;
        valueEl.textContent = s.prefix;
        countUp(valueEl, s.value, { suffix: s.suffix || '', isFloat: !!s.isFloat });
      }, i * 80);
    } else {
      countUp(valueEl, s.value, { suffix: s.suffix || '', isFloat: !!s.isFloat });
    }
  });

  // Failure bars
  const f = document.getElementById('failures');
  const failures = j.failure_breakdown;
  const keys = Object.keys(failures);
  if (!keys.length) {
    f.innerHTML = '<p class="muted" style="margin: 0;">No failures logged yet. Run a decline from the hospital surface.</p>';
  } else {
    const max = Math.max(...Object.values(failures));
    f.innerHTML = keys.map(k => `
      <div style="display: grid; grid-template-columns: 220px 1fr auto; gap: var(--space-3); align-items: center; margin-bottom: var(--space-2); font-size: 13px;">
        <span class="mono">${k}</span>
        <div style="height: 8px; background: rgba(16,35,28,0.06); border-radius: 999px; overflow: hidden;">
          <div data-bar="${failures[k]}" data-max="${max}" style="height: 100%; width: 0; background: var(--vermilion); border-radius: 999px; transition: width 700ms var(--ease-out);"></div>
        </div>
        <span class="mono" style="min-width: 32px; text-align: right;">${failures[k]}</span>
      </div>
    `).join('');
    setTimeout(() => {
      f.querySelectorAll('[data-bar]').forEach(b => {
        const v = parseInt(b.dataset.bar);
        const m = parseInt(b.dataset.max);
        b.style.width = (m ? (v / m * 100) : 0) + '%';
      });
    }, 100);
  }
}

async function loadChain() {
  const r = await fetch('/api/audit/export');
  const text = await r.text();
  const events = text.split('\n').filter(Boolean).map(line => JSON.parse(line));

  // Use most recent patient
  const grouped = {};
  events.forEach(e => {
    grouped[e.patient_id] = grouped[e.patient_id] || [];
    grouped[e.patient_id].push(e);
  });
  const patientIds = Object.keys(grouped);
  if (!patientIds.length) {
    document.getElementById('chain-blocks').innerHTML = '<p class="muted">No events yet. Create one from the pharmacy surface.</p>';
    return;
  }
  const patientId = patientIds[patientIds.length - 1];
  const chain = grouped[patientId].sort((a, b) => a.seq - b.seq);

  const vRes = await fetch(`/api/audit/verify/${patientId}`);
  const v = await vRes.json();

  const status = document.getElementById('chain-status');
  status.innerHTML = v.ok
    ? `<span style="color: var(--loop-green); font-weight: 600;">✓ Chain verified</span> · ${v.events} events · head <span class="mono-inline">${v.head_hash.slice(0, 12)}…</span>`
    : `<span style="color: var(--vermilion); font-weight: 600;">✗ Chain broken</span> at seq ${v.broken_at?.seq} (${v.broken_at?.reason})`;

  const blocks = document.getElementById('chain-blocks');
  blocks.innerHTML = chain.map((e, i) => `
    <div class="chain-block" data-seq="${e.seq}" data-event-id="${e.id}" style="animation: fade-up 300ms var(--ease-out) ${i * 40}ms both;">
      <span class="seq-badge">#${e.seq}</span>
      <span>${e.event_type}</span>
      <span class="mono" style="font-size: 11px; color: var(--slate);">${e.hash.slice(0, 12)}…</span>
    </div>
  `).join('');

  window._chain = chain;
  window._chainPatient = patientId;
}

async function tamper() {
  if (!window._chain || !window._chain.length) return;
  const chain = window._chain;
  const midIndex = Math.floor(chain.length / 2);
  const target = chain[midIndex];

  document.getElementById('tamper-btn').disabled = true;

  try {
    const r = await fetch('/api/audit/tamper', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_id: target.id }),
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.message || j.error);

    // The shockwave: mark tampered block, then cascade red through all subsequent with 60ms stagger
    const blocks = document.querySelectorAll('.chain-block');
    blocks.forEach((b, idx) => {
      if (idx === midIndex) {
        setTimeout(() => {
          b.classList.add('tampering');
          // After the shake, add cascaded to all subsequent blocks with 60ms stagger
          for (let i = midIndex + 1; i < blocks.length; i++) {
            setTimeout(() => blocks[i].classList.add('cascaded'), (i - midIndex) * 60);
          }
        }, 0);
      }
    });

    setTimeout(loadChain, 300 + (blocks.length - midIndex) * 60 + 500);
  } catch (err) {
    alert(err.message);
  } finally {
    document.getElementById('tamper-btn').disabled = false;
  }
}

async function restore() {
  if (!window._chainPatient) return;
  await ButtonEngine.run(document.getElementById('restore-btn'), {
    loadingText: 'Restoring…', successText: 'Chain restored',
    action: async () => {
      const r = await fetch('/api/audit/restore', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ patient_id: window._chainPatient }),
      });
      const j = await r.json();
      if (!j.ok) throw new Error(j.message || 'restore failed');
      return j;
    },
  });
  await loadChain();
}

window.addEventListener('DOMContentLoaded', async () => {
  await loadStats();
  await loadChain();
  document.getElementById('tamper-btn').onclick = tamper;
  document.getElementById('restore-btn').onclick = restore;
});