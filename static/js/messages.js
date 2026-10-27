(function () {
  const queue = [];
  let dialog;
  let message;
  let active;

  function showNext() {
    if (active || !queue.length) return;
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.className = 'app-message';
      dialog.setAttribute('aria-labelledby', 'appMessageTitle');
      dialog.setAttribute('aria-describedby', 'appMessageText');
      dialog.innerHTML = `
        <div class="app-message-header">
          <h2 id="appMessageTitle">Thông báo</h2>
          <button type="button" class="btn-close" aria-label="Đóng"></button>
        </div>
        <div id="appMessageText" class="app-message-text"></div>
        <div class="app-message-footer">
          <button type="button" class="btn btn-primary" autofocus>Đã hiểu</button>
        </div>`;
      message = dialog.querySelector('#appMessageText');
      // Keep an underlying Bootstrap modal's focus trap from stealing focus.
      dialog.addEventListener('focusin', event => event.stopPropagation());
      dialog.addEventListener('keydown', event => {
        if (event.key !== 'Tab') return;
        const buttons = dialog.querySelectorAll('button');
        const first = buttons[0];
        const last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      });
      dialog.querySelectorAll('button').forEach(button => {
        button.addEventListener('click', () => dialog.close());
      });
      dialog.addEventListener('close', () => {
        const closed = active;
        active = null;
        closed.resolve();
        showNext();
      });
      document.body.append(dialog);
    }
    active = queue.shift();
    message.textContent = active.message;
    dialog.showModal();
  }

  window.showMessage = function (message) {
    return new Promise(resolve => {
      queue.push({ message: String(message ?? ''), resolve });
      showNext();
    });
  };
})();
