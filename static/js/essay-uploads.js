(() => {
  const form = document.getElementById('examForm');
  let pending = 0;
  let frozen = false;
  let choosingUntil = 0;
  let choosingTimer;
  const reservedUploads = new Map();
  let queue = Promise.resolve();
  const csrf = form.querySelector('[name="csrf_token"]').value;
  const preview = document.getElementById('essayImagePreview');
  const previewImage = preview.querySelector('img');
  const previewError = preview.querySelector('[data-image-error]');
  preview.querySelector('[data-close-image]').addEventListener('click', () => preview.close());
  previewImage.addEventListener('error', () => previewError.classList.remove('d-none'));
  form.addEventListener('click', event => {
    const link = event.target.closest('.essay-image-card a');
    if (!link) return;
    event.preventDefault();
    previewError.classList.add('d-none');
    previewImage.src = link.href;
    preview.showModal();
  });

  window.examEssayUploads = {
    isBusy: () => pending > 0,
    hasErrors: () => Boolean(form.querySelector('.essay-upload-error')),
    isChoosing: () => Date.now() < choosingUntil,
    freeze: () => {
      frozen = true;
      form.querySelectorAll('.essay-image-input, .essay-image-actions button').forEach(input => {
        input.disabled = true;
      });
    },
  };

  function finishChoosing() {
    choosingUntil = 0;
    clearTimeout(choosingTimer);
  }

  function startChoosing() {
    finishChoosing();
    choosingUntil = Date.now() + 120000;
    choosingTimer = setTimeout(() => {
      finishChoosing();
      if (document.hidden || !document.hasFocus()) {
        window.dispatchEvent(new Event('essay-picker-expired'));
      }
    }, 120000);
  }

  async function request(url, options) {
    const response = await fetch(url, {
      ...options, credentials: 'same-origin',
      headers: { ...options.headers, 'X-CSRFToken': csrf },
    });
    if (!response.headers.get('content-type')?.includes('application/json')) {
      throw new Error('Không thể cập nhật ảnh. Phiên đăng nhập có thể đã hết hạn; hãy kiểm tra kết nối và đăng nhập.');
    }
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || `Không thể cập nhật ảnh (HTTP ${response.status}).`);
    return body;
  }

  async function compress(file) {
    if (file.size > 10 * 1024 * 1024) throw new Error('Ảnh gốc không được vượt 10 MB.');
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      throw new Error('Hãy chọn ảnh JPEG, PNG hoặc WebP. Ảnh HEIC cần chuyển sang JPEG trước.');
    }
    let bitmap;
    try {
      bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
    } catch (error) {
      console.error('Cannot decode essay photo:', error);
      throw new Error('Không đọc được ảnh trên thiết bị này. Hãy chọn ảnh JPEG/PNG khác.');
    }
    const scale = Math.min(1, 2000 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext('2d');
    if (!context) {
      bitmap.close();
      throw new Error('Thiết bị không thể xử lý ảnh. Hãy thử trình duyệt khác.');
    }
    context.fillStyle = '#fff';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.85));
    canvas.width = canvas.height = 1;
    if (!blob || blob.size >= 1024 * 1024) {
      throw new Error('Ảnh sau nén vượt 1 MB. Hãy chụp riêng từng trang, tránh ảnh toàn cảnh.');
    }
    return blob;
  }

  function button(text, label, handler) {
    const element = document.createElement('button');
    element.type = 'button';
    element.className = 'btn btn-outline-secondary btn-sm';
    element.textContent = text;
    element.setAttribute('aria-label', label);
    element.addEventListener('click', handler);
    return element;
  }

  function schedule(panel, action, description, discard = () => {}) {
    if (frozen) return;
    pending += 1;
    const status = panel.querySelector('.essay-upload-status');
    status.textContent = 'Đang xử lý ảnh… Hãy đợi trước khi nộp bài.';
    queue = queue.then(async () => {
      if (frozen) return;
      try {
        await action();
        status.classList.remove('text-danger');
        status.textContent = 'Đã lưu ảnh. Bấm ảnh để kiểm tra độ rõ nét.';
        form.dispatchEvent(new Event('change', { bubbles: true }));
      } catch (error) {
        console.error('Essay image operation failed:', error);
        status.classList.add('text-danger');
        status.textContent = 'Chưa cập nhật được ảnh. Hãy xử lý lỗi bên dưới trước khi nộp.';
        const problem = document.createElement('div');
        problem.className = 'essay-upload-error alert alert-danger p-2 mt-2 small';
        const message = document.createElement('div');
        message.textContent = `${description}: ${error.message}`;
        problem.append(message);
        problem.append(button('Thử lại', 'Thử lại thao tác ảnh', () => {
          problem.remove();
          schedule(panel, action, description, discard);
        }));
        problem.append(button('Bỏ qua thao tác lỗi', 'Bỏ thao tác chưa thực hiện', () => {
          problem.remove();
          discard();
          status.textContent = 'Đã bỏ thao tác lỗi. Chỉ ảnh đang hiển thị mới được lưu.';
          status.classList.remove('text-danger');
        }));
        panel.querySelector('.essay-upload-errors').append(problem);
      }
    }).finally(() => { pending -= 1; });
  }

  function cards(panel) {
    return Array.from(panel.querySelectorAll('[data-image-id]'));
  }

  function refreshActions(panel) {
    const images = cards(panel);
    images.forEach((card, index) => {
      const actions = card.querySelector('.essay-image-actions');
      actions.replaceChildren();
      const label = document.createElement('span');
      label.className = 'small align-self-center';
      label.textContent = `${index + 1}`;
      actions.append(label);
      [-1, 1].forEach(direction => {
        const move = button(direction < 0 ? '↑' : '↓', direction < 0 ? 'Đưa ảnh lên trước' : 'Đưa ảnh xuống sau', () => {
          schedule(panel, async () => {
            const current = cards(panel);
            const from = current.indexOf(card);
            const to = from + direction;
            if (from < 0 || to < 0 || to >= current.length) return;
            [current[from], current[to]] = [current[to], current[from]];
            await request(panel.dataset.orderUrl, {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                answer_field: panel.dataset.answerField, ids: current.map(item => item.dataset.imageId),
              }),
            });
            panel.querySelector('.essay-image-list').replaceChildren(...current);
            refreshActions(panel);
          }, 'Sắp xếp ảnh');
        });
        move.classList.add('action-icon-btn');
        move.title = direction < 0 ? 'Đưa ảnh lên trước' : 'Đưa ảnh xuống sau';
        move.disabled = frozen || index + direction < 0 || index + direction >= images.length;
        actions.append(move);
      });
      const remove = button('', `Xóa ảnh ${index + 1}`, async () => {
        if (!await window.showConfirm(`Xóa ảnh bài làm ${index + 1}?`)) return;
        if (frozen) return;
        schedule(panel, async () => {
          await request(card.querySelector('a').getAttribute('href'), { method: 'DELETE' });
          card.remove();
          refreshActions(panel);
        }, 'Xóa ảnh');
      });
      remove.className = 'btn btn-outline-danger btn-sm action-icon-btn';
      remove.title = `Xóa ảnh ${index + 1}`;
      remove.innerHTML = '<i class="bi bi-trash" aria-hidden="true"></i>';
      actions.append(remove);
    });
  }

  form.querySelectorAll('.essay-upload').forEach(panel => {
    refreshActions(panel);
    panel.querySelectorAll('.essay-image-input').forEach(input => {
      input.addEventListener('click', startChoosing);
      input.addEventListener('cancel', finishChoosing);
      input.addEventListener('change', () => {
        finishChoosing();
        if (frozen) return;
        const files = Array.from(input.files || []);
        input.value = '';
        const reserved = reservedUploads.get(panel) || new Set();
        const totalReserved = Array.from(reservedUploads.values()).reduce((sum, items) => sum + items.size, 0);
        if (cards(panel).length + reserved.size + files.length > 3
            || form.querySelectorAll('[data-image-id]').length + totalReserved + files.length > 10) {
          window.showMessage('Tối đa 3 ảnh/câu và 10 ảnh/bài. Hãy chọn ít ảnh hơn hoặc xóa ảnh đã tải.');
          return;
        }
        reservedUploads.set(panel, reserved);
        files.forEach(file => {
          const reservation = {};
          reserved.add(reservation);
          let uploaded = false;
          schedule(panel, async () => {
            if (uploaded) return;
            const blob = await compress(file);
            const body = new FormData();
            body.append('answer_field', panel.dataset.answerField);
            body.append('image', blob, 'answer.jpg');
            const image = await request(panel.dataset.uploadUrl, { method: 'POST', body });
            const card = document.createElement('div');
            card.className = 'essay-image-card border rounded p-2';
            card.dataset.imageId = image.id;
            const link = document.createElement('a');
            link.href = image.url;
            link.target = '_blank';
            link.rel = 'noopener';
            const preview = document.createElement('img');
            preview.src = image.thumbnail_url;
            preview.alt = 'Ảnh bài làm — bấm để xem ảnh lớn';
            preview.width = preview.height = 120;
            preview.style.objectFit = 'contain';
            link.append(preview);
            const actions = document.createElement('div');
            actions.className = 'essay-image-actions d-flex gap-1 mt-1';
            card.append(link, actions);
            panel.querySelector('.essay-image-list').append(card);
            uploaded = true;
            reserved.delete(reservation);
            refreshActions(panel);
          }, `Tải ảnh ${file.name}`, () => reserved.delete(reservation));
        });
      });
    });
  });
})();
