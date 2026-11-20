(() => {
  const toggle = document.querySelector('.nav-toggle');
  const nav = document.querySelector('.main-nav');
  if (toggle && nav) {
    toggle.addEventListener('click', () => {
      const open = nav.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', String(open));
      toggle.textContent = open ? 'Close' : 'Menu';
    });
  }
  const banner = document.getElementById('cookie-banner');
  const customPanel = document.getElementById('cookie-custom-panel');
  const cookie = (name) => document.cookie.split('; ').find((item) => item.startsWith(name + '='))?.split('=').slice(1).join('=') || '';
  const saveCookie = (name, value) => {
    const secure = location.protocol === 'https:' ? '; Secure' : '';
    document.cookie = `${name}=${encodeURIComponent(value)}; Max-Age=31536000; Path=/; SameSite=Lax${secure}`;
  };
  const analytics = document.getElementById('cookie-analytics');
  const hideCookiePanel = () => { if (banner) banner.hidden = true; if (customPanel) customPanel.hidden = true; };
  const setChoices = (allowAnalytics, mode) => {
    saveCookie('schools_analytics', allowAnalytics ? '1' : '0');
    saveCookie('schools_cookie_consent', mode);
    hideCookiePanel();
    window.location.reload();
  };
  if (banner) {
    if (!cookie('schools_cookie_consent')) banner.hidden = false;
    if (analytics) analytics.checked = cookie('schools_analytics') === '1';
    document.querySelectorAll('[data-cookie-all]').forEach((button) => button.addEventListener('click', () => setChoices(true, 'all')));
    document.querySelectorAll('[data-cookie-essential]').forEach((button) => button.addEventListener('click', () => setChoices(false, 'essential')));
    document.querySelectorAll('[data-cookie-customize]').forEach((button) => button.addEventListener('click', () => { if (customPanel) customPanel.hidden = false; }));
    document.querySelectorAll('[data-cookie-save]').forEach((button) => button.addEventListener('click', () => setChoices(Boolean(analytics?.checked), 'custom')));
    document.querySelectorAll('[data-cookie-cancel]').forEach((button) => button.addEventListener('click', () => { if (customPanel) customPanel.hidden = true; }));
    document.querySelectorAll('[data-open-cookie-settings]').forEach((button) => button.addEventListener('click', () => {
      banner.hidden = false;
      if (customPanel) customPanel.hidden = false;
      if (analytics) analytics.checked = cookie('schools_analytics') === '1';
      banner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }));
  }
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => navigator.serviceWorker.register('/service-worker.js').catch(() => {}));
  }
})();
