(function () {
  const contentForm = document.getElementById('exam-form');
  const settingsForm = document.getElementById('exam-settings-form');
  const showSettings = () => bootstrap.Tab.getOrCreateInstance(document.getElementById('examSettingsTab')).show();
  function syncPoints(groups) {
    const makeField = (name, label, oldValues) => {
      const column = document.createElement('div');
      column.className = 'col-6 col-md-4';
      const caption = document.createElement('label');
      caption.className = 'form-label small mb-1';
      caption.htmlFor = name;
      caption.textContent = label;
      const input = document.createElement('input');
      input.className = 'form-control form-control-sm';
      input.type = 'number';
      input.min = '0.01';
      input.max = '1000';
      input.step = '0.01';
      input.id = input.name = name;
      input.value = oldValues.get(name) ?? '1';
      column.append(caption, input);
      return column;
    };
    for (const [id, prefix] of [['customQuestionPoints', 'question_points'], ['customSectionPoints', 'section_points']]) {
      const container = document.getElementById(id);
      const oldValues = new Map([...container.querySelectorAll('input')].map(el => [el.name, el.value]));
      const heading = container.firstElementChild;
      container.replaceChildren(heading);
      groups.forEach((group, gi) => {
        const row = document.createElement('div');
        row.className = 'row g-2 mb-2';
        if (prefix === 'question_points') {
          const title = document.createElement('div');
          title.className = 'small fw-semibold mt-2';
          title.textContent = group.title;
          container.append(title);
          group.questions.forEach((question, qi) => row.append(makeField(`${prefix}_${gi}_${qi}`, `Câu ${qi + 1}`, oldValues)));
        } else row.append(makeField(`${prefix}_${gi}`, group.title, oldValues));
        container.append(row);
      });
    }
    settingsForm.dispatchEvent(new Event('exam:points-updated'));
  }
  function syncContent() {
    const event = new Event('submit', { cancelable: true });
    contentForm.dispatchEvent(event);
    if (event.defaultPrevented) {
      bootstrap.Tab.getOrCreateInstance(document.getElementById('examContentTab')).show();
      return false;
    }
    settingsForm.elements.namedItem('title').value = document.getElementById('titleField').value;
    settingsForm.elements.namedItem('groups_json').value = document.getElementById('groupsField').value;
    syncPoints(JSON.parse(document.getElementById('groupsField').value).groups);
    return true;
  }
  // Synthetic submit only serializes the editor; native submits save both tabs.
  contentForm.addEventListener('submit', event => {
    if (!event.isTrusted || event.defaultPrevented) return;
    event.preventDefault();
    showSettings();
    if (syncContent()) settingsForm.requestSubmit();
  });
  settingsForm.addEventListener('submit', event => {
    if (!syncContent()) event.preventDefault();
  });
  settingsForm.addEventListener('invalid', showSettings, true);
  document.getElementById('examSettingsTab').addEventListener('shown.bs.tab', () => {
    settingsForm.querySelector('[data-settings-title]').textContent = document.getElementById('examTitle').value;
    contentForm.dispatchEvent(new Event('exam:serialize'));
    syncPoints(JSON.parse(document.getElementById('groupsField').value).groups);
  });
})();
