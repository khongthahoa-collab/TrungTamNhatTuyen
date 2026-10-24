(() => {
  const message = document.getElementById('pwaPushMessage');
  const messageText = document.getElementById('pwaPushMessageText');
  const messageButton = document.getElementById('pwaPushMessageButton');
  const navbarButton = document.getElementById('pwaPushEnable');
  if (!message || !messageText || !messageButton || !navbarButton) return;

  const keyUrl = message.dataset.keyUrl;
  const subscriptionUrl = message.dataset.subscriptionUrl;
  const csrfToken = message.dataset.csrfToken;
  const enableMessage = message.dataset.enableMessage;
  const enabledMessage = message.dataset.enabledMessage;
  const disabledMessage = message.dataset.disabledMessage;

  function setMessage(text, isError = false) {
    messageText.textContent = text;
    message.classList.toggle('alert-danger', isError);
    message.classList.toggle('alert-info', !isError);
    message.classList.remove('d-none');
  }

  function decodeApplicationServerKey(encodedKey) {
    const padding = '='.repeat((4 - encodedKey.length % 4) % 4);
    const base64 = (encodedKey + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = window.atob(base64);
    return Uint8Array.from(raw, (character) => character.charCodeAt(0));
  }

  async function saveSubscription(subscription) {
    const response = await fetch(subscriptionUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken,
      },
      body: JSON.stringify(subscription.toJSON()),
    });
    if (!response.ok) throw new Error('Không thể lưu thiết lập nhận thông báo.');
  }

  async function removeSubscription(subscription) {
    const response = await fetch(subscriptionUrl, {
      method: 'DELETE',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken,
      },
      body: JSON.stringify({ endpoint: subscription.endpoint }),
    });
    if (!response.ok) throw new Error('Không thể tắt thông báo trên thiết bị này.');
  }

  async function initialize() {
    const isIos = /iPhone|iPad|iPod/.test(navigator.userAgent)
      || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    const isStandalone = window.matchMedia('(display-mode: standalone)').matches
      || window.navigator.standalone === true;
    if (isIos && !isStandalone) {
      setMessage('Trên iPhone/iPad, hãy thêm ứng dụng vào Màn hình chính và mở ứng dụng từ biểu tượng đó để bật thông báo.');
      messageButton.classList.add('d-none');
      return;
    }
    if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
      setMessage('Trình duyệt này chưa hỗ trợ thông báo đẩy. Hãy mở ứng dụng bằng trình duyệt hiện đại.');
      messageButton.classList.add('d-none');
      return;
    }

    const response = await fetch(keyUrl, { credentials: 'same-origin' });
    if (!response.ok) throw new Error('Không thể tải thiết lập thông báo.');
    const config = await response.json();
    if (!config.available || !config.public_key) {
      setMessage('Thông báo đẩy chưa được cấu hình trên hệ thống. Vui lòng liên hệ quản trị viên.');
      messageButton.classList.add('d-none');
      return;
    }

    navbarButton.classList.remove('d-none');
    const registration = await navigator.serviceWorker.ready;
    let subscription = await registration.pushManager.getSubscription();

    if (Notification.permission === 'denied') {
      navbarButton.classList.add('d-none');
      setMessage('Thông báo đang bị chặn trong cài đặt trình duyệt. Hãy cho phép thông báo để nhận cập nhật mới.');
      messageButton.classList.add('d-none');
      return;
    }

    if (subscription && Notification.permission === 'granted') {
      await saveSubscription(subscription);
      message.classList.add('d-none');
      navbarButton.title = 'Tắt thông báo trên thiết bị này';
      navbarButton.setAttribute('aria-label', navbarButton.title);
    } else {
      navbarButton.title = 'Bật thông báo';
      navbarButton.setAttribute('aria-label', navbarButton.title);
      setMessage(enableMessage);
    }

    async function toggleSubscription() {
      messageButton.disabled = true;
      navbarButton.disabled = true;
      try {
        if (subscription) {
          await removeSubscription(subscription);
          await subscription.unsubscribe();
          subscription = null;
          setMessage(disabledMessage);
          navbarButton.title = 'Bật thông báo';
          navbarButton.setAttribute('aria-label', navbarButton.title);
        } else {
          const permission = Notification.permission === 'granted'
            ? 'granted'
            : await Notification.requestPermission();
          if (permission !== 'granted') {
            setMessage('Bạn chưa cho phép gửi thông báo. Có thể bật lại trong cài đặt trình duyệt.', true);
            return;
          }
          subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: decodeApplicationServerKey(config.public_key),
          });
          await saveSubscription(subscription);
          setMessage(enabledMessage);
          message.classList.add('d-none');
          navbarButton.title = 'Tắt thông báo trên thiết bị này';
          navbarButton.setAttribute('aria-label', navbarButton.title);
        }
      } catch (error) {
        console.error('PWA push notification setup failed:', error);
        setMessage(error.message || 'Không thể cập nhật thiết lập thông báo.', true);
      } finally {
        messageButton.disabled = false;
        navbarButton.disabled = false;
      }
    }

    messageButton.addEventListener('click', toggleSubscription);
    navbarButton.addEventListener('click', toggleSubscription);
  }

  initialize().catch((error) => {
    console.error('PWA push notification initialization failed:', error);
  });
})();
