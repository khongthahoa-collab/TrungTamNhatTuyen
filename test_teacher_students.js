// Run with: node test_teacher_students.js
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { spawnSync, execFileSync } = require('node:child_process');
const { chromium } = require('playwright');

const rendered = spawnSync('./venv/bin/python', ['-c', `
import json
from test_teacher_students import TeacherStudentsTests
TeacherStudentsTests.setUpClass()
test = TeacherStudentsTests()
test.setUp()
try:
    test.populate()
    paths = ['/teacher/exams', f'/teacher/scores/{test.class_.id}/detai', '/teacher/students', f'/teacher/students/class/{test.class_.id}?q=Synthetic',
             f'/teacher/students/{test.student.id}']
    print(json.dumps({path: test.client.get(path).get_data(as_text=True) for path in paths}))
finally:
    test.tearDown()
    TeacherStudentsTests.tearDownClass()
`], { encoding: 'utf8' });
assert.equal(rendered.status, 0, rendered.stderr);
const bootstrap = execFileSync('curl', [
  '-fsSL', '--max-time', '30',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css',
], { encoding: 'utf8' });
const icons = execFileSync('curl', ['-fsSL', '--max-time', '30',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css'], { encoding: 'utf8' });

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.route('**/*', route => route.abort());
    for (const [path, html] of Object.entries(JSON.parse(rendered.stdout))) {
      await page.setContent(html.replace(/<link\b[^>]*>/g, '')
        .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
        .replace('</head>', `<style>${bootstrap}\n${icons}\n${fs.readFileSync('static/css/custom.css', 'utf8')}\n${fs.readFileSync('static/css/teacher-scores.css', 'utf8')}</style></head>`));
      for (const width of [320, 375, 576, 768, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        const logout = page.getByRole('link', { name: 'Đăng xuất', exact: true });
        assert.equal((await logout.textContent()).trim(), '');
        assert.equal(await logout.getAttribute('title'), 'Đăng xuất');
        assert.equal(await logout.locator('.bi-box-arrow-right').count(), 1);
        assert.deepEqual(await logout.evaluate(el => ({
          border: getComputedStyle(el).borderTopColor,
          background: getComputedStyle(el).backgroundColor,
        })), { border: 'rgba(0, 0, 0, 0)', background: 'rgba(0, 0, 0, 0)' });
        assert.ok(await logout.evaluate(el => {
          const r = el.getBoundingClientRect();
          return r.width >= 44 && r.height >= 44;
        }));
        const nav = page.locator('nav.fixed-bottom');
        const students = nav.getByRole('link', { name: 'Học sinh', exact: true });
        assert.equal(await students.getAttribute('href'), '/teacher/students');
        assert.equal((await students.getAttribute('class')).includes('border-top'), path.startsWith('/teacher/students'));
        const exams = nav.getByRole('link', { name: 'Đề thi', exact: true });
        const examIcon = exams.locator('i');
        assert.ok(await examIcon.isVisible());
        assert.notEqual(await examIcon.evaluate(el => getComputedStyle(el, '::before').content), 'none');
        assert.equal((await exams.getAttribute('class')).includes('border-top'), path === '/teacher/exams');
        const bounds = await nav.locator('a').evaluateAll(elements => elements.map(element => {
          const r = element.getBoundingClientRect();
          return { left: r.left, right: r.right, height: r.height, text: element.textContent.trim() };
        }));
        assert.equal(bounds.length, 6);
        assert.ok(bounds.every(r => r.left >= 0 && r.right <= width + 0.5 && r.height >= 44), JSON.stringify({ width, bounds }));
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${path} at ${width}`);
        if (path.includes('/scores/')) {
          const layout = await page.locator('.score-results-search').evaluate(el => {
            const input = el.querySelector('.form-control').getBoundingClientRect();
            const check = el.querySelector('.form-check').getBoundingClientRect();
            const label = el.querySelector('label');
            const range = document.createRange();
            range.selectNodeContents(label);
            return { sameRow: Math.abs(input.top - check.top) < 2,
              lines: range.getClientRects().length, fits: el.scrollWidth <= el.clientWidth,
              inputWidth: input.width };
          });
          assert.ok(layout.sameRow && layout.fits && layout.inputWidth > 0, JSON.stringify({ width, layout }));
          assert.equal(layout.lines, 1);
        }
        const content = await page.locator('body').textContent();
        for (const secret of ['PRIVATE_PARENT_NAME', 'PRIVATE_PARENT_PHONE', 'PRIVATE_STUDENT_NOTE', 'PRIVATE_OTHER_CLASS']) {
          assert.ok(!content.includes(secret));
        }
      }
      if (path.includes('?')) {
        assert.equal(await page.locator('[name="q"]').inputValue(), 'Synthetic');
        const card = page.getByRole('link', { name: 'Xem học tập Synthetic student', exact: true });
        assert.ok(await card.getAttribute('href'));
        assert.equal(await page.locator('.bi-eye').count(), 0);
        await card.hover();
        assert.equal(await card.evaluate(el => getComputedStyle(el).cursor), 'pointer');
        await card.focus();
        assert.equal(await card.evaluate(el => el === document.activeElement), true);
      } else if (path === '/teacher/exams') {
        assert.equal(await page.locator('.teacher-bottom-nav .bi-pc-display-fill').count(), 0);
        const filter = page.getByRole('button', { name: 'Lọc', exact: true });
        assert.equal(await filter.getAttribute('type'), 'submit');
        assert.equal((await filter.textContent()).trim(), '');
        assert.equal(await filter.locator('.bi-funnel').count(), 1);
        assert.deepEqual(await filter.evaluate(el => ({
          border: getComputedStyle(el).borderTopColor,
          background: getComputedStyle(el).backgroundColor,
        })), { border: 'rgba(0, 0, 0, 0)', background: 'rgba(0, 0, 0, 0)' });
      } else if (path.includes('/scores/')) {
        assert.equal(await page.locator('#detailFailed').count(), 1);
      } else if (path !== '/teacher/students') {
        assert.equal(await page.locator('form[method="post"]').count(), 0);
        assert.ok((await page.locator('body').textContent()).includes('0.0/10.0'));
      } else {
        assert.ok(await page.getByRole('link', { name: /Synthetic class/ }).getAttribute('href'));
      }
    }
    const pages = JSON.parse(rendered.stdout);
    await page.unroute('**/*');
    await page.route('https://teacher.test/**', route => {
      const url = new URL(route.request().url());
      const key = Object.keys(pages).find(path => path.split('?')[0] === url.pathname);
      return route.fulfill({ contentType: 'text/html', body: key
        ? pages[key].replace(/<link\b[^>]*>/g, '').replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
        : 'Not found' });
    });
    await page.goto('https://teacher.test/teacher/students');
    await page.getByRole('link', { name: /Synthetic class/ }).click();
    assert.ok(new URL(page.url()).pathname.includes('/students/class/'));
    const studentCard = page.getByRole('link', { name: 'Xem học tập Synthetic student', exact: true });
    const expectedTarget = await studentCard.getAttribute('href');
    await studentCard.locator('.card-body').click({ position: { x: 5, y: 5 } });
    assert.equal(new URL(page.url()).pathname + new URL(page.url()).search, expectedTarget);
    assert.ok(/\/students\/\d+$/.test(new URL(page.url()).pathname));
    assert.ok((await page.locator('body').textContent()).includes('0.0/10.0'));
    await page.getByRole('link', { name: /học sinh trong lớp/ }).click();
    assert.ok(new URL(page.url()).pathname.includes('/students/class/'));
    console.log('PASS: class → roster → learning detail and back navigation; six-item bottom nav fits 320–1440px, active Students link, no overflow/private data, zero score preserved, read-only detail.');
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
