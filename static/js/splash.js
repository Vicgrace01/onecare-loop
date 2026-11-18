// Splash — Cinematic Intro with GSAP
window.addEventListener('DOMContentLoaded', () => {
  if (!window.gsap) {
    // Fallback: just show everything
    document.querySelectorAll('.splash h1 .word, .splash-sub, .splash-cta, .splash-ring-wrap').forEach(el => {
      el.style.opacity = 1;
      el.style.transform = 'none';
    });
    return;
  }

  const tl = gsap.timeline({ defaults: { ease: 'power3.out' } });

  // 1. Ring draws in
  tl.fromTo('.splash-ring-wrap', 
    { opacity: 0, scale: 0.8 }, 
    { opacity: 1, scale: 1, duration: 1.2, ease: 'expo.out' }, 0);

  // 2. Words split converge
  const words = document.querySelectorAll('.splash h1 .word');
  const mid = Math.floor(words.length / 2);
  const leftWords = Array.from(words).slice(0, mid);
  const rightWords = Array.from(words).slice(mid);
  
  tl.fromTo(leftWords, 
    { x: '-100vw', opacity: 0 },
    { x: 0, opacity: 1, duration: 1, stagger: 0.05, ease: 'power3.out' }, 0.6);
  tl.fromTo(rightWords, 
    { x: '100vw', opacity: 0 },
    { x: 0, opacity: 1, duration: 1, stagger: -0.05, ease: 'power3.out' }, 0.6);

  // 3. Subtitle
  tl.fromTo('.splash-sub',
    { y: 20, opacity: 0 },
    { y: 0, opacity: 1, duration: 0.8 }, 1.8);

  // 4. CTA
  tl.fromTo('.splash-cta',
    { y: 20, opacity: 0 },
    { y: 0, opacity: 1, duration: 0.6, ease: 'back.out(1.7)' }, 2.2);

  // Counter animation
  const counters = document.querySelectorAll('[data-count-to]');
  counters.forEach(c => {
    const target = parseFloat(c.dataset.countTo);
    const suffix = c.dataset.suffix || '';
    const obj = { val: 0 };
    tl.to(obj, {
      val: target,
      duration: 1.5,
      ease: 'power2.out',
      onUpdate: () => c.textContent = (target >= 10 ? Math.round(obj.val) : obj.val.toFixed(1)) + suffix
    }, 2.5);
  });
});