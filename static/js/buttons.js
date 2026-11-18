window.ButtonEngine = {
  async run(button, opts) {
    if (!button || button.disabled) return null;
    const {
      action,
      loadingText = 'Working…',
      successText = 'Done',
      errorText = null,
      successDuration = 900,
      errorDuration = 1600,
    } = opts;

    const original = button.innerHTML;
    const originalMinWidth = button.offsetWidth;
    button.style.minWidth = originalMinWidth + 'px';
    button.disabled = true;
    button.classList.add('btn-loading');
    button.innerHTML = loadingText + '<span class="btn-spinner"></span>';

    try {
      const result = await action();
      button.classList.remove('btn-loading');
      button.classList.add('btn-success');
      button.innerHTML = '✓ ' + successText;
      
      // If GSAP is available, add a little bounce
      if (window.gsap) {
        gsap.fromTo(button, { scale: 0.98 }, { scale: 1, duration: 0.3, ease: 'back.out(2)' });
      }

      await new Promise(r => setTimeout(r, successDuration));
      return result;
    } catch (err) {
      button.classList.remove('btn-loading');
      button.classList.add('btn-error');
      button.innerHTML = '✗ ' + (errorText || err.message || 'Failed');
      await new Promise(r => setTimeout(r, errorDuration));
      throw err;
    } finally {
      button.classList.remove('btn-success', 'btn-error');
      button.disabled = false;
      button.style.minWidth = '';
      button.innerHTML = original;
    }
  },
};