(() => {
  const form = document.querySelector('[data-availability-form]');
  if (!form) return;

  const updateDate = (date) => {
    const selected = date.querySelector('input:checked');
    date.querySelectorAll('.availability-option').forEach((option) => {
      option.classList.toggle('is-selected', option.querySelector('input') === selected);
    });
    const unset = date.querySelector('.availability-unset');
    if (unset) unset.hidden = Boolean(selected);
  };

  const updateWeek = (week) => {
    const dates = [...week.querySelectorAll('[data-availability-date]')];
    const selected = dates.map((date) => date.querySelector('input:checked')?.value);
    const total = dates.length;
    const available = selected.filter((value) => value === 'journee').length;
    const unavailable = selected.filter((value) => value === 'indisponible').length;
    const summary = week.querySelector('[data-week-summary]');
    if (!summary) return;
    if (!selected.every(Boolean)) summary.textContent = 'À renseigner';
    else if (available === total) summary.textContent = `${total} jours disponibles`;
    else if (unavailable === total) summary.textContent = 'Aucune disponibilité';
    else summary.textContent = `${available} jours disponibles sur ${total}`;
  };

  const refresh = () => {
    form.querySelectorAll('[data-availability-date]').forEach(updateDate);
    form.querySelectorAll('[data-availability-week]').forEach(updateWeek);
  };

  form.addEventListener('change', refresh);
  form.querySelectorAll('[data-week-value]').forEach((button) => {
    button.addEventListener('click', () => {
      const week = button.closest('[data-availability-week]');
      week.querySelectorAll('[data-availability-date]').forEach((date) => {
        const input = date.querySelector(`input[value="${button.dataset.weekValue}"]`);
        if (input) input.checked = true;
      });
      refresh();
    });
  });
  form.querySelector('[data-send-availability]')?.addEventListener('click', (event) => {
    const all = [...form.querySelectorAll('[data-availability-date]')];
    const zero = all.length && all.every((date) => date.querySelector('input:checked')?.value === 'indisponible');
    const confirmation = form.querySelector('[data-zero-confirmation]');
    if (zero && !window.confirm("Tu as indiqué n’être disponible sur aucune des dates proposées. Confirmer l’envoi ?")) {
      event.preventDefault();
      return;
    }
    if (confirmation) confirmation.value = zero ? '1' : '';
  });
  refresh();
})();
