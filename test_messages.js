// Run with: node test_messages.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setContent('<meta name="viewport" content="width=device-width, initial-scale=1"><button id="trigger">Open</button>');
    await page.addStyleTag({ content: fs.readFileSync('static/css/custom.css', 'utf8') });
    await page.addScriptTag({ content: fs.readFileSync('static/js/messages.js', 'utf8') });
    await page.evaluate(() => {
      window.finished = [];
      document.getElementById('trigger').onclick = () => {
        showMessage('<img src=x onerror=alert(1)>\nThông báo đầu tiên').then(() => finished.push(1));
        showMessage('Thông báo thứ hai').then(() => finished.push(2));
      };
    });
    await page.locator('#trigger').click();
    assert.equal(await page.locator('.app-message[open]').count(), 1);
    assert.equal(await page.locator('.app-message img').count(), 0);
    assert.ok((await page.locator('#appMessageText').innerText()).includes('<img src=x'));
    assert.deepEqual(await page.evaluate(() => finished), []);
    await page.getByRole('button', { name: 'Đã hiểu', exact: true }).click();
    await page.waitForFunction(() => document.getElementById('appMessageText').textContent === 'Thông báo thứ hai');
    assert.equal(await page.locator('#appMessageText').textContent(), 'Thông báo thứ hai');
    assert.deepEqual(await page.evaluate(() => finished), [1]);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => window.finished.length === 2);
    assert.equal(await page.locator('.app-message[open]').count(), 0);
    assert.equal(await page.locator('#trigger').evaluate(el => el === document.activeElement), true);

    for (const action of ['cancel', 'escape', 'close', 'accept']) {
      await page.evaluate(() => {
        window.confirmed = null;
        showConfirm('Tìm thấy bản nháp trên thiết bị. Bạn có muốn khôi phục không?')
          .then(value => { window.confirmed = value; });
      });
      assert.equal(await page.locator('#appMessageTitle').textContent(), 'Xác nhận');
      assert.equal(await page.getByRole('button', { name: 'Hủy', exact: true })
        .evaluate(el => el === document.activeElement), true);
      if (action === 'escape') await page.keyboard.press('Escape');
      else await page.getByRole('button', {
        name: action === 'cancel' ? 'Hủy' : action === 'close' ? 'Đóng' : 'Đồng ý', exact: true,
      }).click();
      await page.waitForFunction(() => window.confirmed !== null);
      assert.equal(await page.evaluate(() => window.confirmed), action === 'accept');
    }

    await page.evaluate(() => {
      document.body.insertAdjacentHTML('beforeend', `
        <form id="confirmedForm" data-confirm="Xóa dữ liệu?">
          <input required name="required" value="valid">
          <input type="hidden" name="csrf_token" value="synthetic-csrf">
          <button type="submit" name="action" value="delete" data-confirm="Xóa mục đã chọn?">Delete</button>
        </form>`);
      window.posts = [];
      document.addEventListener('submit', event => {
        if (event.target.id !== 'confirmedForm' || event.defaultPrevented) return;
        event.preventDefault();
        window.posts.push(Object.fromEntries(new FormData(event.target, event.submitter)));
      });
    });
    await page.getByRole('button', { name: 'Delete', exact: true }).click();
    assert.equal(await page.locator('#appMessageText').textContent(), 'Xóa mục đã chọn?');
    await page.getByRole('button', { name: 'Hủy', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('.app-message[open]'));
    assert.deepEqual(await page.evaluate(() => window.posts), []);
    await page.getByRole('button', { name: 'Delete', exact: true }).click();
    await page.evaluate(() => document.getElementById('confirmedForm')
      .requestSubmit(document.querySelector('#confirmedForm button')));
    await page.getByRole('button', { name: 'Đồng ý', exact: true }).click();
    await page.waitForFunction(() => window.posts.length === 1);
    assert.deepEqual(await page.evaluate(() => window.posts), [
      { required: 'valid', csrf_token: 'synthetic-csrf', action: 'delete' },
    ]);
    assert.equal(await page.locator('.app-message[open]').count(), 0);

    // Validation is rerun after confirmation rather than bypassed with form.submit().
    await page.getByRole('button', { name: 'Delete', exact: true }).click();
    await page.evaluate(() => { document.querySelector('#confirmedForm input').value = ''; });
    await page.getByRole('button', { name: 'Đồng ý', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('.app-message[open]'));
    assert.equal(await page.evaluate(() => window.posts.length), 1);

    for (const width of [320, 375, 768, 1440]) {
      await page.setViewportSize({ width, height: 640 });
      await page.evaluate(() => { showMessage(('LongLinkWithoutSpaces'.repeat(12) + '\n').repeat(15)); });
      const bounds = await page.locator('.app-message').evaluate(el => {
        const r = el.getBoundingClientRect();
        return { x: r.x, right: r.right, height: r.height, clientWidth: el.clientWidth, scrollWidth: el.scrollWidth };
      });
      assert.ok(bounds.x >= 0 && bounds.right <= width && bounds.height <= 640);
      assert.ok(bounds.scrollWidth <= bounds.clientWidth);
      await page.getByRole('button', { name: 'Đã hiểu', exact: true }).click();
      await page.waitForFunction(() => !document.querySelector('.app-message[open]'));
    }

    // Simulate Bootstrap's document-level focus trap on an existing modal.
    await page.evaluate(() => {
      const modal = document.createElement('div');
      modal.id = 'underlyingModal';
      modal.innerHTML = '<button id="modalTrigger">Modal action</button>';
      document.body.append(modal);
      document.addEventListener('focusin', event => {
        if (!modal.contains(event.target)) document.getElementById('modalTrigger').focus();
      });
      document.getElementById('modalTrigger').onclick = () => { showMessage('Message above another modal'); };
    });
    await page.locator('#modalTrigger').click();
    assert.equal(await page.getByRole('button', { name: 'Đã hiểu', exact: true }).evaluate(el => el === document.activeElement), true);
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.querySelector('.app-message').contains(document.activeElement)), true);
    await page.getByRole('button', { name: 'Đóng', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('.app-message[open]'));
    assert.equal(await page.locator('#modalTrigger').evaluate(el => el === document.activeElement), true);

    const take = fs.readFileSync('templates/exams/take.html', 'utf8');
    const manualSubmit = take.slice(take.indexOf('let confirmationPending = false;'),
      take.indexOf("form.addEventListener('input', event =>"));
    await page.evaluate(code => {
      document.body.insertAdjacentHTML('beforeend', '<form id="manualExam"><button>Submit exam</button></form>');
      window.form = document.getElementById('manualExam');
      window.form.submit = () => { window.manualSubmissionCount = (window.manualSubmissionCount || 0) + 1; };
      window.submitted = false;
      window.cheatCount = 0;
      window.cheatField = { value: 0 };
      window.countUnansweredQuestions = () => 2;
      window.examEssayUploads = { isBusy: () => false, hasErrors: () => false, freeze: () => {} };
      window.eval(code);
    }, manualSubmit);
    await page.getByRole('button', { name: 'Submit exam', exact: true }).click();
    assert.ok((await page.locator('#appMessageText').textContent()).includes('2 câu chưa làm xong'));
    await page.getByRole('button', { name: 'Hủy', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('.app-message[open]'));
    assert.equal(await page.evaluate(() => window.manualSubmissionCount || 0), 0);
    await page.getByRole('button', { name: 'Submit exam', exact: true }).click();
    await page.evaluate(() => window.form.requestSubmit());
    await page.getByRole('button', { name: 'Đồng ý', exact: true }).click();
    await page.waitForFunction(() => window.manualSubmissionCount === 1);
    assert.equal(await page.locator('.app-message[open]').count(), 0);

    // A timer submission while the confirmation is open must not submit twice.
    await page.evaluate(() => { window.submitted = false; });
    await page.getByRole('button', { name: 'Submit exam', exact: true }).click();
    await page.evaluate(() => { window.submitted = true; });
    await page.getByRole('button', { name: 'Đồng ý', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('.app-message[open]'));
    assert.equal(await page.evaluate(() => window.manualSubmissionCount), 1);

    // Execute the real auto-submit function: notification(s) must finish before submit.
    const autoSubmit = take.slice(take.indexOf('async function autoSubmit(reason)'), take.indexOf('// ── Countdown timer'));
    await page.evaluate(code => {
      window.submitted = false;
      window.cheatCount = 3;
      window.CHEAT_LIMIT = 2;
      window.cheatField = { value: 0 };
      window.form = { submit: () => { window.submissionCount = (window.submissionCount || 0) + 1; } };
      window.examEssayUploads = { isBusy: () => true, hasErrors: () => false, freeze: () => {} };
      window.eval(code);
      autoSubmit('timeout');
      autoSubmit('cheat');
    }, autoSubmit);
    assert.equal(await page.evaluate(() => window.submissionCount || 0), 0);
    await page.getByRole('button', { name: 'Đã hiểu', exact: true }).click();
    await page.waitForFunction(() => document.getElementById('appMessageText').textContent.includes('Ảnh đang tải'));
    assert.equal(await page.evaluate(() => window.submissionCount || 0), 0);
    await page.getByRole('button', { name: 'Đã hiểu', exact: true }).click();
    await page.waitForFunction(() => window.submissionCount === 1);
    assert.deepEqual(errors, []);
    console.log('PASS: messages and confirmations; accept/cancel/Escape/close; safe text, focus, queue, responsive layout; form submission preserves CSRF/submitter, cancels safely, validates again and runs once; exam auto-submit waits.');
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
