/* Nhật Tuyền — Main JS */

// Flash messages stay until dismissed (via the close button) — some carry
// one-time info (e.g. a generated temp password) that must not disappear
// before the admin has a chance to read/copy it.

// Page-loading overlay: shown on real page navigations (link clicks, form
// submits) so a slow request reads as "loading" instead of "stuck/broken".
// Skips anything that isn't a full navigation (modals, collapses, tabs,
// #-anchors, new tabs, downloads, ajax forms that already preventDefault).
(function () {
  const overlay = document.getElementById('page-loading-overlay');
  if (!overlay) return;

  let hideTimer = null;
  function showLoading() {
    overlay.classList.remove('d-none');
    clearTimeout(hideTimer);
    // Safety net: never let the overlay get stuck (e.g. a download link,
    // or a submit that turned out not to navigate away).
    hideTimer = setTimeout(() => overlay.classList.add('d-none'), 20000);
  }
  function hideLoading() {
    overlay.classList.add('d-none');
    clearTimeout(hideTimer);
  }

  document.addEventListener('click', (e) => {
    const link = e.target.closest('a[href]');
    if (!link) return;
    if (link.target === '_blank' || link.hasAttribute('download')) return;
    if (link.hasAttribute('data-bs-toggle') || link.hasAttribute('data-bs-dismiss')) return;
    if (link.hasAttribute('data-no-loading')) return;
    const href = link.getAttribute('href');
    if (!href || href.startsWith('#') || href.startsWith('javascript:') ||
        href.startsWith('mailto:') || href.startsWith('tel:')) return;
    showLoading();
  });

  // Bubble phase (default) so any handler on the form itself (e.g. a fetch-based
  // submit that calls preventDefault) runs first; if it did, skip the overlay.
  document.addEventListener('submit', (e) => {
    if (e.defaultPrevented) return;
    if (e.target.hasAttribute && e.target.hasAttribute('data-no-loading')) return;
    showLoading();
  });

  // Covers back/forward-cache restores, where the overlay could otherwise
  // still be showing from the page that navigated away.
  window.addEventListener('pageshow', hideLoading);
})();

// Mark all present in attendance form
function markAllPresent() {
  document.querySelectorAll('.status-radio[value="present"]').forEach(r => {
    r.checked = true;
    r.dispatchEvent(new Event('change'));
  });
}

// Toggle school name field in score form
document.addEventListener('DOMContentLoaded', () => {
  const radios = document.querySelectorAll('input[name="score_source"]');
  const schoolGroup = document.getElementById('school-name-group');
  if (!radios.length || !schoolGroup) return;
  radios.forEach(r => {
    r.addEventListener('change', () => {
      schoolGroup.style.display = r.value === 'truong' ? '' : 'none';
    });
  });
  // Initial state
  const checked = document.querySelector('input[name="score_source"]:checked');
  if (checked) schoolGroup.style.display = checked.value === 'truong' ? '' : 'none';
});

// Teacher user-add form: toggle staff fields
document.addEventListener('DOMContentLoaded', () => {
  const roleSelect = document.getElementById('role-select');
  const teacherFields = document.getElementById('teacher-extra-fields');
  if (!roleSelect || !teacherFields) return;
  function updateTeacherFields() {
    teacherFields.style.display = roleSelect.value === 'teacher' ? '' : 'none';
  }
  roleSelect.addEventListener('change', updateTeacherFields);
  updateTeacherFields();
});

// Confirm dangerous actions
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('click', e => {
      if (!confirm(el.dataset.confirm)) e.preventDefault();
    });
  });
});

// Format number as VND while typing
function formatVnd(input) {
  let val = input.value.replace(/\D/g, '');
  input.title = val ? parseInt(val).toLocaleString('vi-VN') + ' ₫' : '';
}
