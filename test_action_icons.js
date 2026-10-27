// Run with: node test_action_icons.js
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { spawnSync, execFileSync } = require('node:child_process');
const { chromium } = require('playwright');

const rendered = spawnSync('./venv/bin/python', ['-c', `
import json
from flask import g
from app import create_app
from config import Config, config
from extensions import db
from models import User, PermissionGroup, ExamContentTemplate, BankAccount, Room
class T(Config):
    TESTING = True
    SECRET_KEY = 'synthetic-icons'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    ACADEMIC_ROLLOVER_ENABLED = False
config['icon_test'] = T
app = create_app('icon_test')
with app.app_context():
    db.create_all()
    group = PermissionGroup(name='Reader', permissions='{"exams":"read"}')
    admin = User(username='master', role='admin', is_master=True, password_hash='test')
    reader = User(username='reader', role='admin', permission_group=group, password_hash='test')
    db.session.add_all([admin, reader,
        ExamContentTemplate(name='Mẫu <Test>', content='Synthetic content'),
        BankAccount(bank_id='VCB', bank_name='Synthetic Bank', account_number='0000000000', account_name='TEST'),
        Room(name='Test room')])
    db.session.commit()
    for name in app.jinja_env.list_templates():
        app.jinja_env.get_template(name)
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(admin.id)
        session['_fresh'] = True
    pages = {}
    for path in ['/admin/exam/content-templates', '/admin/settings/bank-accounts', '/admin/rooms']:
        response = client.get(path)
        assert response.status_code == 200
        pages[path] = response.get_data(as_text=True)
    g.pop('_login_user', None)
    with client.session_transaction() as session:
        session['_user_id'] = str(reader.id)
    response = client.get('/admin/exam/content-templates')
    assert response.status_code == 200
    pages['reader'] = response.get_data(as_text=True)
    print(json.dumps(pages))
    db.session.remove()
    db.engine.dispose()
`], { encoding: 'utf8' });
assert.equal(rendered.status, 0, rendered.stderr);
const pages = JSON.parse(rendered.stdout);
const bootstrap = execFileSync('curl', [
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
        .replace('</head>', `<style>${bootstrap}\n${fs.readFileSync('static/css/custom.css', 'utf8')}</style></head>`));
      for (const width of [320, 375, 768, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        await page.waitForTimeout(350);
        const actions = page.locator('.action-icon-btn');
        assert.ok(await actions.count() > 0);
        for (let i = 0; i < await actions.count(); i++) {
          const action = actions.nth(i);
          if (!await action.isVisible()) continue;
          const details = await action.evaluate(element => {
            const rect = element.getBoundingClientRect();
            return {
              w: rect.width, h: rect.height, x: rect.x, right: rect.right,
              title: element.title, label: element.getAttribute('aria-label'),
              text: element.textContent.trim(),
              hidden: element.querySelector('i')?.getAttribute('aria-hidden'),
            };
          });
          assert.ok(details.w >= 44 && details.h >= 44, JSON.stringify({ path, width, details }));
          assert.ok(details.x >= 0 && details.right <= width, JSON.stringify({ path, width, details }));
          assert.ok(details.title && details.label);
          assert.equal(details.text, '');
          assert.equal(details.hidden, 'true');
        }
      }
      if (path === 'reader') {
        assert.equal(await page.locator('.action-icon-btn .bi-eye').count(), 1);
        assert.equal(await page.locator('.action-icon-btn .bi-trash').count(), 0);
        assert.equal(await page.locator('.action-icon-btn .bi-pencil').count(), 0);
      }
      if (path === '/admin/exam/content-templates') {
        const form = page.locator('form[action$="/delete"]');
        assert.ok((await form.getAttribute('onsubmit')).includes('confirm('));
        assert.equal(await form.locator('[name="csrf_token"]').count(), 1);
        assert.ok((await page.locator('a.action-icon-btn').getAttribute('href')).endsWith('/edit'));
      }
    }
    console.log('PASS: all Jinja templates compile; icon actions are 44px at 320–1440px with title/ARIA, no clipped controls, read-only eye/no delete, unchanged edit links/delete confirmation/CSRF.');
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
