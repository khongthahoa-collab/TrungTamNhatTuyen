(() => {
  const form = document.getElementById('examForm');
  const csrfInput = form.querySelector('[name="csrf_token"]');
  const csrfUrl = form.dataset.csrfUrl;

  async function readResponse(response) {
    if (!response.headers.get('content-type')?.includes('application/json')) {
      throw new Error('Không thể kết nối phiên làm bài. Hãy kiểm tra mạng và phiên đăng nhập; không đóng trang thi.');
    }
    return response.json();
  }

  async function refreshCsrf() {
    const response = await fetch(csrfUrl, {
      credentials: 'same-origin', cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
    const body = await readResponse(response);
    if (!response.ok || typeof body.csrf_token !== 'string' || !body.csrf_token) {
      throw new Error(body.error || 'Không thể làm mới phiên bảo mật. Hãy thử lại; không đóng trang thi.');
    }
    csrfInput.value = body.csrf_token;
  }

  window.examRequest = async (url, options, freshToken = false) => {
    if (freshToken) await refreshCsrf();
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const body = options.body;
      if (body instanceof FormData && body.has('csrf_token')) {
        body.set('csrf_token', csrfInput.value);
      }
      const response = await fetch(url, {
        ...options, credentials: 'same-origin',
        headers: {
          ...options.headers, Accept: 'application/json', 'X-CSRFToken': csrfInput.value,
        },
      });
      const payload = await readResponse(response);
      if (response.status === 400 && payload.code === 'csrf_expired' && attempt === 0) {
        await refreshCsrf();
        continue;
      }
      if (!response.ok) throw new Error(payload.error || `Không thể lưu bài làm (HTTP ${response.status}).`);
      return payload;
    }
  };
})();
