(() => {
  const body = document.body;
  const sidebar = document.getElementById('animator-sidebar');
  const mobileToggle = document.querySelector('.animator-menu-toggle');
  const collapseToggle = document.querySelector('.animator-sidebar-collapse');
  const backdrop = document.querySelector('.animator-sidebar-backdrop');

  if (!sidebar || !mobileToggle || !collapseToggle) return;

  const storageKey = 'animation-manager:animateur-sidebar-collapsed';
  const mobileQuery = window.matchMedia('(max-width: 700px)');

  const isMobile = () => mobileQuery.matches;

  const updateControls = () => {
    const mobileOpen = body.classList.contains('animator-sidebar-open');
    const collapsed = body.classList.contains('animator-sidebar-collapsed');
    mobileToggle.setAttribute('aria-expanded', String(mobileOpen));
    mobileToggle.setAttribute('aria-label', mobileOpen ? 'Fermer le menu' : 'Ouvrir le menu');
    collapseToggle.setAttribute('aria-label', collapsed ? 'Déplier le menu' : 'Replier le menu');
    collapseToggle.setAttribute('title', collapsed ? 'Déplier le menu' : 'Replier le menu');
    const icon = collapseToggle.querySelector('.material-symbols-outlined');
    if (icon) icon.textContent = collapsed ? 'menu' : 'menu_open';
    if (backdrop) backdrop.hidden = !mobileOpen;
  };

  const closeMobile = () => {
    body.classList.remove('animator-sidebar-open');
    updateControls();
  };

  const applyStoredDesktopState = () => {
    if (isMobile()) {
      body.classList.remove('animator-sidebar-collapsed');
      closeMobile();
      return;
    }
    body.classList.toggle('animator-sidebar-collapsed', localStorage.getItem(storageKey) === 'true');
    body.classList.remove('animator-sidebar-open');
    updateControls();
  };

  mobileToggle.addEventListener('click', () => {
    body.classList.toggle('animator-sidebar-open');
    updateControls();
  });

  collapseToggle.addEventListener('click', () => {
    if (isMobile()) {
      closeMobile();
      return;
    }
    const collapsed = body.classList.toggle('animator-sidebar-collapsed');
    localStorage.setItem(storageKey, String(collapsed));
    updateControls();
  });

  backdrop?.addEventListener('click', closeMobile);
  sidebar.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => {
    if (isMobile()) closeMobile();
  }));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeMobile();
  });
  mobileQuery.addEventListener?.('change', applyStoredDesktopState);

  applyStoredDesktopState();
})();
