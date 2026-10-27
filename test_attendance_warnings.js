// Run with: node test_attendance_warnings.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { spawnSync, execFileSync } = require('node:child_process');
const { chromium } = require('playwright');

const fixture = spawnSync('./venv/bin/python', ['-c', `
import json
from datetime import date, datetime, time
from test_attendance_warnings import AttendanceWarningTests
from extensions import db
AttendanceWarningTests.setUpClass()
test = AttendanceWarningTests()
test.setUp()
try:
    test.start = date.today()
    test.enrollment.enrolled_at = datetime.combine(test.start, time())
    test.student.full_name = '<img src=x onerror=alert(1)>'
    for index in range(8):
        current = test.session(0, 'absent' if index < 3 else None)
    paths = ['/teacher/', '/teacher/attendance', f'/teacher/attendance/{current.id}',
             '/teacher/students', f'/teacher/students/class/{test.class_.id}',
             f'/teacher/students/{test.student.id}']
    print(json.dumps({path: test.client.get(path).get_data(as_text=True) for path in paths}))
finally:
    test.tearDown()
    AttendanceWarningTests.tearDownClass()
`], { encoding: 'utf8' });
assert.equal(fixture.status, 0, fixture.stderr);
const pages = JSON.parse(fixture.stdout);
const bootstrapCss = execFileSync('curl', [
  '-fsSL', '--max-time', '30',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css',
], { encoding: 'utf8' });

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.route('**/*', route => route.abort());
    for (const [path, html] of Object.entries(pages)) {
      await page.setContent(html.replace(/<link\b[^>]*>/g, '')
        .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
        .replace('</head>', `<style>${bootstrapCss}\n${fs.readFileSync('static/css/custom.css', 'utf8')}</style></head>`));
      const panel = page.getByRole('region', { name: 'Cảnh báo học sinh nghỉ học' });
      if (!/\/students\/\d+$/.test(path)) {
        assert.equal(await panel.count(), 0, `No absence warning on ${path}`);
        assert.ok(!html.includes('attendance-warnings.js'));
        assert.ok(!html.includes('updateAbsenceWarnings'));
        continue;
      }
      assert.equal(await panel.count(), 1);
      assert.ok((await panel.textContent()).includes('nghỉ 3/8 buổi trong tháng'));
      assert.ok((await panel.textContent()).includes('25%'));
      assert.equal(await panel.locator('img').count(), 0);
      assert.ok((await panel.locator('strong').textContent()).includes('<img'));
      for (const width of [320, 375, 768, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        const bounds = await panel.evaluate(el => {
          const r = el.getBoundingClientRect();
          return { left: r.left, right: r.right, client: el.clientWidth, scroll: el.scrollWidth };
        });
        assert.ok(bounds.left >= 0 && bounds.right <= width);
        assert.ok(bounds.scroll <= bounds.client);
      }
    }
    console.log('PASS: monthly >25% warning only on teacher student detail; no warning on dashboard/attendance/roster; escaped names and 320–1440px layout.');
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
