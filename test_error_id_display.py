import unittest

from flask import render_template_string

from app import create_app
from config import Config, config
from extensions import db


class ErrorDisplayConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'synthetic-error-display'
    ACADEMIC_ROLLOVER_ENABLED = False


class ErrorIdDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config['error_display_test'] = ErrorDisplayConfig
        cls.app = create_app('error_display_test')

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.engine.dispose()
        config.pop('error_display_test')

    def test_labels_below_segments_and_answer_not_leaked_to_student(self):
        with self.app.app_context():
            render = self.app.jinja_env.filters['error_id_render']
            text = '[A:She] [*B:go] [C:to school] [D:every day].'
            hidden = str(render(text, False))
            self.assertEqual(hidden.count('exam-error-label'), 4)
            self.assertIn('exam-error-underline">go</span><span class="exam-error-label">B', hidden)
            self.assertNotIn('text-success', hidden)
            self.assertNotIn('<sup>', hidden)
            self.assertIn('text-success', str(render(text)))
            self.assertIn('&lt;script&gt;', str(render('[A:<script>] [*B:x]')))

    def test_review_buttons_match_labels_and_mark_selected_and_correct(self):
        with self.app.test_request_context():
            html = render_template_string(
                "{% from 'exams/_macros.html' import render_error_id_choices %}"
                "{{ render_error_id_choices(text, 'B', 'D') }}",
                text='[A:She] [*B:go] [C:to school] [D:every day].',
            )
            self.assertEqual(html.count('<span class="btn btn-sm'), 4)
            self.assertIn('btn-success', html)
            self.assertIn('btn-danger is-selected', html)
            self.assertIn('Đã chọn', html)
            self.assertIn('Đáp án đúng', html)

    def test_preview_and_legacy_six_labels_preserved(self):
        with self.app.test_request_context():
            html = render_template_string(
                "{% from 'exams/_macros.html' import render_question %}"
                "{{ render_question(q, 'error_id', 1) }}",
                q={'text': '[A:a] [B:b] [C:c] [D:d] [E:e] [*F:f]',
                   'correct_label': 'F', 'explanation': ''},
            )
            self.assertEqual(html.count('<span class="btn btn-sm'), 6)
            self.assertIn('exam-error-choices', html)
