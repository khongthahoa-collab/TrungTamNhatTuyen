const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('static/js/exam-request.js', 'utf8');
function setup(responses) {
  const csrf = { value: 'old-token' };
  const calls = [];
  const context = {
    window: {}, FormData,
    document: { getElementById: () => ({
      dataset: { csrfUrl: '/exam-images/attempts/1/csrf' }, querySelector: () => csrf,
    }) },
    fetch: async (url, options) => {
      calls.push({ url, headers: options.headers, token: options.body?.get?.('csrf_token') });
      const next = responses.shift();
      assert.ok(next, 'unexpected extra request');
      if (next instanceof Error) throw next;
      return {
        status: next.status, ok: next.status >= 200 && next.status < 300,
        headers: { get: () => next.html ? 'text/html' : 'application/json' },
        json: async () => next.body,
      };
    },
  };
  vm.runInNewContext(source, context);
  return { csrf, calls, request: context.window.examRequest };
}
const expired = { status: 400, body: { code: 'csrf_expired', error: 'expired' } };
const fresh = { status: 200, body: { csrf_token: 'new-token' } };

(async () => {
  const form = new FormData();
  form.set('csrf_token', 'old-token');
  form.set('g0_q1', 'my answer');
  const recovery = setup([expired, fresh, { status: 200, body: { saved: true } }]);
  assert.equal((await recovery.request('/save', { method: 'POST', body: form })).saved, true);
  assert.deepEqual(recovery.calls.map(call => call.url), ['/save', '/exam-images/attempts/1/csrf', '/save']);
  assert.equal(recovery.calls[0].token, 'old-token');
  assert.equal(recovery.calls[2].token, 'new-token');
  assert.equal(recovery.calls[2].headers['X-CSRFToken'], 'new-token');
  assert.equal(form.get('g0_q1'), 'my answer');

  for (const method of ['POST', 'DELETE']) {
    const upload = setup([expired, fresh, { status: 201, body: { id: 'photo' } }]);
    assert.equal((await upload.request('/photo', { method })).id, 'photo');
    assert.equal(upload.calls.length, 3);
  }
  const submit = setup([fresh, { status: 200, body: { redirect_url: '/result' } }]);
  assert.equal((await submit.request('/submit', { method: 'POST', body: form }, true)).redirect_url, '/result');
  assert.equal(submit.calls[0].url, '/exam-images/attempts/1/csrf');
  assert.equal(submit.calls[1].token, 'new-token');

  for (const response of [
    { status: 409, body: { error: 'deadline' } },
    { status: 400, body: { error: 'bad file' } },
    { status: 200, html: true },
    new Error('offline'),
  ]) {
    const failed = setup([response]);
    await assert.rejects(failed.request('/upload', { method: 'POST' }));
    assert.equal(failed.calls.length, 1, 'do not retry ambiguous or non-CSRF failures');
  }
  const twice = setup([expired, fresh, expired]);
  await assert.rejects(twice.request('/upload', { method: 'POST' }));
  assert.equal(twice.calls.length, 3, 'retry is bounded');
  const loggedOut = setup([{ status: 200, html: true }]);
  await assert.rejects(loggedOut.request('/submit', { method: 'POST' }, true));
  assert.equal(loggedOut.calls.length, 1, 'never submit after failed token refresh');
  console.log('PASS: CSRF refresh/retry, form and header tokens, fresh submission, bounded retries and explicit failures.');
})().catch(error => { console.error(error); process.exitCode = 1; });
