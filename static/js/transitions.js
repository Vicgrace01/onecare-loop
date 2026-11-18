// Page transitions via View Transitions API with graceful fallback.
(function () {
  document.addEventListener('click', (e) => {
    const a = e.target.closest('a[href]');
    if (!a) return;
    if (a.target === '_blank' || a.hasAttribute('download') || a.dataset.noTransition !== undefined) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const url = new URL(a.href, location.href);
    if (url.origin !== location.origin) return;
    if (url.pathname === location.pathname && url.hash) return;

    if (document.startViewTransition) {
      e.preventDefault();
      document.startViewTransition(() => { location.href = a.href; });
    }
  });
})();