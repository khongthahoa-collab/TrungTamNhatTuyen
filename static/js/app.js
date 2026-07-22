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

    // Freeze the submit button so a slow request can't be double-submitted by
    // an impatient double-tap. Runs only once we know the submission is
    // actually proceeding (defaultPrevented is false at this point) — a form
    // with its own failed client-side validation never reaches here, so it
    // can never get stuck disabled.
    const submitBtn = e.target.querySelector('button[type="submit"], input[type="submit"]');
    if (submitBtn && !submitBtn.disabled) {
      submitBtn.disabled = true;
      // "Đang xử lý..." label only on narrow (mobile) screens, where forms
      // are usually full-width and this is the only loading feedback close
      // to the user's thumb. On laptop/PC the full-page overlay above
      // already covers this, and many desktop buttons here are small
      // icon-only controls (search, filter toggles) that break/wrap badly
      // once text is injected into them — just disabling is enough there.
      if (window.innerWidth < 992) {
        submitBtn.dataset.originalHtml = submitBtn.innerHTML;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Đang xử lý...';
      }
      // Safety net matching the overlay's own timeout — never leave a button
      // stuck disabled if the page navigation stalls for some reason.
      setTimeout(() => {
        submitBtn.disabled = false;
        if (submitBtn.dataset.originalHtml !== undefined) {
          submitBtn.innerHTML = submitBtn.dataset.originalHtml;
        }
      }, 20000);
    }
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
