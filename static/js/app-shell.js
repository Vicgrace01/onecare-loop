// App shell — sidebar toggle, user menu, auth check

(async function initShell() {
  // Load user
  try {
    const r = await fetch('/auth/me');
    if (!r.ok) {
      window.location.href = '/login';
      return;
    }
    const j = await r.json();
    const user = j.user;
    const initials = (user.name || user.email).split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();
    document.getElementById('user-avatar').textContent = initials;
    document.getElementById('user-name').textContent = user.name || user.email;
    document.getElementById('user-role').textContent = user.role + (user.org ? ' · ' + user.org : '');
  } catch (e) {
    window.location.href = '/login';
  }

  // Sidebar collapse
  const shell = document.querySelector('.shell');
  const toggle = document.getElementById('sidebar-toggle');
  if (toggle) {
    toggle.onclick = () => {
      if (window.innerWidth < 900) {
        shell.classList.toggle('mobile-open');
      } else {
        shell.classList.toggle('collapsed');
        localStorage.setItem('sidebar-collapsed', shell.classList.contains('collapsed'));
      }
    };
    if (localStorage.getItem('sidebar-collapsed') === 'true' && window.innerWidth >= 900) {
      shell.classList.add('collapsed');
    }
  }

  // User menu
  const menuBtn = document.getElementById('user-menu-btn');
  const menu = document.getElementById('user-menu');
  if (menuBtn) {
    menuBtn.onclick = (e) => {
      e.stopPropagation();
      menu.classList.toggle('open');
    };
    document.addEventListener('click', () => menu.classList.remove('open'));
  }

  // Logout
  const logout = document.getElementById('logout-btn');
  if (logout) {
    logout.onclick = async () => {
      await fetch('/auth/logout', { method: 'POST' });
      window.location.href = '/';
    };
  }
})();

// Toast helper
window.toast = function (msg, type = '') {
  const c = document.getElementById('toasts');
  if (!c) return;
  const t = document.createElement('div');
  t.className = 'toast ' + type;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => {
    t.style.opacity = '0';
    t.style.transition = 'opacity 300ms';
    setTimeout(() => t.remove(), 300);
  }, 3000);
};