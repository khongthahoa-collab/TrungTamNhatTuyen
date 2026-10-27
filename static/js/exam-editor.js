(function () {
  const config = JSON.parse(document.getElementById('examEditorConfig').textContent);
  const form = document.getElementById('exam-form');
  const editor = document.getElementById('rawTextEditor');
  const preview = document.getElementById('groupsContainer');
  const title = document.getElementById('examTitle');
  const draftStatus = document.getElementById('localDraftStatus');
  if (!config.localDraft) draftStatus.classList.add('d-none');
  const errorBox = document.getElementById('examEditorError');
  const composer = document.getElementById('examComposer');
  const letters = ['A', 'B', 'C', 'D', 'E', 'F'];
  const statementLetters = ['a', 'b', 'c', 'd', 'e', 'f'];
  let groups = config.groups;
  let sourceOffsets = [];
  let draftTimer;
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const text = value => `<span class="exam-math exam-preview-content">${escapeHtml(value)}</span>`;

  function showError(message) {
    errorBox.textContent = message;
    errorBox.classList.remove('d-none');
    errorBox.scrollIntoView({ block: 'center' });
  }

  function serialize(allGroups) {
    const lines = [];
    allGroups.forEach(group => {
      lines.push(`## ${group.title || 'Phần thi'} {${group.type}}`);
      if (group.instruction) lines.push(group.instruction);
      group.questions.forEach((q, i) => {
        lines.push('', `Câu ${i + 1}: ${q.text || ''}`);
        if (group.type === 'mcq') {
          (q.options || []).forEach((option, oi) => lines.push(`${letters[oi]}. ${option}`));
          lines.push(`Đáp án: ${letters[q.correct_index] || 'A'}`);
        } else if (group.type === 'true_false') {
          (q.statements || []).forEach((st, si) => lines.push(`${statementLetters[si]}) ${st.text}`));
          lines.push(`Đáp án: ${(q.statements || []).map((st, si) => `${statementLetters[si]})${st.correct ? 'Đ' : 'S'}`).join(' ')}`);
        } else if (group.type === 'short_answer') {
          lines.push(`Đáp án: ${(q.accepted_answers || []).join(' | ')}`);
        }
        if (q.explanation) lines.push(`Giải thích: ${q.explanation}`);
      });
      lines.push('');
    });
    return lines.join('\n');
  }

  function sectionType(value) {
    const normalized = value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[đĐ]/g, 'd')
      .toUpperCase().replace(/[^A-Z0-9]+/g, ' ').trim();
    if (/TRA LOI NGAN|SHORT ANSWER/.test(normalized)) return 'short_answer';
    if (/TU LUAN|ESSAY/.test(normalized)) return 'essay';
    if (/DUNG SAI|TRUE FALSE/.test(normalized)) return 'true_false';
    if (/TIM LOI SAI|ERROR IDENTIFICATION/.test(normalized)) return 'error_id';
    return 'mcq';
  }

  function parse(rawText) {
    const result = [];
    const offsets = [];
    let group = null;
    let question = null;
    let placeholder = false;
    let explanationMode = false;
    let offset = 0;
    function flushQuestion() {
      if (question && question.text.trim()) group.questions.push(question);
      question = null;
      explanationMode = false;
      placeholder = false;
    }
    function startQuestion(value, position) {
      question = { text: value || `Câu ${group.questions.length + 1}`, explanation: '' };
      if (group.type === 'mcq') Object.assign(question, { options: [], correct_index: 0 });
      if (group.type === 'true_false') question.statements = [];
      if (group.type === 'short_answer') question.accepted_answers = [];
      placeholder = !value;
      offsets[result.length - 1].push(position);
    }
    function startGroup(name, type) {
      group = { title: name, type, instruction: '', questions: [] };
      result.push(group);
      offsets.push([]);
    }
    rawText.split('\n').forEach(raw => {
      const line = raw.trim();
      const position = offset + raw.indexOf(line);
      offset += raw.length + 1;
      if (!line) return;
      const heading = line.match(/^##\s*(.+?)\s*(?:\{(mcq|true_false|short_answer|essay|error_id)\})?\s*$/i);
      const naturalHeading = /^(?:PHẦN|SECTION)\s+\d+\s*[.:)-]?\s+.+$/i.test(line);
      if (heading || naturalHeading) {
        flushQuestion();
        const name = heading ? heading[1].trim() : line;
        startGroup(name, heading?.[2]?.toLowerCase() || sectionType(name));
        return;
      }
      if (!group) startGroup('Phần 1', 'mcq');
      const questionLine = line.match(/^C[aâ]u\s*(\d+)\s*(?:[:.]\s*(.*))?$/i);
      const numberedLine = line.match(/^(\d+)[.)]?\s*(.*)$/);
      if (questionLine || numberedLine) {
        flushQuestion();
        startQuestion((questionLine || numberedLine)[2] || '', position);
        return;
      }
      if (/^Trả\s*lời\s*:\s*$/i.test(line)) return;
      const answer = line.match(/^Đáp\s*án\s*:\s*(.*)$/i);
      if (answer && question) {
        explanationMode = false;
        const value = answer[1];
        if (group.type === 'mcq') question.correct_index = Math.max(0, letters.indexOf(value.trim().toUpperCase()));
        else if (group.type === 'short_answer') question.accepted_answers = value.split('|').map(s => s.trim()).filter(Boolean);
        else if (group.type === 'true_false') {
          value.split(/\s+/).forEach(part => {
            const match = part.match(/^([a-f])\)(Đ|S)$/i);
            const index = match ? statementLetters.indexOf(match[1].toLowerCase()) : -1;
            if (question.statements[index]) question.statements[index].correct = match[2].toUpperCase() === 'Đ';
          });
        }
        return;
      }
      const explanation = line.match(/^(?:Giải\s*thích(?:\s*chi\s*tiết)?|Lời\s*giải)\s*:\s*(.*)$/i);
      if (question && (explanation || /^(?:Giải\s*thích\s*chi\s*tiết\s*câu\s*các\s*ý|Giải\s*thích\s*chi\s*tiết)\s*$/i.test(line))) {
        explanationMode = true;
        question.explanation = explanation?.[1]?.trim() || '';
        return;
      }
      if (explanationMode && question) {
        question.explanation += (question.explanation ? '\n' : '') + line;
        return;
      }
      const option = line.match(/^(\*)?\s*([A-F])(?:[).:]|\s|$)\s*(.*)$/i);
      if (option && ['mcq', 'true_false'].includes(group.type)) {
        if (!question) startQuestion('', position);
        if (group.type === 'mcq') {
          question.options.push(option[3]);
          if (option[1]) question.correct_index = question.options.length - 1;
        } else question.statements.push({ text: option[3], correct: Boolean(option[1]) });
        return;
      }
      if (!question) group.instruction += (group.instruction ? '\n' : '') + line;
      else if (placeholder) {
        question.text = line;
        placeholder = false;
      } else question.text += (question.text ? '\n' : '') + line;
    });
    flushQuestion();
    return { groups: result, offsets };
  }

  function errorIdText(value) {
    return escapeHtml(value).replace(/\[(\*?)([A-F]):([^\]]*)\]/g, (_, correct, label, content) =>
      `<span class="exam-error-segment ${correct ? 'text-success fw-bold' : ''}"><span class="exam-error-underline">${content}</span><span class="exam-error-label">${label}</span></span>`);
  }

  function renderQuestion(group, question, gi, qi) {
    let answers = '';
    if (group.type === 'mcq') {
      answers = `<div class="exam-preview-options${config.isAdmin && question.options.length === 4 ? ' exam-review-options' : ''}">${question.options.map((option, oi) =>
        `<div class="exam-preview-option${oi === question.correct_index ? ' is-correct' : ''}">${letters[oi]}. ${text(option)}</div>`).join('')}</div>`;
    } else if (group.type === 'true_false') {
      answers = question.statements.map((st, si) =>
        `<div class="exam-preview-option mb-1 ${st.correct ? 'is-correct' : 'is-incorrect'}">${statementLetters[si]}) ${text(st.text)}<span class="visually-hidden"> (${st.correct ? 'Đúng' : 'Sai'})</span></div>`).join('');
    } else if (group.type === 'short_answer') {
      answers = `<div class="small text-success">Đáp án: ${text(question.accepted_answers.join(' | '))}</div>`;
    } else if (group.type === 'essay') answers = '<div class="small text-muted">Tự luận · Chấm tay</div>';
    else if (group.type === 'error_id') {
      const matches = [...question.text.matchAll(/\[(\*?)([A-F]):([^\]]*)\]/g)];
      const correct = matches.find(match => match[1])?.[2];
      answers = `<div class="exam-error-choices" role="group" aria-label="Các lựa chọn tìm lỗi sai">${
        [...new Set(matches.map(match => match[2]))].map(label =>
          `<span class="btn btn-sm ${label === correct ? 'btn-success' : 'btn-outline-secondary'}">${label}${label === correct ? '<span class="visually-hidden"> — Đáp án đúng</span>' : ''}</span>`
        ).join('')}</div>`;
    }
    const body = group.type === 'error_id'
      ? `<span class="exam-math exam-preview-content">${errorIdText(question.text)}</span>` : text(question.text);
    return `<article class="card border-0 shadow-sm mb-3 exam-preview-card" data-anchor="${gi}-${qi}">
      <div class="card-body">
        <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
          <h3 class="h6 fw-bold mb-0">Câu ${qi + 1}</h3>
          <button type="button" class="btn btn-outline-secondary btn-sm" data-source-group="${gi}" data-source-question="${qi}">Sửa trong văn bản</button>
        </div>
        <div class="mb-2">${body}</div>${answers}
        ${question.explanation ? `<div class="border-top mt-3 pt-2 small"><strong>Hướng dẫn giải</strong><div>${text(question.explanation)}</div></div>` : ''}
      </div></article>`;
  }

  function refreshPreview() {
    const parsed = parse(editor.value);
    groups = parsed.groups;
    sourceOffsets = parsed.offsets;
    preview.innerHTML = groups.length ? groups.map((group, gi) =>
      `<section class="mb-3"><h2 class="h6 fw-bold text-success">${escapeHtml(group.title)}</h2>
      ${group.instruction ? `<p class="small">${text(group.instruction)}</p>` : ''}
      ${group.questions.map((q, qi) => renderQuestion(group, q, gi, qi)).join('')}
      ${group.questions.length ? '' : '<p class="small text-muted">Chưa nhận diện được câu hỏi. Bắt đầu bằng “Câu 1:”.</p>'}</section>`).join('')
      : '<p class="text-muted">Nhập hoặc dán nội dung ở vùng văn bản để xem trước đề thi.</p>';
    window.scheduleExamMathTypeset(preview);
    refreshJumpGroups();
  }

  const jumpGroup = document.getElementById('examJumpGroup');
  const jumpQuestion = document.getElementById('examJumpQuestion');
  const jumpHint = document.getElementById('examJumpHint');
  function refreshJumpGroups() {
    const previous = jumpGroup.value;
    jumpGroup.innerHTML = groups.map((group, gi) =>
      `<option value="${gi}" title="${escapeHtml(group.title || 'Phần thi')}">${gi + 1}</option>`).join('');
    if (previous && Number(previous) < groups.length) jumpGroup.value = previous;
    updateJumpMax();
  }
  function updateJumpMax() {
    const count = groups[Number(jumpGroup.value)]?.questions.length || 1;
    jumpQuestion.max = String(count);
  }
  function jumpToQuestion() {
    jumpHint.textContent = '';
    const gi = Number(jumpGroup.value);
    const group = groups[gi];
    const qi = parseInt(jumpQuestion.value, 10) - 1;
    if (!group || !group.questions.length) {
      jumpHint.textContent = 'Chưa có nhóm câu hỏi nào để di chuyển đến.';
      return;
    }
    if (!Number.isInteger(qi) || qi < 0 || qi >= group.questions.length) {
      jumpHint.textContent = `Nhóm này chỉ có ${group.questions.length} câu. Hãy nhập số từ 1 đến ${group.questions.length}.`;
      return;
    }
    const card = preview.querySelector(`[data-anchor="${gi}-${qi}"]`);
    if (card) {
      const scroller = preview.closest('.exam-compose-preview') || preview;
      const box = scroller.getBoundingClientRect();
      scroller.scrollTo({ top: scroller.scrollTop + card.getBoundingClientRect().top - box.top - 8, behavior: 'smooth' });
      preview.querySelectorAll('.is-jump-target').forEach(el => el.classList.remove('is-jump-target'));
      card.classList.add('is-jump-target');
      setTimeout(() => card.classList.remove('is-jump-target'), 1800);
    }
    const offset = sourceOffsets[gi]?.[qi];
    if (Number.isInteger(offset)) {
      const lineHeight = parseFloat(getComputedStyle(editor).lineHeight) || 20;
      editor.setSelectionRange(offset, offset);
      editor.scrollTop = Math.max(0, editor.value.slice(0, offset).split('\n').length * lineHeight - editor.clientHeight / 3);
      if (editor.offsetParent !== null && composer.dataset.activePane === 'source') editor.focus({ preventScroll: true });
    }
  }
  jumpGroup.addEventListener('change', updateJumpMax);
  document.getElementById('examJumpGo').addEventListener('click', jumpToQuestion);
  jumpQuestion.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      jumpToQuestion();
    }
  });

  function saveDraft() {
    refreshState();
    if (!config.localDraft) return true;
    try {
      localStorage.setItem(config.draftKey, JSON.stringify({ title: title.value, groups, rawText: editor.value, savedAt: Date.now() }));
      draftStatus.textContent = 'Đã tự động lưu bản nháp trên thiết bị này.';
      draftStatus.classList.remove('text-danger');
      return true;
    } catch (error) {
      console.error('Không thể lưu bản nháp đề thi.', error);
      draftStatus.textContent = 'Không thể lưu nháp trên thiết bị. Hãy tiếp tục để lưu lên hệ thống.';
      draftStatus.classList.add('text-danger');
      return false;
    }
  }
  function refreshState() {
    const parsed = parse(editor.value);
    groups = parsed.groups;
    sourceOffsets = parsed.offsets;
  }
  function scheduleDraft() {
    if (!config.localDraft) return;
    draftStatus.textContent = 'Đang lưu bản nháp trên thiết bị…';
    clearTimeout(draftTimer);
    draftTimer = setTimeout(saveDraft, 350);
  }
  function setPane(pane) {
    composer.dataset.activePane = pane;
    document.querySelectorAll('[data-editor-pane]').forEach(button => {
      const active = button.dataset.editorPane === pane;
      button.setAttribute('aria-pressed', String(active));
      button.classList.toggle('btn-primary', active);
      button.classList.toggle('btn-outline-primary', !active);
    });
  }
  document.querySelectorAll('[data-editor-pane]').forEach(button => button.addEventListener('click', () => {
    refreshPreview();
    setPane(button.dataset.editorPane);
  }));
  preview.addEventListener('click', event => {
    const button = event.target.closest('[data-source-question]');
    if (!button) return;
    setPane('source');
    const offset = sourceOffsets[Number(button.dataset.sourceGroup)]?.[Number(button.dataset.sourceQuestion)];
    if (!Number.isInteger(offset)) {
      showError('Không tìm thấy vị trí câu hỏi trong văn bản. Hãy kiểm tra lại nội dung.');
      return;
    }
    editor.focus({ preventScroll: true });
    editor.setSelectionRange(offset, offset);
    editor.scrollTop = Math.max(0, editor.value.slice(0, offset).split('\n').length * parseFloat(getComputedStyle(editor).lineHeight) - editor.clientHeight / 3);
  });
  let previewTimer;
  editor.addEventListener('input', () => {
    errorBox.classList.add('d-none');
    clearTimeout(previewTimer);
    previewTimer = setTimeout(refreshPreview, 180);
    scheduleDraft();
  });
  title.addEventListener('input', () => {
    errorBox.classList.add('d-none');
    scheduleDraft();
  });
  window.addEventListener('pagehide', saveDraft);
  document.querySelectorAll('[data-exam-editor-exit]').forEach(link => link.addEventListener('click', event => {
    if (!config.localDraft) return;
    if (!confirm('Thoát và lưu đề? Nội dung sẽ được lưu nháp trên thiết bị để khôi phục khi quay lại.') || !saveDraft()) event.preventDefault();
  }));
  form.addEventListener('submit', event => {
    refreshState();
    document.getElementById('titleField').value = title.value.trim();
    document.getElementById('groupsField').value = JSON.stringify({ groups });
    saveDraft();
    if (!title.value.trim() || !groups.some(group => group.questions.some(q => q.text.trim()))) {
      event.preventDefault();
      showError(!title.value.trim() ? 'Vui lòng nhập tên đề thi.' : 'Vui lòng nhập ít nhất một câu hỏi có nội dung.');
    }
  });
  editor.value = serialize(groups);
  try {
    if (!config.localDraft) localStorage.removeItem(config.draftKey);
    const draft = config.localDraft ? JSON.parse(localStorage.getItem(config.draftKey) || 'null') : null;
    if (draft && Array.isArray(draft.groups) && Date.now() - draft.savedAt < 7 * 86400000) {
      if (confirm('Tìm thấy bản nháp trên thiết bị. Bạn có muốn khôi phục không?')) {
        title.value = draft.title || '';
        editor.value = typeof draft.rawText === 'string' ? draft.rawText : serialize(draft.groups);
      } else localStorage.removeItem(config.draftKey);
    } else if (draft) localStorage.removeItem(config.draftKey);
  } catch (error) {
    console.warn('Không thể đọc bản nháp đề thi.', error);
    draftStatus.textContent = 'Không thể đọc bản nháp trên thiết bị. Nội dung hiện tại chưa bị thay đổi.';
    draftStatus.classList.add('text-danger');
  }
  refreshPreview();
  const toolbar = document.querySelector('.exam-editor-toolbar');
  if (toolbar) new ResizeObserver(() => {
    document.documentElement.style.setProperty('--exam-editor-toolbar-height', `${toolbar.offsetHeight}px`);
  }).observe(toolbar);

  const sampleSelect = document.getElementById('examSampleSelect');
  const applySample = document.getElementById('applyExamSample');
  const sampleStatus = document.getElementById('examSampleStatus');
  const retrySamples = document.getElementById('retryExamSamples');
  let samples = [];
  async function loadSamples() {
    sampleStatus.textContent = 'Đang tải nội dung mẫu…';
    retrySamples.classList.add('d-none');
    sampleSelect.disabled = true;
    applySample.disabled = true;
    try {
      const response = await fetch(config.samplesUrl, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!Array.isArray(data.templates) || !data.templates.every(sample =>
        Number.isInteger(sample.id) && typeof sample.name === 'string' && typeof sample.content === 'string')) {
        throw new Error('Dữ liệu mẫu không hợp lệ.');
      }
      samples = data.templates;
      sampleSelect.replaceChildren(new Option(samples.length ? 'Chọn nội dung mẫu' : 'Chưa có nội dung mẫu', ''));
      samples.forEach(sample => sampleSelect.add(new Option(sample.name, String(sample.id))));
      sampleSelect.disabled = !samples.length;
      sampleStatus.textContent = samples.length ? 'Áp dụng mẫu sẽ thay nội dung câu hỏi, không đổi tên đề.' : 'Admin chưa tạo nội dung mẫu.';
    } catch (error) {
      console.error('Không thể tải nội dung mẫu.', error);
      sampleStatus.textContent = 'Không thể tải nội dung mẫu. Hãy thử tải lại. Bạn vẫn có thể nhập đề.';
      sampleSelect.replaceChildren(new Option('Không tải được mẫu', ''));
      retrySamples.classList.remove('d-none');
    }
  }
  sampleSelect.addEventListener('change', () => { applySample.disabled = !sampleSelect.value; });
  retrySamples.addEventListener('click', loadSamples);
  applySample.addEventListener('click', () => {
    const sample = samples.find(item => String(item.id) === sampleSelect.value);
    if (!sample) {
      showError('Vui lòng chọn nội dung mẫu hợp lệ.');
      return;
    }
    if (editor.value.trim() && !confirm('Áp dụng mẫu sẽ thay thế toàn bộ nội dung câu hỏi đang nhập. Tiếp tục?')) return;
    editor.value = sample.content;
    errorBox.classList.add('d-none');
    refreshPreview();
    scheduleDraft();
    setPane('source');
    editor.focus();
  });
  loadSamples();
})();
