// Run with: node test_responsive_pages.js
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { spawnSync, execFileSync } = require('node:child_process');
const { chromium } = require('playwright');

const fixture = spawnSync('./venv/bin/python', ['-c', `
import json
from flask import g, render_template
from flask_login import login_user
from models import User
from extensions import db
from test_teacher_students import TeacherStudentsTests
TeacherStudentsTests.setUpClass()
t = TeacherStudentsTests()
t.setUp()
pages = {}
try:
    t.populate()
    teacher_paths = ['/teacher/', '/teacher/schedule', '/teacher/intensive/create',
        '/teacher/scores', '/teacher/notifications', '/teacher/attendance',
        '/teacher/exams', '/teacher/exams/create?mode=compose', '/teacher/students',
        f'/teacher/scores/{t.class_.id}/detail', f'/teacher/students/class/{t.class_.id}',
        f'/teacher/students/{t.student.id}']
    for path in teacher_paths:
        response = t.client.get(path)
        assert response.status_code == 200, (path, response.status_code)
        pages[path] = response.get_data(as_text=True)
    with t.app.test_request_context('/teacher/exams/1/attempts/1'):
        login_user(t.teacher.user)
        t.exam.questions_json = json.dumps({'groups': [{
            'type': 'essay', 'title': 'Chemistry', 'questions': [{
                'text': 'Synthetic chemistry question',
                'explanation': '## Trong một chu kì đi từ trái sang phải, tính base của các oxide cao nhất giảm dần\\n\\nNormal explanation',
            }],
        }]})
        pages['teacher-preview-heading'] = render_template(
            'teacher/exams_preview.html', exam=t.exam, can_edit_exam=True,
            is_shared_source=False, classes=[])
        question = dict(position=1, source_index=0, text='LongQuestionWithoutSpaces' * 8,
                        student_answer='answer', correct_answers=['answer'], explanation='Explanation')
        from types import SimpleNamespace
        pages['teacher-attempt-long-question'] = render_template(
            'teacher/exam_attempt_detail.html', exam=t.exam,
            attempt=SimpleNamespace(id=1, student=t.student, submitted_at=None, cheat_count=0, was_flagged=False),
            result={}, duration=None, sections=[], groups=[dict(group_index=0,
            title='Synthetic questions', type='short_answer', questions=[question])])
    admin = User(username='responsive_admin', role='admin', is_master=True, password_hash='test')
    db.session.add(admin)
    db.session.commit()
    t.login(admin)
    with t.client.session_transaction() as session:
        session['active_role'] = 'admin'
    for suffix in ['', 'students', 'students/add', 'classes', 'classes/add', 'tuition',
        'expenses', 'salary', 'rewards', 'documents', 'reports', 'settings',
        'settings/bank-accounts', 'inquiries', 'accounts', 'permission', 'courses',
        'teachers', 'teachers/add', 'rooms', 'schools', 'attendance', 'exam',
        'leave-requests', 'exam/content-templates']:
        path = '/admin/' + suffix
        response = t.client.get(path)
        assert response.status_code == 200, (path, response.status_code)
        pages[path] = response.get_data(as_text=True)
    for path in ['/', '/auth/login']:
        response = t.app.test_client().get(path)
        if response.status_code == 200:
            pages[path] = response.get_data(as_text=True)
    parent = User(username='responsive_parent', role='parent', password_hash='test')
    student_user = User(username='responsive_student', role='student', password_hash='test')
    t.student.parent_user = parent
    t.student.student_user = student_user
    db.session.add_all([parent, student_user])
    db.session.commit()
    t.login(parent)
    with t.client.session_transaction() as session:
        session['active_role'] = 'parent'
    for path in ['/parent/change-password', '/parent/notifications'] + [
        f'/parent/students/{t.student.id}' + suffix for suffix in
        ['', '/attendance', '/scores', '/homework', '/schedule', '/rewards', '/tuition', '/documents', '/exams']
    ]:
        response = t.client.get(path)
        assert response.status_code == 200, (path, response.status_code)
        pages[path] = response.get_data(as_text=True)
    t.login(student_user)
    with t.client.session_transaction() as session:
        session['active_role'] = 'student'
    response = t.client.get('/student/exams')
    assert response.status_code == 200
    pages['/student/exams'] = response.get_data(as_text=True)
    print(json.dumps(pages))
finally:
    t.tearDown()
    TeacherStudentsTests.tearDownClass()
`], { encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 });
assert.equal(fixture.status, 0, fixture.stderr);
const pages = JSON.parse(fixture.stdout);
const css = execFileSync('curl', ['-fsSL', '--max-time', '30',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css'], { encoding: 'utf8' });

(async () => {
  const browser = await chromium.launch();
  const failures = [];
  try {
    const page = await browser.newPage();
    await page.route('**/*', route => route.abort());
    for (const [path, html] of Object.entries(pages)) {
      const localCss = [...html.matchAll(/href="\/static\/([^"?]+\.css)(?:\?[^"]*)?"/g)]
        .map(match => fs.readFileSync(`static/${match[1]}`, 'utf8')).join('\n');
      await page.setContent(html.replace(/<link\b[^>]*>/g, '')
        .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
        .replace('</head>', `<style>${css}\n${localCss}</style></head>`));
      for (const width of [320, 375, 576, 768, 992, 1440, 1920]) {
        await page.setViewportSize({ width, height: 900 });
        const overflow = await page.evaluate(() => {
          if (document.documentElement.scrollWidth <= innerWidth + 1) return [];
          return [...document.querySelectorAll('body *')].filter(el => {
            const r = el.getBoundingClientRect();
            return r.width && r.right > innerWidth + 1
              && !el.closest('.table-responsive, .modal, .sidebar, .offcanvas')
              && getComputedStyle(el).position !== 'fixed';
          }).slice(0, 5).map(el => `${el.tagName}.${el.className}`);
        });
        if (overflow.length) failures.push({ path, width, overflow });
        if (path === 'teacher-attempt-long-question') {
          const edit = page.getByRole('button', { name: 'Sửa nội dung câu 1', exact: true });
          const bounds = await edit.boundingBox();
          assert.ok(bounds && bounds.x >= 0 && bounds.x + bounds.width <= width,
            `Question edit button must stay on-screen at ${width}px`);
          assert.ok(await page.locator('.attempt-question-text').evaluate(el =>
            el.scrollWidth <= el.clientWidth + 1), `Question text must wrap at ${width}px`);
        }
        if (path === 'teacher-preview-heading') {
          assert.ok(await page.locator('.exam-answer-explanation-content h2').evaluate(el =>
            getComputedStyle(el).fontSize === getComputedStyle(el.parentElement).fontSize),
          'Markdown heading in explanation must not enlarge the text');
        }
      }
      if (path === 'teacher-attempt-long-question') {
        await page.evaluate(() => {
          const original = document.querySelector('[data-attempt-state]');
          for (const state of ['wrong', 'partial', 'blank', 'pending', 'graded']) {
            const clone = original.cloneNode(true);
            clone.removeAttribute('id');
            clone.dataset.attemptState = state;
            original.parentElement.append(clone);
          }
        });
        await page.addScriptTag({ content: fs.readFileSync('static/js/attempt-filters.js', 'utf8') });
        assert.equal(await page.locator('[data-filter-count="all"]').textContent(), '(6)');
        assert.equal(await page.locator('[data-filter-count="correct"]').textContent(), '(1)');
        assert.equal(await page.locator('[data-filter-count="wrong"]').textContent(), '(3)');
        for (const [filter, count] of [['correct', 1], ['wrong', 3], ['original', 6], ['all', 6]]) {
          await page.locator(`[data-attempt-filter="${filter}"]`).click();
          assert.equal(await page.locator('[data-attempt-state]:visible').count(), count);
          if (filter === 'original') {
            assert.equal(await page.locator('[data-attempt-review]:visible').count(), 0);
            assert.equal(await page.locator('[data-attempt-original]:not([hidden])').count(), 6);
          }
        }
      }
    }
    assert.deepEqual(failures, [], JSON.stringify(failures, null, 2));
    console.log(`PASS: ${Object.keys(pages).length} rendered pages at 320/375/576/768/992/1440/1920px; no page-level horizontal overflow.`);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
