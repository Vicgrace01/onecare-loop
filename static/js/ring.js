// Animated ring — each node draws in with a stagger on render.
const RING_CANONICAL = [
  ['SCREEN_POSITIVE', 'Screened'],
  ['REFERRAL_CREATED', 'Referred'],
  ['FACILITY_ACCEPTED', 'Accepted'],
  ['APPOINTMENT_BOOKED', 'Booked'],
  ['CLINICAL_ENCOUNTER_COMPLETED', 'Seen'],
  ['CLINICAL_DISPOSITION_RETURNED', 'Outcome'],
];

const RING_FAILURE = new Set([
  'REFERRAL_DECLINED','FACILITY_UNAVAILABLE','APPOINTMENT_MISSED',
  'PATIENT_UNREACHABLE','PATIENT_DECLINED','PATIENT_REQUESTED_RESCHEDULE',
  'REFERRAL_REDIRECTED','FOLLOWUP_OVERDUE',
]);

window.renderRing = function (containerId, events, opts = {}) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const types = events.map(e => e.event_type);
  const lastIsFailure = types.length > 0 && RING_FAILURE.has(types[types.length - 1]);
  const previousTypes = opts.previousTypes || [];
  const isUpdate = previousTypes.length > 0;

  let html = '';
  let currentSeen = false;

  for (let i = 0; i < RING_CANONICAL.length; i++) {
    const [type, label] = RING_CANONICAL[i];
    const done = types.includes(type);
    let cls = '';
    if (done) cls = 'done';
    else if (lastIsFailure) cls = 'broken';
    else if (!currentSeen) { cls = 'current'; currentSeen = true; }

    const isNew = done && !previousTypes.includes(type);

    if (i > 0) {
      const prevDone = types.includes(RING_CANONICAL[i - 1][0]);
      html += `<div class="ring-connector ${prevDone ? 'done' : ''}"></div>`;
    }
    html += `<div class="ring-node ${cls}" data-i="${i}"><div class="ring-circle"></div><div class="ring-label">${label}</div></div>`;
  }

  container.innerHTML = html;

  // Animate nodes that just became done
  if (isUpdate) {
    container.querySelectorAll('.ring-node.done').forEach((node, idx) => {
      const i = parseInt(node.dataset.i);
      const [type] = RING_CANONICAL[i];
      if (!previousTypes.includes(type)) {
        node.classList.add('entering');
        node.querySelector('.ring-circle').style.animationDelay = (idx * 120) + 'ms';
      }
    });
  }
};