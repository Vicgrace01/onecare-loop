/* =========================================================================
   ONECARE LOOP — UI layer
   Reveal system · tickers · ripple · cursor · page transitions · toasts
   ========================================================================= */

(function () {
  'use strict';

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- Reveal on scroll ---------- */
  const Reveal = {
    observer: null,
    init() {
      if (reduced) {
        document.querySelectorAll('.reveal, .s-fade, .s-slide-up, .reveal-scale, .s-stagger')
          .forEach(el => el.classList.add('revealed'));
        return;
      }
      this.observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            entry.target.classList.add('revealed');
            this.observer.unobserve(entry.target);
          }
        });
      }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });

      document.querySelectorAll('.reveal, .s-fade, .s-slide-up, .reveal-scale, .s-stagger').forEach(el => {
        this.observer.observe(el);
      });
    },
    observe(el) {
      if (this.observer && el) this.observer.observe(el);
    }
  };

  /* ---------- Stagger indexing ---------- */
  document.querySelectorAll('.s-stagger').forEach(parent => {
    Array.from(parent.children).forEach((child, i) => {
      child.style.setProperty('--i', i);
    });
  });

  /* ---------- Number ticker ---------- */
  const Ticker = {
    format(n, opts) {
      const { decimals = 0, prefix = '', suffix = '', thousands = true } = opts || {};
      let s;
      if (decimals > 0) {
        s = n.toFixed(decimals);
      } else if (thousands) {
        s = Math.round(n).toLocaleString();
      } else {
        s = String(Math.round(n));
      }
      return prefix + s + suffix;
    },
    count(el, target, opts) {
      if (!el) return;
      if (reduced) {
        el.textContent = this.format(target, opts);
        return;
      }
      const duration = (opts && opts.duration) || 1200;
      const start = performance.now();
      const self = this;
      function tick(now) {
        const p = Math.min((now - start) / duration, 1);
        const eased = 1 - Math.pow(1 - p, 3);
        el.textContent = self.format(target * eased, opts);
        if (p < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    },
    countOnReveal(el) {
      const target = parseFloat(el.dataset.ticker);
      if (isNaN(target)) return;
      const opts = {
        decimals: parseInt(el.dataset.decimals || '0'),
        prefix: el.dataset.prefix || '',
        suffix: el.dataset.suffix || '',
        thousands: el.dataset.thousands !== 'false'
      };
      const obs = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            this.count(entry.target, target, opts);
            obs.unobserve(entry.target);
          }
        });
      }, { threshold: 0.3 });
      obs.observe(el);
    }
  };

  /* ---------- Ripple ---------- */
  const Ripple = {
    attach(el) {
      if (reduced) return;
      el.addEventListener('click', (e) => {
        const rect = el.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height) * 2;
        const span = document.createElement('span');
        span.className = 'ripple';
        span.style.width = span.style.height = size + 'px';
        span.style.left = (e.clientX - rect.left - size / 2) + 'px';
        span.style.top = (e.clientY - rect.top - size / 2) + 'px';
        el.appendChild(span);
        setTimeout(() => span.remove(), 650);
      });
    },
    init() {
      document.querySelectorAll('.btn, .icon-btn, .nav-item, .gate-card').forEach(el => this.attach(el));
    }
  };

  /* ---------- Page transitions ---------- */
  const PageTransition = {
    init() {
      if (!document.startViewTransition) return;
      document.addEventListener('click', (e) => {
        const a = e.target.closest('a[href]');
        if (!a || a.target === '_blank' || a.hasAttribute('download')) return;
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        const url = new URL(a.href, location.href);
        if (url.origin !== location.origin) return;
        if (url.pathname === location.pathname && !url.hash) return;
        e.preventDefault();
        document.startViewTransition(() => { location.href = a.href; });
      });
    }
  };

  /* ---------- Custom cursor zones ---------- */
  const CursorZone = {
    init() {
      document.querySelectorAll('.cursor-zone').forEach(el => {
        el.addEventListener('mouseenter', () => {
          document.body.style.cursor = el.classList.contains('copy') ? 'copy' : 'crosshair';
        });
        el.addEventListener('mouseleave', () => { document.body.style.cursor = ''; });
      });
    }
  };

  /* ---------- Skeleton swap ---------- */
  const Skeleton = {
    swap(selector, html) {
      const el = document.querySelector(selector);
      if (!el) return;
      el.innerHTML = html;
      el.querySelectorAll('.reveal').forEach(r => r.classList.add('revealed'));
    }
  };

  /* ---------- Toast queue ---------- */
  const Toast = {
    queue: [],
    show(msg, type) {
      const c = document.getElementById('toasts');
      if (!c) return;
      const t = document.createElement('div');
      t.className = 'toast ' + (type || '');
      t.textContent = msg;
      c.appendChild(t);
      setTimeout(() => {
        t.style.opacity = '0';
        t.style.transform = 'translateX(20px)';
        t.style.transition = 'opacity 300ms, transform 300ms';
        setTimeout(() => t.remove(), 300);
      }, 3200);
    }
  };

  /* ---------- Keyboard shortcuts ---------- */
  const Keyboard = {
    init() {
      document.addEventListener('keydown', (e) => {
        if (e.key === '?' && !this._inInput(e)) {
          e.preventDefault();
          Toast.show('Shortcuts: ? = help · Esc = close · / = focus search', '');
        }
        if (e.key === '/' && !this._inInput(e)) {
          e.preventDefault();
          const s = document.querySelector('.search-input');
          if (s) s.focus();
        }
      });
    },
    _inInput(e) {
      const t = e.target;
      return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
    }
  };

  /* ---------- Sparkline generator ---------- */
  window.sparkline = function (values, opts) {
    const w = 100, h = 32;
    const max = Math.max(...values);
    const min = Math.min(...values);
    const range = max - min || 1;
    const step = w / (values.length - 1);
    const pts = values.map((v, i) => [i * step, h - ((v - min) / range) * h]);
    const d = pts.map((p, i) => (i === 0 ? 'M' : 'L') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
    const fillD = d + ` L${w} ${h} L0 ${h} Z`;
    const color = (opts && opts.color) || 'var(--teal)';
    return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <path class="spark-fill" d="${fillD}" style="fill:${color}"></path>
      <path d="${d}" style="stroke:${color}"></path>
    </svg>`;
  };

  /* ---------- Word reveal (splash) ---------- */
  window.wordReveal = function (el, delay) {
    if (!el || reduced) return;
    const text = el.dataset.text || el.textContent;
    const words = text.split(/\s+/).filter(Boolean);
    const em = el.dataset.em;
    el.innerHTML = words.map((w, i) => {
      const content = (em && i === words.length - 1) ? `<em>${w}</em>` : w;
      return `<span class="word-reveal"><span>${content}</span></span>`;
    }).join(' ');
    el.querySelectorAll('.word-reveal').forEach((w, i) => {
      setTimeout(() => w.classList.add('in'), (delay || 300) + i * 90);
    });
  };

  /* ---------- Boot ---------- */
  document.addEventListener('DOMContentLoaded', () => {
    Reveal.init();
    Ripple.init();
    PageTransition.init();
    CursorZone.init();
    Keyboard.init();

    document.querySelectorAll('[data-ticker]').forEach(el => Ticker.countOnReveal(el));

    // Splash-specific word reveals
    document.querySelectorAll('[data-word-reveal]').forEach(el => {
      const delay = parseInt(el.dataset.wordDelay || '300');
      wordReveal(el, delay);
    });
  });

  /* ---------- Exports ---------- */
  window.UI = { Reveal, Ticker, Ripple, PageTransition, CursorZone, Skeleton, Toast };
})();