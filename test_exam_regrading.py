"""Focused tests for refreshing submitted exam grades after answer-key changes."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg

from blueprints.exams_shared import (
    attempt_result_is_stale,
    edited_question_from_form,
    exam_is_assigned_to_student,
    has_stale_scoring,
    parse_confirm_settings,
    regrade_attempt_if_stale,
)
from blueprints.teacher_exams import _validate_teacher_assignment_targets
from models import Class
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import Forbidden


class Attempt:
    status = 'submitted'
    order_data = {'groups': [{'q_order': [0], 'opt_orders': {'0': [0, 1]}}]}
    answers = {'g0_q1': '1'}
    score = 0
    result_json = json.dumps({
        'earned': 0.0,
        'total': 1.0,
        'percent': 0,
        'score_10': 0.0,
        'scoring_mode': 'question',
        'breakdown': [{'title': 'Phần 1', 'type': 'mcq', 'earned': 0.0, 'total': 1.0}],
    })

    @property
    def result(self):
        return json.loads(self.result_json)


class AttemptCollection:
    def __init__(self, attempts):
        self.items = attempts

    def filter_by(self, **kwargs):
        return self

    def all(self):
        return self.items


class SubmittedAttemptRegradingTests(unittest.TestCase):
    def test_confirm_class_ids_use_integer_query_parameters_for_all_scoring_modes(self):
        groups = [{'title': 'Section 1', 'type': 'mcq', 'questions': [{}]}]
        for mode in ('question', 'section', 'question_custom', 'section_custom'):
            with self.subTest(mode=mode):
                form = MultiDict([
                    ('class_ids', '014'), ('class_ids', '14'), ('class_ids', '15'),
                    ('scoring_mode', mode), ('section_points_0', '10'),
                    ('question_points_0_0', '1'), ('is_draft', 'published'),
                ])
                query = Mock()
                query.filter.return_value.count.return_value = 2
                with patch('blueprints.exams_shared.Class', SimpleNamespace(
                    id=Class.id, is_active=Class.is_active, query=query,
                )):
                    settings, error = parse_confirm_settings(form, groups)

                self.assertIsNone(error)
                self.assertEqual(settings['class_ids'], ['14', '15'])
                self.assertEqual(settings['scoring_mode'], mode)
                self.assertEqual(settings['scoring_config']['section_points'], [10.0])
                class_filter = query.filter.call_args.args[0]
                compiled = class_filter.compile(
                    dialect=PGDialect_psycopg(),
                    compile_kwargs={'render_postcompile': True},
                )
                self.assertEqual(list(compiled.params.values()), [14, 15])
                self.assertNotIn('VARCHAR', str(compiled))

    def test_teacher_assignment_validation_uses_visible_accessible_class_roster(self):
        school = SimpleNamespace(id=4)
        student = SimpleNamespace(id=12)
        accessible_class = SimpleNamespace(id=7)

        with patch(
            'blueprints.teacher_exams._teacher_accessible_classes',
            return_value=[accessible_class],
        ), patch(
            'blueprints.teacher_exams.exam_assignment_options',
            return_value=([school], [student]),
        ) as options:
            _validate_teacher_assignment_targets([4], [12])
            options.assert_called_once_with([7])

        with patch(
            'blueprints.teacher_exams._teacher_accessible_classes',
            return_value=[accessible_class],
        ), patch(
            'blueprints.teacher_exams.exam_assignment_options',
            return_value=([school], [student]),
        ):
            with self.assertRaises(Forbidden):
                _validate_teacher_assignment_targets([], [13])

    def test_exam_targets_match_selected_class_school_or_student(self):
        student = SimpleNamespace(id=12, school_id=4)
        exam = SimpleNamespace(class_list=[7], school_list=[4], student_list=[12], creator=None)

        self.assertTrue(exam_is_assigned_to_student(exam, student, active_class_ids={7}))
        self.assertTrue(exam_is_assigned_to_student(exam, student, active_class_ids={9}))
        self.assertTrue(exam_is_assigned_to_student(
            SimpleNamespace(class_list=[], school_list=[], student_list=[12], creator=None),
            student,
            active_class_ids=set(),
        ))
        self.assertFalse(exam_is_assigned_to_student(
            SimpleNamespace(class_list=[], school_list=[5], student_list=[], creator=None),
            student,
            active_class_ids={9},
        ))
        self.assertFalse(exam_is_assigned_to_student(
            SimpleNamespace(class_list=[7], school_list=[], student_list=[], creator=None),
            student,
            active_class_ids={9},
        ))

    def test_teacher_school_target_is_limited_to_assigned_classes(self):
        student = SimpleNamespace(id=12, school_id=4)
        exam = SimpleNamespace(class_list=[], school_list=[4], student_list=[], creator=None)

        self.assertTrue(exam_is_assigned_to_student(
            exam, student, active_class_ids={7}, teacher_class_ids={7, 9},
        ))
        self.assertFalse(exam_is_assigned_to_student(
            exam, student, active_class_ids={12}, teacher_class_ids={7, 9},
        ))

    def test_stale_grade_is_refreshed_from_current_answer_key(self):
        attempt = Attempt()
        exam = SimpleNamespace(
            question_groups=[{
                'title': 'Phần 1',
                'type': 'mcq',
                'questions': [{
                    'text': 'Câu hỏi',
                    'options': ['A', 'B'],
                    'correct_index': 0,
                }],
            }],
            scoring_mode='question',
            scoring_config={},
            attempts=AttemptCollection([attempt]),
        )

        self.assertTrue(attempt_result_is_stale(exam, attempt))
        self.assertTrue(has_stale_scoring(exam, 'question'))
        self.assertTrue(regrade_attempt_if_stale(exam, attempt))
        self.assertEqual(attempt.result['score_10'], 10.0)
        self.assertEqual(attempt.score, 100)
        self.assertFalse(attempt_result_is_stale(exam, attempt))
        self.assertFalse(regrade_attempt_if_stale(exam, attempt))

        attempt.score = 0
        self.assertTrue(attempt_result_is_stale(exam, attempt))
        self.assertTrue(regrade_attempt_if_stale(exam, attempt))
        self.assertEqual(attempt.score, 100)

    def test_per_question_editor_updates_mcq_key_without_changing_shape(self):
        question = {
            'text': 'Old question',
            'options': ['Old A', 'Old B'],
            'correct_index': 1,
            'explanation': '',
        }
        form = MultiDict([
            ('text', 'Updated question'),
            ('explanation', 'Because of this.'),
            ('option_0', 'New A'),
            ('option_1', 'New B'),
            ('correct_index', '0'),
        ])

        updated, error = edited_question_from_form('mcq', question, form)

        self.assertIsNone(error)
        self.assertEqual(updated['text'], 'Updated question')
        self.assertEqual(updated['options'], ['New A', 'New B'])
        self.assertEqual(updated['correct_index'], 0)
        self.assertEqual(len(updated['options']), len(question['options']))

    def test_per_question_editor_updates_true_false_and_short_answers(self):
        tf_question = {
            'text': 'Old statement group',
            'statements': [{'text': 'Old a', 'correct': False}, {'text': 'Old b', 'correct': True}],
        }
        tf_form = MultiDict([
            ('text', 'Updated group'),
            ('statement_0', 'Updated a'),
            ('statement_correct_0', '1'),
            ('statement_1', 'Updated b'),
            ('statement_correct_1', '0'),
        ])
        updated_tf, tf_error = edited_question_from_form('true_false', tf_question, tf_form)
        self.assertIsNone(tf_error)
        self.assertEqual(
            updated_tf['statements'],
            [{'text': 'Updated a', 'correct': True}, {'text': 'Updated b', 'correct': False}],
        )

        short_question = {'text': 'Old question', 'accepted_answers': ['one']}
        short_form = MultiDict([
            ('text', 'Updated question'),
            ('accepted_answers', 'first answer\nsecond answer'),
        ])
        updated_short, short_error = edited_question_from_form('short_answer', short_question, short_form)
        self.assertIsNone(short_error)
        self.assertEqual(updated_short['accepted_answers'], ['first answer', 'second answer'])

    def test_per_question_editor_rejects_invalid_answer_key(self):
        question = {
            'text': 'Question',
            'options': ['A', 'B'],
            'correct_index': 0,
            'explanation': '',
        }
        form = MultiDict([
            ('text', 'Question'),
            ('option_0', 'A'),
            ('option_1', 'B'),
            ('correct_index', '5'),
        ])

        updated, error = edited_question_from_form('mcq', question, form)

        self.assertIsNone(updated)
        self.assertIsNotNone(error)


if __name__ == '__main__':
    unittest.main()
