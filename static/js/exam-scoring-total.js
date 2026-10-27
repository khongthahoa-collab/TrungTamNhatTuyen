(function () {
  const total = document.querySelector('[data-scoring-total]');
  const form = total.closest('form');
  const format = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 4 });
  function updateTotal() {
    const mode = form.querySelector('[name="scoring_mode"]:checked')?.value;
    const selector = {
      question_custom: '#customQuestionPoints input',
      section_custom: '#customSectionPoints input',
    }[mode];
    if (!selector) {
      total.textContent = '10 điểm';
      return;
    }
    const fields = [...form.querySelectorAll(selector)];
    if (fields.some(input => !Number.isFinite(input.valueAsNumber))) {
      total.textContent = 'Chưa đủ dữ liệu';
      return;
    }
    const sum = fields.reduce((value, input) => value + input.valueAsNumber, 0);
    total.textContent = `${format.format(sum)} điểm`;
  }
  form.addEventListener('input', updateTotal);
  form.addEventListener('change', updateTotal);
  form.addEventListener('exam:points-updated', updateTotal);
  updateTotal();
})();
