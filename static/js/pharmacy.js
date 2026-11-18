// Pharmacy surface — narrative interactions.

function getSymptoms() {
  return Array.from(document.querySelectorAll('#symptom-grid input:checked')).map(el => el.value);
}

function checkBP() {
  const s = parseInt(document.getElementById('systolic').value) || 0;
  const d = parseInt(document.getElementById('diastolic').value) || 0;
  const warn = document.getElementById('bp-warning');
  if (s >= 180 || d >= 120) {
    warn.textContent = '⚠ Red flag: BP ≥ 180/120. Refer as emergency.';
    warn.className = 'warning show danger';
  } else if (s >= 140 || d >= 90) {
    warn.textContent = 'Positive screening (≥ 140/90). Refer for clinical assessment.';
    warn.className = 'warning show';
  } else {
    warn.className = 'warning';
  }
}

async function submitScreening() {
  const errBox = document.getElementById('error-box');
  errBox.style.display = 'none';

  if (!document.getElementById('consent').checked) {
    errBox.textContent = 'Consent is required before screening.';
    errBox.style.display = 'block';
    return;
  }

  const btn = document.getElementById('submit-btn');
  const body = {
    patient: {
      age_band: document.getElementById('age_band').value,
      insurance_type: document.getElementById('insurance').value,
      nhia_number: document.getElementById('nhia_number').value || null,
      phone: document.getElementById('phone').value,
    },
    consent: { version: '1.0', scope: ['screening', 'referral', 'follow_up'] },
    screening: {
      pharmacy_id: 'PHARM-A',
      systolic: parseInt(document.getElementById('systolic').value),
      diastolic: parseInt(document.getElementById('diastolic').value),
      symptoms: getSymptoms(),
      protocol_version: 'HTN-PROTOCOL-v1',
    },
    actor_id: 'pharmacy@onecare.demo',
  };

  try {
    const result = await ButtonEngine.run(btn, {
      loadingText: 'Screening patient…',
      successText: 'Screening recorded',
      successDuration: 700,
      action: async () => {
        const r1 = await fetch('/api/screening', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!r1.ok) { const e = await r1.json(); throw new Error(e.message || e.error); }
        const screening = await r1.json();

        const r2 = await fetch('/api/referral', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            screening_id: screening.screening.id,
            facility_id: 'HOSP-A',
            actor_id: 'pharmacy@onecare.demo',
          }),
        });
        if (!r2.ok) { const e = await r2.json(); throw new Error(e.message || e.error); }
        const referral = await r2.json();
        return { screening, referral };
      },
    });

    const { screening, referral } = result;

    // Story transition: form fades out, result card slides in
    document.getElementById('form-card').style.display = 'none';
    const result = document.getElementById('result-card');
    result.style.display = 'block';

    document.getElementById('result-patient').textContent = screening.patient_id.slice(0, 8) + '…';
    document.getElementById('result-referral').textContent = referral.referral_id.slice(0, 8) + '…';
    document.getElementById('result-urgency').innerHTML = `<span class="state-pill ${referral.urgency === 'emergency' ? 'state-failure' : 'state-pending'}">${referral.urgency}</span>`;
    document.getElementById('result-eligibility').textContent = referral.eligibility.decision;
    document.getElementById('result-seq').textContent = referral.event.seq;
    document.getElementById('result-hash').textContent = referral.event.hash.slice(0, 16) + '…';

    document.getElementById('link-patient').href = '/demo/patient?patient_id=' + screening.patient_id;

    // Animated ring arrives with stagger
    renderRing('ring-pharmacy', [screening.event, referral.event], { previousTypes: [] });
  } catch (err) {
    errBox.textContent = err.message || 'Something went wrong.';
    errBox.style.display = 'block';
  }
}

function resetForm() {
  document.getElementById('result-card').style.display = 'none';
  document.getElementById('form-card').style.display = 'block';
}

window.addEventListener('DOMContentLoaded', () => {
  document.getElementById('systolic').addEventListener('input', checkBP);
  document.getElementById('diastolic').addEventListener('input', checkBP);
  checkBP();

  // Symptom card toggle
  document.querySelectorAll('.symptom-item').forEach(item => {
    item.addEventListener('click', () => {
      const cb = item.querySelector('input');
      setTimeout(() => item.classList.toggle('checked', cb.checked), 0);
    });
  });

  document.getElementById('submit-btn').addEventListener('click', submitScreening);
});