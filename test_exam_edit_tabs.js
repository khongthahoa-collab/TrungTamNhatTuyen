// Run with: node test_exam_edit_tabs.js
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { spawnSync, execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const fixture = spawnSync('./venv/bin/python', ['-c', `
from test_teacher_students import TeacherStudentsTests
from extensions import db
import json
TeacherStudentsTests.setUpClass()
t = TeacherStudentsTests()
t.setUp()
try:
    t.populate()
    t.exam.questions_json = json.dumps({'groups': [{'type': 'essay', 'title': 'Essay',
        'questions': [{'text': 'Original question', 'explanation': ''}]}]})
    db.session.commit()
    response = t.client.get(f'/teacher/exams/edit/{t.exam.id}?tab=settings')
    assert response.status_code == 200
    print(response.get_data(as_text=True))
finally:
    t.tearDown()
    TeacherStudentsTests.tearDownClass()
`], { encoding: 'utf8' });
assert.equal(fixture.status, 0, fixture.stderr);
const fetchAsset = url => execFileSync('curl', ['-fsSL', '--max-time', '30', url], { encoding: 'utf8' });
const css = fetchAsset('https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css');
const bootstrap = fetchAsset('https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js');
const jquery = fetchAsset('https://cdn.jsdelivr.net/npm/jquery@3.7.1/dist/jquery.min.js');
const select2 = fetchAsset('https://cdn.jsdelivr.net/npm/select2@4.1.0-rc.0/dist/js/select2.min.js');
(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('https://edit.test/**', route => route.fulfill({
      contentType: 'application/json', body: '{"templates":[]}',
    }));
    await page.goto('https://edit.test/');
    await page.setContent(fixture.stdout.replace(/<link\b[^>]*>/g, '')
      .replace(/<script\b(?![^>]*application\/json)[^>]*>[\s\S]*?<\/script>/g, '')
      .replace('</head>', `<style>${css}\n${fs.readFileSync('static/css/custom.css', 'utf8')}\n${fs.readFileSync('static/css/exam-editor.css', 'utf8')}</style></head>`));
    await page.addScriptTag({ content: bootstrap });
    await page.addScriptTag({ content: jquery });
    await page.addScriptTag({ content: select2 });
    await page.evaluate(() => { window.scheduleExamMathTypeset = () => {}; });
    await page.addScriptTag({ content: fs.readFileSync('static/js/messages.js', 'utf8') });
    await page.addScriptTag({ content: fs.readFileSync('static/js/exam-editor.js', 'utf8') });
    const settingsScript = [...fixture.stdout.matchAll(/<script>([\s\S]*?)<\/script>/g)]
      .map(m => m[1]).find(code => code.includes('syncSubjectOther'));
    await page.addScriptTag({ content: settingsScript });
    await page.addScriptTag({ content: fs.readFileSync('static/js/exam-edit-tabs.js', 'utf8') });
    assert.equal(await page.locator('#examSettingsPane').isVisible(), true);
    await page.locator('[name="description"]').fill('Unsaved settings');
    await page.locator('#examContentTab').click();
    await page.locator('#examTitle').fill('Updated title');
    await page.locator('#rawTextEditor').fill('## Essay {essay}\nCâu 1: Updated question');
    await page.locator('#examSettingsTab').click();
    assert.equal(await page.locator('[name="description"]').inputValue(), 'Unsaved settings');
    await page.locator('#examContentTab').click();
    assert.ok((await page.locator('#rawTextEditor').inputValue()).includes('Updated question'));
    await page.evaluate(() => {
      document.getElementById('exam-settings-form').addEventListener('submit', event => {
        event.preventDefault();
        window.savedForm = Object.fromEntries(new FormData(event.currentTarget));
      });
    });
    for (const width of [320, 375, 768, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.locator('#examSettingsTab').click();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      const layout = await page.evaluate(() => {
        const columns = [...document.querySelectorAll('#exam-settings-form > .row > .col-lg-6')];
        const [left, right] = columns.map(el => el.getBoundingClientRect());
        const saves = [...document.querySelectorAll('#exam-settings-form [data-guide="save"]')];
        const topSave = saves[0].getBoundingClientRect();
        const save = saves[1].getBoundingClientRect();
        return {
          columns: columns.length,
          sideBySide: Math.abs(left.top - right.top) < 1,
          footerBelow: save.top >= Math.max(left.bottom, right.bottom),
          headerAbove: topSave.bottom <= Math.min(left.top, right.top),
          saveCount: saves.length,
          cards: columns.map(el => el.querySelectorAll('.card').length),
        };
      });
      assert.equal(layout.columns, 2);
      assert.equal(layout.sideBySide, width >= 992);
      assert.equal(layout.footerBelow, true);
      assert.equal(layout.headerAbove, true);
      assert.equal(layout.saveCount, 2);
      assert.deepEqual(layout.cards, [2, 3]);
    }
    await page.locator('#examSettingsTab').click();
    await page.locator('#exam-settings-form button[type="submit"]').first().click();
    const saved = await page.evaluate(() => window.savedForm);
    assert.equal(saved.title, 'Updated title');
    assert.equal(saved.description, 'Unsaved settings');
    assert.equal(JSON.parse(saved.groups_json).groups[0].questions[0].text, 'Updated question');
    await page.evaluate(() => { delete window.savedForm; });
    await page.locator('#exam-settings-form button[type="submit"]').last().click();
    assert.deepEqual(await page.evaluate(() => window.savedForm), saved);
    await page.locator('#examContentTab').click();
    await page.locator('#rawTextEditor').fill('## Essay {essay}\nCâu 1: Updated question\nCâu 2: Additional question');
    await page.locator('#examSettingsTab').click();
    assert.equal(await page.locator('[name="question_points_0_1"]').count(), 1);
    await page.locator('#examContentTab').click();
    await page.evaluate(() => { delete window.savedForm; });
    await page.locator('#exam-form button[name="quick_save"]').first().click();
    await page.waitForFunction(() => !!window.savedForm);
    const fromContent = await page.evaluate(() => window.savedForm);
    assert.equal(JSON.parse(fromContent.groups_json).groups[0].questions.length, 2);
    assert.equal(fromContent.description, 'Unsaved settings');
    assert.deepEqual(errors, []);
    console.log('PASS: settings entry tab, preserved unsaved values, combined save payload, responsive 320–1440px.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
