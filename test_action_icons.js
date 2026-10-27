// Run with: node test_action_icons.js
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { spawnSync, execFileSync } = require('node:child_process');
const { chromium } = require('playwright');

const rendered = spawnSync('./venv/bin/python', ['-c', `
import json
from datetime import datetime
from types import SimpleNamespace
from flask import g, render_template, render_template_string
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
    for path in ['/admin/exam/content-templates', '/admin/settings/bank-accounts', '/admin/rooms',
                 '/admin/accounts', '/admin/courses', '/admin/students', '/admin/documents', '/admin/exam']:
        response = client.get(path)
        assert response.status_code == 200
        pages[path] = response.get_data(as_text=True)
    g.pop('_login_user', None)
    with client.session_transaction() as session:
        session['_user_id'] = str(reader.id)
    response = client.get('/admin/exam/content-templates')
    assert response.status_code == 200
    pages['reader'] = response.get_data(as_text=True)
    doc = SimpleNamespace(id=1, title='Synthetic document', description='',
                          original_filename='sample.pdf', created_at=datetime(2026, 10, 1),
                          file_size=1024)
    student = SimpleNamespace(id=1, full_name='Synthetic student')
    with app.test_request_context():
        date = datetime(2026, 10, 1).date()
        pages['teacher-schedule'] = render_template(
            'teacher/schedule.html', current_user=User(role='teacher', full_name='Teacher'),
            ref_date=date, prev2_date=date, prev_date=date, next_date=date, next2_date=date,
            monday=date, sunday=date, today=date, this_week_start=date, this_month_start=date,
            filter_mode='all', present_days=[], has_any=False, has_next=False)
        pages['parent-documents'] = render_template(
            'parent/documents.html', current_user=User(role='parent'), student=student,
            children=[student], docs_by_class={'Synthetic class': [doc]}, unread_notifications=1)
        pages['student-header'] = render_template_string(
            "{% extends 'student/base.html' %}",
            current_user=SimpleNamespace(student_profile=student))
        pages['login'] = render_template('auth/login.html')
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
        const accountPage = path === '/admin/accounts';
        const actions = page.locator(accountPage ? '.acct-action-btn' : '.action-icon-btn');
        assert.ok(await actions.count() > 0);
        for (let i = 0; i < await actions.count(); i++) {
          const action = actions.nth(i);
          if (!await action.isVisible()) continue;
          const details = await action.evaluate(element => {
            const rect = element.getBoundingClientRect();
            const content = element.cloneNode(true);
            content.querySelectorAll('.badge').forEach(badge => badge.remove());
            return {
              w: rect.width, h: rect.height, x: rect.x, right: rect.right,
              title: element.title, label: element.getAttribute('aria-label'),
              text: content.textContent.trim(),
              hidden: element.querySelector('i')?.getAttribute('aria-hidden'),
              radius: getComputedStyle(element).borderRadius,
              plain: element.classList.contains('icon-action-plain'),
              border: getComputedStyle(element).borderTopColor,
              background: getComputedStyle(element).backgroundColor,
            };
          });
          const minSize = 44;
          assert.ok(details.w >= minSize && details.h >= minSize, JSON.stringify({ path, width, details }));
          assert.equal(details.radius, '50%');
          if (details.plain) {
            assert.equal(details.border, 'rgba(0, 0, 0, 0)');
            assert.equal(details.background, 'rgba(0, 0, 0, 0)');
          }
          if (!accountPage) {
            assert.ok(details.x >= 0 && details.right <= width, JSON.stringify({ path, width, details }));
          }
          if (path === 'login') {
            const source = fs.readFileSync('templates/auth/login.html', 'utf8');
            const toggle = source.slice(source.indexOf('function togglePw()'), source.indexOf('</script>', source.indexOf('function togglePw()')));
            await page.addScriptTag({ content: toggle });
            const eye = page.locator('button:has(#pwEye)');
            await eye.click();
            assert.equal(await page.locator('#pwInput').getAttribute('type'), 'text');
            await eye.click();
            assert.equal(await page.locator('#pwInput').getAttribute('type'), 'password');
            await eye.focus();
            assert.equal(await eye.evaluate(el => getComputedStyle(el).backgroundColor), 'rgba(0, 0, 0, 0)');
          }
          assert.ok(details.title && details.label);
          assert.equal(details.text, '');
          assert.equal(details.hidden, 'true');
        }
        if (path === '/admin/accounts') {
          const row = page.locator('tbody tr').filter({ hasText: 'reader' });
          for (const [icon, target] of [
            ['bi-pencil', '#userEditModal'],
            ['bi-shield-lock', '#permEditModal'],
            ['bi-key', '#resetPwdModal'],
          ]) {
            const button = row.locator(`button:has(.${icon})`);
            assert.equal(await button.count(), 1);
            assert.equal(await button.getAttribute('data-bs-target'), target);
            assert.ok(await button.getAttribute('data-user-id'));
          }
          assert.equal(await row.locator('.bi-pencil').count(), 1);
          for (const suffix of ['/lock', '/delete']) {
            const form = row.locator(`form[action$="${suffix}"]`);
            assert.equal(await form.locator('[name="csrf_token"]').count(), 1);
            assert.ok(await form.locator('button').getAttribute('data-confirm'));
          }
          const selfRow = page.locator('tbody tr').filter({
            has: page.locator('td').filter({ hasText: /^master$/ }),
          });
          assert.equal(await selfRow.count(), 1);
          assert.equal(await selfRow.locator('.bi-shield-lock, .bi-trash').count(), 0);
        }
      }
      if (path === 'reader') {
        assert.equal(await page.locator('.action-icon-btn .bi-eye').count(), 1);
        assert.equal(await page.locator('.action-icon-btn .bi-trash').count(), 0);
        assert.equal(await page.locator('.action-icon-btn .bi-pencil').count(), 0);
      }
      if (path === '/admin/exam/content-templates') {
        const form = page.locator('form[action$="/delete"]');
        assert.ok(await form.getAttribute('data-confirm'));
        assert.equal(await form.locator('[name="csrf_token"]').count(), 1);
        assert.ok((await page.locator('a.action-icon-btn[href$="/edit"]').getAttribute('href')).endsWith('/edit'));
      }
    }
    console.log('PASS: Jinja compilation; 44px round actions across admin/teacher/parent/student/login at 320–1440px; distinct account controls, title/ARIA, self-account restrictions, unchanged modal targets/confirmation/CSRF.');
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
