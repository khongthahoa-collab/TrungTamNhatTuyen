(function () {
  window.updateAbsenceWarnings = function (classId, warnings) {
    if (!Array.isArray(warnings)) throw new Error('Dữ liệu cảnh báo nghỉ học không hợp lệ.');
    document.querySelectorAll('[data-absence-class]').forEach(panel => {
      if (Number(panel.dataset.absenceClass) !== classId) return;
      const list = panel.querySelector('[data-absence-warning-list]');
      list.replaceChildren();
      warnings.forEach(warning => {
        const row = document.createElement('li');
        row.className = 'small mb-1';
        const name = document.createElement('strong');
        name.textContent = warning.student_name;
        row.append(name, ` · ${warning.class_name}: nghỉ ${warning.absence_count} buổi trong chu kỳ ${warning.cycle_number} `
          + `(đã điểm danh ${warning.completed_sessions}/${warning.cycle_size} buổi, `
          + `${warning.start_date} – ${warning.end_date}).`);
        list.append(row);
      });
      panel.classList.toggle('d-none', warnings.length === 0);
    });
  };
})();
