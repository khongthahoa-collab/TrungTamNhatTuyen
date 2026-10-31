const assert = require('node:assert/strict');
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');
const { chromium } = require('playwright');

const fixture = spawnSync('./venv/bin/python', ['-W', 'ignore', '-c', `
import json
from test_essay_images import EssayImageTests
from extensions import db
EssayImageTests.setUpClass()
t = EssayImageTests()
t.setUp()
try:
    t.exam.exam_type = 'practice'
    db.session.commit()
    photo = t.upload().get_json()
    student = t.client.get(f'/student/exams/{t.exam.id}').get_data(as_text=True)
    t.exam.exam_type = 'exam'
    db.session.commit()
    cheat = t.client.get(f'/student/exams/{t.exam.id}').get_data(as_text=True)
    t.exam.exam_type = 'practice'
    db.session.commit()
    t.client.post(f'/student/exams/{t.exam.id}/submit', data={
        'csrf_token': t.csrf, 'attempt_id': t.attempt.id})
    t.login(t.teacher)
    teacher = t.client.get(f'/teacher/exams/{t.exam.id}/attempts/{t.attempt.id}').get_data(as_text=True)
    print(json.dumps({'student': student, 'teacher': teacher, 'cheat': cheat, 'photo': photo}))
finally:
    t.tearDown()
    EssayImageTests.tearDownClass()
`], { encoding: 'utf8', maxBuffer: 4 * 1024 * 1024 });
assert.equal(fixture.status, 0, fixture.stderr);
const pages = JSON.parse(fixture.stdout);

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 375, height: 667 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const requests = [];
    let failSubmit = true;
    let expireSave = true;
    let mode = 'student';
    await page.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.hostname !== 'exam.test') return route.abort();
      if (url.pathname.startsWith('/static/')) {
        const path = url.pathname.slice(1);
        const mocks = {
          'static/js/app.js': '',
          'static/js/messages.js': '',
          'static/js/exam-math.js': 'window.scheduleExamMathTypeset = () => {};',
        };
        return route.fulfill({
          contentType: path.endsWith('.css') ? 'text/css' : 'text/javascript',
          body: Object.hasOwn(mocks, path) ? mocks[path] : fs.readFileSync(path, 'utf8'),
        });
      }
      if (url.pathname.endsWith('/csrf')) {
        requests.push({ type: 'csrf' });
        return route.fulfill({ json: { csrf_token: 'fresh-token' } });
      }
      if (url.pathname.endsWith('/save')) {
        requests.push({ type: 'save', token: request.headers()['x-csrftoken'], body: request.postData() });
        if (expireSave) {
          expireSave = false;
          return route.fulfill({ status: 400, json: { code: 'csrf_expired' } });
        }
        return route.fulfill({ json: { saved: true } });
      }
      if (url.pathname.endsWith('/submit')) {
        requests.push({ type: 'submit', token: request.headers()['x-csrftoken'], body: request.postData() });
        if (failSubmit) return route.fulfill({ status: 503, json: { error: 'temporary failure' } });
        return route.fulfill({ json: { redirect_url: '/result' } });
      }
      if (url.pathname === '/result') return route.fulfill({ contentType: 'text/html', body: 'Submitted' });
      if (url.pathname === pages.photo.url || url.pathname.includes('/exam-images/')) {
        return route.fulfill({
          contentType: 'image/svg+xml',
          body: '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="2000"><rect width="200" height="2000" fill="white"/></svg>',
        });
      }
      let html = pages[mode];
      if (mode === 'timeout') html = pages.student.replace(/let remaining = \d+;/, 'let remaining = 0;');
      return route.fulfill({ contentType: 'text/html', body: html });
    });
    await page.addInitScript(() => {
      window.showConfirm = async () => true;
      window.showMessage = async message => { window.lastMessage = message; };
    });

    mode = 'teacher';
    await page.goto('http://exam.test/teacher');
    for (const viewport of [{ width: 320, height: 568 }, { width: 667, height: 375 }]) {
      await page.setViewportSize(viewport);
      await page.locator('.essay-image-link').first().click();
      const close = page.locator('[data-close-image]');
      await close.waitFor({ state: 'visible' });
      assert.equal(await page.locator('.essay-image-preview').evaluate(dialog => dialog.open), true);
      const bounds = await close.boundingBox();
      assert.ok(bounds.y >= 0 && bounds.y + bounds.height <= viewport.height);
      assert.ok(bounds.height >= 44, 'touch target must be at least 44px');
      await page.locator('.essay-image-preview-content').evaluate(content => { content.scrollTop = 1500; });
      assert.ok(await close.isVisible(), 'close remains outside the image scrolling area');
      await close.click();
      assert.equal(await page.locator('.essay-image-preview').evaluate(dialog => dialog.open), false);
      assert.equal(page.url(), 'http://exam.test/teacher');
      await page.locator('.essay-image-link').first().click();
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('.essay-image-preview').evaluate(dialog => dialog.open), false);
      await page.locator('.essay-image-link').first().click();
      await page.mouse.click(1, 1);
      assert.equal(await page.locator('.essay-image-preview').evaluate(dialog => dialog.open), false);
    }
    assert.equal(page.context().pages().length, 1, 'image viewer never opens another tab');

    mode = 'student';
    await page.goto('http://exam.test/take');
    await page.locator('.essay-image-card a').first().click();
    await page.locator('[data-close-image]').click();
    assert.equal(page.url(), 'http://exam.test/take');
    await page.locator('textarea').first().fill('Keep this answer');
    await page.waitForFunction(() => document.getElementById('saveStatus').textContent === 'Đã lưu tiến độ.');
    const saves = requests.filter(request => request.type === 'save');
    assert.equal(saves.length, 2);
    assert.equal(saves[1].token, 'fresh-token');
    assert.ok(saves[1].body.includes('Keep this answer'));
    await page.locator('#submitBtnTop').click();
    await page.waitForFunction(() => window.lastMessage?.includes('temporary failure'));
    assert.equal(page.url(), 'http://exam.test/take');
    assert.equal(await page.locator('textarea').first().inputValue(), 'Keep this answer');
    assert.equal(await page.locator('[data-image-id]').count(), 1);
    assert.equal(await page.locator('.essay-image-input').first().isEnabled(), true);
    failSubmit = false;
    await page.locator('#submitBtnTop').click();
    await page.waitForURL('**/result');
    for (const submission of requests.filter(request => request.type === 'submit')) {
      assert.equal(submission.token, 'fresh-token');
      assert.ok(submission.body.includes('Keep this answer'));
    }

    for (const automaticMode of ['timeout', 'cheat']) {
      mode = automaticMode;
      failSubmit = true;
      await page.goto('http://exam.test/take');
      if (mode === 'cheat') await page.evaluate(() => {
        for (let i = 0; i < 20; i += 1) window.dispatchEvent(new Event('blur'));
      });
      await page.waitForFunction(() => window.lastMessage?.includes('temporary failure'));
      assert.equal(page.url(), 'http://exam.test/take');
      assert.equal(await page.locator('.essay-image-input').first().isEnabled(), false);
      failSubmit = false;
      await page.locator('#submitBtnTop').click();
      await page.waitForURL('**/result');
    }
    assert.deepEqual(errors, []);
    console.log('PASS: mobile portrait/landscape image close, Escape/backdrop, autosave CSRF recovery, manual/timeout/cheat failed submissions retain page and retry.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
