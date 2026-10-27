// Run with: node test_confirm_editor.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');
const { chromium } = require('playwright');

const rendered = spawnSync('./venv/bin/python', ['-c', `
from types import SimpleNamespace
from flask import render_template_string
from app import create_app
from config import Config, config
from extensions import db
class T(Config):
    TESTING = True
    SECRET_KEY = 'synthetic-confirm-editor'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    ACADEMIC_ROLLOVER_ENABLED = False
config['confirm_editor_test'] = T
app = create_app('confirm_editor_test')
with app.test_request_context():
    print(render_template_string("""
      <meta charset="utf-8">
      <form id="exam-form">
        <input id="examTitle" value="Original title">
        <input id="titleField"><input id="groupsField">
        <div id="localDraftStatus"></div>
        {% include 'exams/_editor.html' %}
      </form>
      <a href="/exit" data-exam-editor-exit>Exit</a>
    """, current_user=SimpleNamespace(is_admin=True, id=1),
       prefill={'groups': []}, editing=False))
with app.app_context():
    db.session.remove()
    db.engine.dispose()
`], { encoding: 'utf8' });
assert.equal(rendered.status, 0, rendered.stderr);

(async () => {
  const browser = await chromium.launch();
  try {
    for (const restore of [false, true]) {
      const page = await browser.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('dialog', dialog => {
        errors.push(`Unexpected native dialog: ${dialog.message()}`);
        dialog.dismiss();
      });
      await page.route('https://popup.test/**', route => {
        const isEditor = new URL(route.request().url()).pathname === '/editor';
        return route.fulfill({
          contentType: isEditor ? 'text/html; charset=utf-8' : 'application/json',
          body: isEditor ? rendered.stdout : JSON.stringify({
            templates: [{ id: 1, name: 'Sample', content: '## Sample {essay}\nCâu 1: New question' }],
          }),
        });
      });
      await page.goto('https://popup.test/editor');
      await page.addStyleTag({ content: fs.readFileSync('static/css/custom.css', 'utf8') });
      await page.addStyleTag({ content: fs.readFileSync('static/css/exam-editor.css', 'utf8') });
      await page.evaluate(() => {
        window.scheduleExamMathTypeset = () => {};
        const config = JSON.parse(document.getElementById('examEditorConfig').textContent);
        localStorage.setItem(config.draftKey, JSON.stringify({
          title: 'Saved title', groups: [], savedAt: Date.now(),
          rawText: '## Saved {essay}\nCâu 1: Saved question',
        }));
      });
      await page.addScriptTag({ content: fs.readFileSync('static/js/messages.js', 'utf8') });
      await page.addScriptTag({ content: fs.readFileSync('static/js/exam-editor.js', 'utf8') });
      assert.equal(await page.locator('#appMessageText').textContent(),
        'Tìm thấy bản nháp trên thiết bị. Bạn có muốn khôi phục không?');
      await page.getByRole('button', { name: restore ? 'Đồng ý' : 'Hủy', exact: true }).click();
      await page.waitForFunction(() => !document.getElementById('examSampleSelect').disabled);
      assert.equal(await page.locator('#examTitle').inputValue(), restore ? 'Saved title' : 'Original title');
      assert.equal((await page.locator('#rawTextEditor').inputValue()).includes('Saved question'), restore);
      if (!restore) {
        assert.equal(await page.evaluate(() => localStorage.getItem(
          JSON.parse(document.getElementById('examEditorConfig').textContent).draftKey)), null);
      }

      await page.locator('#rawTextEditor').fill('## Current {essay}\nCâu 1: Keep this question');
      await page.waitForFunction(() => !document.getElementById('examSampleSelect').disabled);
      await page.locator('#examSampleSelect').selectOption('1');
      await page.locator('#applyExamSample').click();
      await page.getByRole('button', { name: 'Hủy', exact: true }).click();
      await page.waitForFunction(() => !document.querySelector('.app-message[open]'));
      assert.ok((await page.locator('#rawTextEditor').inputValue()).includes('Keep this question'));
      await page.locator('#applyExamSample').click();
      await page.getByRole('button', { name: 'Đồng ý', exact: true }).click();
      await page.waitForFunction(() => document.getElementById('rawTextEditor').value.includes('New question'));
      await page.getByRole('link', { name: 'Exit', exact: true }).click();
      await page.getByRole('button', { name: 'Hủy', exact: true }).click();
      await page.waitForFunction(() => !document.querySelector('.app-message[open]'));
      assert.equal(page.url(), 'https://popup.test/editor');
      for (const width of [992, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        for (const height of [600, 850]) {
          await page.locator('#rawTextEditor').evaluate((el, size) => {
            el.style.height = `${size}px`;
          }, height);
          await page.locator('#examSyntaxHelp').evaluate((el, open) => { el.open = open; }, height === 850);
          const sizes = await page.locator('#examComposer').evaluate(el => {
            const preview = el.querySelector('.exam-compose-preview').getBoundingClientRect();
            const source = el.querySelector('.exam-compose-source').getBoundingClientRect();
            return { preview: preview.height, source: source.height, top: preview.top - source.top };
          });
          assert.ok(Math.abs(sizes.preview - sizes.source) <= 1, JSON.stringify(sizes));
          assert.equal(sizes.top, 0);
        }
      }
      await page.setViewportSize({ width: 375, height: 800 });
      assert.equal(await page.locator('.exam-compose-preview').isVisible(), false);
      await page.locator('[data-editor-pane="preview"]').click();
      assert.equal(await page.locator('.exam-compose-source').isVisible(), false);
      assert.equal(await page.locator('.exam-compose-preview').isVisible(), true);
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log('PASS: real editor markup/script; restore or discard local draft; apply sample only on acceptance; cancel exit retains page; no native dialogs.');
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
