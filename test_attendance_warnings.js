// Run with: node test_attendance_warnings.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { spawnSync, execFileSync } = require('node:child_process');
const { chromium } = require('playwright');

const fixture = spawnSync('./venv/bin/python', ['-c', `
import json
from datetime import date, datetime, time, timedelta
from test_attendance_warnings import AttendanceWarningTests
from extensions import db
AttendanceWarningTests.setUpClass()
test = AttendanceWarningTests()
test.setUp()
try:
    test.start = date.today() - timedelta(days=2)
    test.enrollment.enrolled_at = datetime.combine(test.start, time())
    test.student.full_name = '<img src=x onerror=alert(1)>'
    test.session(0, 'absent')
    test.session(1, 'excused')
    current = test.session(2, None)
    pages = {
        'list': test.client.get('/teacher/attendance').get_data(as_text=True),
        'session': test.client.get(f'/teacher/attendance/{current.id}').get_data(as_text=True),
    }
    response = test.client.post(f'/teacher/api/attendance/{current.id}/save',
        json={'attendance': [{'student_id': test.student.id, 'status': 'absent'}]})
    assert response.status_code == 200
    print(json.dumps({'pages': pages, 'result': response.json, 'classId': test.class_.id}))
finally:
    test.tearDown()
    AttendanceWarningTests.tearDownClass()
`], { encoding: 'utf8' });
assert.equal(fixture.status, 0, fixture.stderr);
const { pages, result, classId } = JSON.parse(fixture.stdout);
const bootstrapCss = execFileSync('curl', [
  '-fsSL', '--max-time', '30',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css',
], { encoding: 'utf8' });
const bootstrapJs = execFileSync('curl', [
  '-fsSL', '--max-time', '30',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js',
], { encoding: 'utf8' });

(async () => {
  const browser = await chromium.launch();
  try {
    for (const [name, html] of Object.entries(pages)) {
      const page = await browser.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/*', route => route.abort());
      const script = Array.from(html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g))
        .map(match => match[1]).find(code => code.includes(name === 'list' ? 'const ATT_CSRF' : 'const SAVE_URL'));
      assert.ok(script);
      await page.setContent(html.replace(/<link\b[^>]*>/g, '')
        .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
        .replace('</head>', `<style>${bootstrapCss}\n${fs.readFileSync('static/css/custom.css', 'utf8')}</style></head>`));
      await page.addScriptTag({ content: bootstrapJs });
      await page.addScriptTag({ content: fs.readFileSync('static/js/attendance-warnings.js', 'utf8') });
      await page.evaluate(response => {
        window.showConfirm = async () => true;
        window.showMessage = text => { throw new Error(text); };
        window.fetch = async () => ({ ok: true, json: async () => response });
        document.querySelectorAll('.collapse').forEach(panel => panel.classList.add('show'));
      }, result);
      await page.addScriptTag({ content: script });
      const panel = page.locator('[data-absence-class]');
      assert.equal(await panel.isVisible(), false);
      if (name === 'list') {
        await page.locator('.status-btn[data-value="absent"]').click();
        await page.locator('.btn-save').click();
      } else {
        await page.locator('label[for^="absent_"]').click();
        await page.locator('#saveBtn').click();
      }
      await panel.waitFor({ state: 'visible' });
      assert.ok((await panel.textContent()).includes('nghỉ 3 buổi'));
      assert.ok((await panel.textContent()).includes('3/8 buổi'));
      assert.equal(await panel.locator('img').count(), 0);
      assert.ok((await panel.locator('strong').textContent()).includes('<img'));
      if (name === 'session') await page.locator('.modal.show [data-bs-dismiss="modal"]').first().click();
      for (const width of [320, 375, 768, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        const bounds = await panel.evaluate(el => {
          const r = el.getBoundingClientRect();
          return { left: r.left, right: r.right, client: el.clientWidth, scroll: el.scrollWidth };
        });
        assert.ok(bounds.left >= 0 && bounds.right <= width);
        assert.ok(bounds.scroll <= bounds.client);
      }
      await page.evaluate(id => window.updateAbsenceWarnings(id, []), classId);
      assert.equal(await panel.isVisible(), false);
      assert.equal(await panel.locator('li').count(), 0);
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log('PASS: real attendance pages update warnings after save, show third absence in 8-session cycle, safely render names, clear corrected warnings and fit 320–1440px.');
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
