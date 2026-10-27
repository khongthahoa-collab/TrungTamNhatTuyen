(function () {
  const queue = [];
  let dialog;
  let message;
  let active;
  const pendingForms = new WeakSet();
  const approvedForms = new WeakSet();

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
          <button type="button" class="btn btn-outline-secondary" data-message-cancel hidden>Hủy</button>
          <button type="button" class="btn btn-primary" autofocus>Đã hiểu</button>
        </div>`;
      message = dialog.querySelector('#appMessageText');
      // Keep an underlying Bootstrap modal's focus trap from stealing focus.
      dialog.addEventListener('focusin', event => event.stopPropagation());
      dialog.addEventListener('keydown', event => {
        if (event.key !== 'Tab') return;
        const buttons = Array.from(dialog.querySelectorAll('button')).filter(button => !button.hidden);
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
        button.addEventListener('click', () => {
          dialog.close(button.matches('.btn-primary') ? 'confirmed' : 'cancelled');
        });
      });
      dialog.addEventListener('close', () => {
        const closed = active;
        active = null;
        closed.resolve(closed.confirmation ? dialog.returnValue === 'confirmed' : undefined);
        showNext();
      });
      document.body.append(dialog);
    }
    active = queue.shift();
    message.textContent = active.message;
    dialog.querySelector('#appMessageTitle').textContent = active.confirmation ? 'Xác nhận' : 'Thông báo';
    dialog.querySelector('[data-message-cancel]').hidden = !active.confirmation;
    dialog.querySelector('.btn-primary').textContent = active.confirmation ? 'Đồng ý' : 'Đã hiểu';
    dialog.returnValue = '';
    dialog.showModal();
    if (active.confirmation) dialog.querySelector('[data-message-cancel]').focus();
  }

  window.showMessage = function (message) {
    return new Promise(resolve => {
      queue.push({ message: String(message ?? ''), resolve });
      showNext();
    });
  };

  window.showConfirm = function (message) {
    return new Promise(resolve => {
      queue.push({ message: String(message ?? ''), resolve, confirmation: true });
      showNext();
    });
  };

  window.confirmFormSubmit = function (event, text) {
    const form = event.target;
    if (approvedForms.delete(form)) return true;
    event.preventDefault();
    if (pendingForms.has(form)) return false;
    pendingForms.add(form);
    const submitter = event.submitter;
    window.showConfirm(text).then(confirmed => {
      pendingForms.delete(form);
      if (!confirmed || !form.isConnected) return;
      approvedForms.add(form);
      try {
        form.requestSubmit(submitter || undefined);
      } finally {
        approvedForms.delete(form);
      }
    });
    return false;
  };

  document.addEventListener('submit', event => {
    if (event.defaultPrevented) return;
    const text = event.submitter?.dataset.confirm ?? event.target.dataset.confirm;
    if (text !== undefined) window.confirmFormSubmit(event, text);
  });

  const pendingLinks = new WeakSet();
  document.addEventListener('click', async event => {
    const link = event.target.closest('a[data-confirm]');
    if (!link || event.defaultPrevented) return;
    event.preventDefault();
    if (pendingLinks.has(link)) return;
    pendingLinks.add(link);
    try {
      if (await window.showConfirm(link.dataset.confirm)) {
        window.location.assign(link.href);
      }
    } finally {
      pendingLinks.delete(link);
    }
  });
})();
