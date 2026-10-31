(() => {
  let dialog;
  document.addEventListener('click', event => {
    const link = event.target.closest('.essay-image-link, .essay-image-card a');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.className = 'essay-image-preview border-0 rounded shadow';
      dialog.setAttribute('aria-label', 'Xem ảnh bài làm');
      dialog.innerHTML = `
        <div class="essay-image-preview-header">
          <strong>Ảnh bài làm</strong>
          <button type="button" class="btn btn-outline-secondary" data-close-image autofocus>Đóng ảnh</button>
        </div>
        <div class="essay-image-preview-content">
          <p class="text-danger d-none" data-image-error role="alert">Không tải được ảnh. Hãy đóng và thử lại; không xóa ảnh nếu chưa kiểm tra kết nối.</p>
          <img alt="Ảnh bài làm đầy đủ">
        </div>`;
      dialog.querySelector('[data-close-image]').addEventListener('click', () => dialog.close());
      dialog.addEventListener('click', click => {
        if (click.target !== dialog) return;
        const bounds = dialog.getBoundingClientRect();
        if (click.clientX < bounds.left || click.clientX > bounds.right
            || click.clientY < bounds.top || click.clientY > bounds.bottom) dialog.close();
      });
      dialog.querySelector('img').addEventListener('error', () => {
        dialog.querySelector('[data-image-error]').classList.remove('d-none');
      });
      dialog.addEventListener('close', () => dialog.querySelector('img').removeAttribute('src'));
      document.body.append(dialog);
    }
    dialog.querySelector('[data-image-error]').classList.add('d-none');
    dialog.querySelector('img').src = link.href;
    dialog.showModal();
  });
})();
