(function () {
  const buttons = [...document.querySelectorAll('[data-attempt-filter]')];
  if (!buttons.length) return;
  let selected = 'all';
  const matches = (state, filter) => filter === 'all' || filter === 'original'
    || (filter === 'correct' ? state === 'correct' : ['wrong', 'partial', 'blank'].includes(state));
  function update() {
    const pane = document.querySelector('.tab-pane.active');
    if (!pane) return;
    const questions = [...pane.querySelectorAll('[data-attempt-state]')];
    buttons.forEach(button => {
      const active = button.dataset.attemptFilter === selected;
      button.setAttribute('aria-pressed', String(active));
      button.classList.toggle('btn-primary', active);
      button.classList.toggle('btn-outline-primary', !active && button.dataset.attemptFilter !== 'original');
      button.classList.toggle('btn-outline-secondary', !active && button.dataset.attemptFilter === 'original');
      const count = button.querySelector('[data-filter-count]');
      if (count) count.textContent = `(${questions.filter(q => matches(q.dataset.attemptState, button.dataset.attemptFilter)).length})`;
    });
    document.querySelectorAll('[data-attempt-state]').forEach(question => {
      question.hidden = !matches(question.dataset.attemptState, selected);
      question.querySelector('[data-attempt-original]').hidden = selected !== 'original';
    });
    document.querySelectorAll('[data-attempt-review]').forEach(el => { el.hidden = selected === 'original'; });
    document.querySelectorAll('[data-attempt-group]').forEach(group => {
      group.hidden = ![...group.querySelectorAll('[data-attempt-state]')].some(q => !q.hidden);
    });
    pane.querySelector('[data-attempt-empty]').hidden = questions.some(q => !q.hidden);
    document.querySelector('[data-attempt-filter-hint]').textContent = selected === 'original'
      ? 'Chỉ xem câu hỏi và lựa chọn, theo thứ tự học sinh đã nhận; không hiển thị bài làm, đáp án hoặc lời giải.'
      : 'Lọc trong phần đang xem. “Sai” gồm sai, đúng một phần và chưa trả lời; không gồm tự luận chờ chấm.';
  }
  buttons.forEach(button => button.addEventListener('click', () => {
    selected = button.dataset.attemptFilter;
    update();
  }));
  document.querySelectorAll('[data-bs-toggle="tab"]').forEach(tab => tab.addEventListener('shown.bs.tab', update));
  const jumpGroup = document.getElementById('examJumpGroup');
  const jumpQuestion = document.getElementById('examJumpQuestion');
  const jumpGo = document.getElementById('examJumpGo');
  const hint = document.getElementById('examJumpHint');
  function groupQuestions() {
    const group = [...document.querySelectorAll('[data-attempt-group]')]
      .find(el => el.dataset.attemptGroup === jumpGroup.value);
    return group ? [...group.querySelectorAll('[data-question-position]')] : [];
  }
  function updateJumpLimit() {
    const questions = groupQuestions();
    jumpQuestion.max = String(Math.max(0, ...questions.map(q => Number(q.dataset.questionPosition))));
    jumpGo.disabled = questions.length === 0;
    hint.textContent = '';
  }
  function jump() {
    const number = Number(jumpQuestion.value);
    const target = groupQuestions().find(q => Number(q.dataset.questionPosition) === number);
    if (!Number.isInteger(number) || !target) {
      hint.textContent = `Nhập số câu từ 1 đến ${jumpQuestion.max} trong nhóm đã chọn.`;
      jumpQuestion.focus();
      return;
    }
    hint.textContent = '';
    if (!matches(target.dataset.attemptState, selected)) selected = 'all';
    const pane = target.closest('.tab-pane');
    const reveal = () => {
      update();
      target.focus({ preventScroll: true });
      target.scrollIntoView({ block: 'start', behavior: 'auto' });
    };
    if (!pane.classList.contains('active')) {
      const tab = document.querySelector(`[data-bs-target="#${pane.id}"]`);
      tab.addEventListener('shown.bs.tab', () => requestAnimationFrame(reveal), { once: true });
      bootstrap.Tab.getOrCreateInstance(tab).show();
    } else reveal();
  }
  jumpGroup.addEventListener('change', updateJumpLimit);
  jumpGo.addEventListener('click', jump);
  jumpQuestion.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      jump();
    }
  });
  updateJumpLimit();
  update();
})();
