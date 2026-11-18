/* =========================================================================
   ONECARE LOOP — MOTION ENGINE
   GSAP + ScrollTrigger + Lenis + custom cursor + magnetic buttons
   ========================================================================= */

(function () {
  'use strict';

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const hasGSAP = typeof window.gsap !== 'undefined';
  const hasST = typeof window.ScrollTrigger !== 'undefined';
  const hasLenis = typeof window.Lenis !== 'undefined';

  /* ---------- Custom cursor ---------- */
  const Cursor = {
    dot: null,
    ring: null,
    mx: 0, my: 0,
    rx: 0, ry: 0,
    init() {
      if (reduced || window.matchMedia('(pointer: coarse)').matches) return;
      document.documentElement.classList.add('has-custom-cursor');
      this.dot = document.createElement('div');
      this.dot.className = 'cursor-dot';
      this.ring = document.createElement('div');
      this.ring.className = 'cursor-ring';
      document.body.appendChild(this.dot);
      document.body.appendChild(this.ring);

      document.addEventListener('mousemove', (e) => {
        this.mx = e.clientX;
        this.my = e.clientY;
        this.dot.style.left = this.mx + 'px';
        this.dot.style.top = this.my + 'px';
      }, { passive: true });

      const loop = () => {
        this.rx += (this.mx - this.rx) * 0.15;
        this.ry += (this.my - this.ry) * 0.15;
        this.ring.style.left = this.rx + 'px';
        this.ring.style.top = this.ry + 'px';
        requestAnimationFrame(loop);
      };
      requestAnimationFrame(loop);

      const hoverTargets = 'a, button, [role="button"], .gate-card, .nav-item, .s-role, .chip, .action-card, .demo-card, .s-primary-cta';
      document.addEventListener('mouseover', (e) => {
        if (e.target.closest(hoverTargets)) {
          this.dot.classList.add('hovering');
          this.ring.classList.add('hovering');
        }
      });
      document.addEventListener('mouseout', (e) => {
        if (e.target.closest(hoverTargets)) {
          this.dot.classList.remove('hovering');
          this.ring.classList.remove('hovering');
        }
      });
      document.addEventListener('mousedown', () => this.ring.classList.add('pressed'));
      document.addEventListener('mouseup', () => this.ring.classList.remove('pressed'));
    },
  };

  /* ---------- Magnetic buttons ---------- */
  const Magnetic = {
    init() {
      if (reduced) return;
      document.querySelectorAll('.magnetic, .s-primary-cta, .btn-lg').forEach((el) => {
        el.addEventListener('mousemove', (e) => {
          const rect = el.getBoundingClientRect();
          const x = e.clientX - rect.left - rect.width / 2;
          const y = e.clientY - rect.top - rect.height / 2;
          if (hasGSAP) {
            gsap.to(el, { x: x * 0.25, y: y * 0.25, duration: 0.4, ease: 'power2.out' });
          } else {
            el.style.transform = `translate(${x * 0.25}px, ${y * 0.25}px)`;
          }
        });
        el.addEventListener('mouseleave', () => {
          if (hasGSAP) {
            gsap.to(el, { x: 0, y: 0, duration: 0.6, ease: 'elastic.out(1, 0.4)' });
          } else {
            el.style.transform = 'translate(0, 0)';
          }
        });
      });
    },
  };

  /* ---------- Lenis smooth scroll ---------- */
  const Smooth = {
    init() {
      if (reduced || !hasLenis) return;
      const lenis = new Lenis({
        duration: 1.15,
        easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
        wheelMultiplier: 1,
        touchMultiplier: 1.6,
      });
      if (hasGSAP && hasST) {
        lenis.on('scroll', ScrollTrigger.update);
        gsap.ticker.add((time) => { lenis.raf(time * 1000); });
        gsap.ticker.lagSmoothing(0);
      } else {
        function raf(time) { lenis.raf(time); requestAnimationFrame(raf); }
        requestAnimationFrame(raf);
      }
      window.__lenis = lenis;
    },
  };

  /* ---------- Scroll reveals ---------- */
  const Reveals = {
    init() {
      document.querySelectorAll('.gs-reveal').forEach((el) => {
        if (reduced) { el.classList.add('in'); return; }
        if (hasGSAP && hasST) {
          gsap.to(el, {
            opacity: 1, y: 0, duration: 1,
            ease: 'power3.out',
            scrollTrigger: { trigger: el, start: 'top 85%', once: true },
            onStart: () => el.classList.add('in'),
          });
        } else {
          const obs = new IntersectionObserver((entries) => {
            entries.forEach(en => {
              if (en.isIntersecting) {
                en.target.classList.add('in');
                obs.unobserve(en.target);
              }
            });
          }, { threshold: 0.15 });
          obs.observe(el);
        }
      });
    },
  };

  /* ---------- Page transition curtain ---------- */
  const PageTransition = {
    init() {
      if (reduced) return;
      const curtain = document.createElement('div');
      curtain.className = 'page-curtain entering';
      document.body.appendChild(curtain);

      document.addEventListener('click', (e) => {
        const a = e.target.closest('a[href]');
        if (!a || a.target === '_blank' || a.hasAttribute('download')) return;
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        const url = new URL(a.href, location.href);
        if (url.origin !== location.origin) return;
        if (url.pathname === location.pathname && !url.hash) return;
        // Do NOT intercept demo-login — must be a direct nav for session cookie
        if (url.pathname === '/patient/demo-login') return;
        e.preventDefault();
        curtain.classList.remove('entering');
        curtain.classList.add('exiting');
        setTimeout(() => { location.href = a.href; }, 500);
      });
    },
  };

  /* ---------- Split lines (for headings) ---------- */
  window.splitLines = function (selector) {
    document.querySelectorAll(selector).forEach((el) => {
      const text = el.textContent;
      const words = text.split(/\s+/).filter(Boolean);
      el.innerHTML = words.map(w => `<span class="split-line" style="display:inline-block"><span>${w}</span></span>`).join(' ');
    });
  };

  /* ---------- Boot ---------- */
  document.addEventListener('DOMContentLoaded', () => {
    if (hasGSAP && hasST) gsap.registerPlugin(ScrollTrigger);
    Cursor.init();
    Smooth.init();
    Magnetic.init();
    Reveals.init();
    PageTransition.init();
  });

  window.Motion = { Cursor, Magnetic, Smooth, Reveals, PageTransition };
})();