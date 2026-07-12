/* Nhật Tuyền — Main JS */

// Flash messages stay until dismissed (via the close button) — some carry
// one-time info (e.g. a generated temp password) that must not disappear
// before the admin has a chance to read/copy it.

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
