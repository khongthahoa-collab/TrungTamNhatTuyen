(() => {
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd').replace(/Đ/g, 'D').toLocaleLowerCase().trim();

  document.querySelectorAll('[data-student-filter]').forEach(container => {
    const search = container.querySelector('[data-student-search]');
    const only = container.querySelector('[data-student-only]');
    const rows = Array.from(container.querySelectorAll('[data-student-row]'));
    const empty = container.querySelector('[data-student-empty]');
    function filter() {
      const query = normalize(search.value);
      let visible = 0;
      rows.forEach(row => {
        const input = row.querySelector('[data-score-input]');
        const matchesOnly = !only?.checked || (input ? input.value === '' : row.dataset.failed === 'true');
        row.hidden = !normalize(row.dataset.studentName).includes(query) || !matchesOnly;
        if (!row.hidden) visible += 1;
      });
      if (empty) empty.hidden = visible > 0 || rows.length === 0;
    }
    search.addEventListener('input', filter);
    search.addEventListener('keydown', event => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      container.querySelector('[data-student-row]:not([hidden]) [data-score-input]')?.focus();
    });
    only?.addEventListener('change', filter);
    container.addEventListener('focusout', event => {
      const row = event.target.closest('[data-student-row]');
      if (only?.checked && row?.querySelector('[data-score-input]') && !row.contains(event.relatedTarget)) {
        filter();
      }
    });
    filter();
  });

  const form = document.getElementById('scoresForm');
  if (!form) return;
  const inputs = Array.from(form.querySelectorAll('[data-score-input]'));
  const count = document.getElementById('scoreEntryCount');
  const save = document.getElementById('scoreSave');
  const message = document.getElementById('scoreEntryMessage');
  const round = document.getElementById('exam_round');
  const semester = document.getElementById('semester');
  const type = document.getElementById('score_type');
  const date = document.getElementById('exam_date');
  const nextRounds = JSON.parse(type.dataset.nextRounds);
  const currentYear = date.value.slice(0, 4);
  let roundTouched = false;
  let dirty = false;
  let submitting = false;
  let initial;

  function updateCount() {
    const filled = inputs.filter(input => input.value !== '').length;
    count.textContent = `Đã nhập ${filled}/${inputs.length} học sinh`;
    save.disabled = filled === 0;
  }
  function suggestRound() {
    if (roundTouched) return;
    if (date.value.slice(0, 4) === currentYear) {
      round.value = nextRounds[semester.value]?.[type.value] || 1;
    } else {
      // A blank round lets the server choose the next round in the selected year.
      round.value = '';
    }
  }
  round.addEventListener('input', () => { roundTouched = round.value !== ''; });
  semester.addEventListener('change', suggestRound);
  type.addEventListener('change', suggestRound);
  date.addEventListener('change', suggestRound);
  form.addEventListener('invalid', event => {
    const row = event.target.closest('[data-student-row]');
    if (!row) return;
    const container = row.closest('[data-student-filter]');
    const search = container.querySelector('[data-student-search]');
    const only = container.querySelector('[data-student-only]');
    search.value = '';
    only.checked = false;
    search.dispatchEvent(new Event('input'));
  }, true);
  inputs.forEach((input, index) => {
    input.addEventListener('keydown', event => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      const next = inputs.slice(index + 1).find(item => !item.closest('[data-student-row]').hidden);
      if (next) next.focus();
      else save.focus();
    });
  });
  form.addEventListener('input', () => {
    dirty = new URLSearchParams(new FormData(form)).toString() !== initial;
    message.hidden = true;
    updateCount();
  });
  form.addEventListener('change', () => {
    dirty = new URLSearchParams(new FormData(form)).toString() !== initial;
  });
  form.addEventListener('submit', event => {
    const filled = inputs.filter(input => input.value !== '');
    if (!filled.length) {
      event.preventDefault();
      message.textContent = 'Nhập điểm cho ít nhất một học sinh trước khi lưu.';
      message.hidden = false;
      return;
    }
    const summary = `${type.selectedOptions[0].text} · ${semester.selectedOptions[0].text}\n`
      + `Ngày kiểm tra: ${date.value} · Lần: ${round.value || 'tự động'}\n`
      + `Lưu ${filled.length}/${inputs.length} học sinh. Các ô trống không được ghi điểm.`;
    if (!confirm(summary)) {
      event.preventDefault();
      return;
    }
    submitting = true;
  });
  window.addEventListener('beforeunload', event => {
    if (!dirty || submitting) return;
    event.preventDefault();
    event.returnValue = '';
    setTimeout(() => document.getElementById('page-loading-overlay')?.classList.add('d-none'), 0);
  });
  window.addEventListener('pageshow', () => {
    submitting = false;
    updateCount();
  });
  suggestRound();
  initial = new URLSearchParams(new FormData(form)).toString();
  updateCount();
})();
