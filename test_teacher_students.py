"""Read-only teacher tracking never exposes private student or parent fields."""
from datetime import datetime, time
import json
import unittest
from unittest.mock import patch

from flask import g

from extensions import db
from models import Class, Enrollment, Exam, ExamAttempt, Homework, HomeworkRecord, Schedule, Score, Student, Teacher, User
from test_attendance_warnings import AttendanceWarningTests


class TeacherStudentsTests(unittest.TestCase):
    setUpClass = classmethod(AttendanceWarningTests.setUpClass.__func__)
    tearDownClass = classmethod(AttendanceWarningTests.tearDownClass.__func__)
    setUp = AttendanceWarningTests.setUp
    tearDown = AttendanceWarningTests.tearDown
    login = AttendanceWarningTests.login

    def populate(self):
        self.student.parent_name = 'PRIVATE_PARENT_NAME'
        self.student.parent_phone = 'PRIVATE_PARENT_PHONE'
        self.student.note = 'PRIVATE_STUDENT_NOTE'
        self.student.date_of_birth = self.start
        self.student.current_grade = 'Lớp 8'
        self.hidden_class = Class(name='PRIVATE_OTHER_CLASS', course=self.class_.course,
                                  sessions_per_week=2)
        db.session.add(Enrollment(class_=self.hidden_class, student=self.student,
                                  enrolled_at=datetime.combine(self.start, time())))
        for cls, value in ((self.class_, 0), (self.hidden_class, 9.876)):
            db.session.add(Score(student_id=self.student.id, class_=cls, score_type='oral',
                                 score_value=value, exam_date=self.start))
            homework = Homework(class_=cls, assigned_date=self.start, title=f'Work {cls.name}')
            db.session.add(homework)
            db.session.flush()
            db.session.add(HomeworkRecord(homework=homework, student=self.student, status='not_done'))
        self.exam = Exam(title='Allowed exam', created_by=self.teacher.user_id,
                         class_ids=str(self.class_.id))
        db.session.add(self.exam)
        db.session.commit()

    def test_nav_list_and_detail_are_read_only_and_private_fields_absent(self):
        self.populate()
        for path in ('/teacher/', '/teacher/students', f'/teacher/students/{self.student.id}'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn('href="/teacher/students"', html)
            for private in ('PRIVATE_PARENT_NAME', 'PRIVATE_PARENT_PHONE', 'PRIVATE_STUDENT_NOTE',
                            'PRIVATE_OTHER_CLASS', '9.876'):
                self.assertNotIn(private, html)
        html = self.client.get(f'/teacher/students/{self.student.id}').get_data(as_text=True)
        self.assertIn('0.0/10.0', html)
        self.assertIn('Không làm', html)
        self.assertIn('Chưa làm', html)
        self.assertIn('Allowed exam', html)
        self.assertEqual(self.client.post('/teacher/students').status_code, 405)
        self.assertEqual(self.client.post(f'/teacher/students/{self.student.id}').status_code, 405)

    def test_outsider_or_old_schedule_does_not_grant_roster_access(self):
        self.populate()
        outsider = User(username='outsider', role='teacher', password_hash='test')
        teacher = Teacher(user=outsider)
        db.session.add(teacher)
        db.session.flush()
        db.session.add(Schedule(class_=self.class_, teacher=teacher, date=self.start,
                                start_time=time(10), end_time=time(11)))
        db.session.commit()
        self.login(outsider)
        response = self.client.get('/teacher/students')
        self.assertNotIn(self.student.full_name.encode(), response.data)
        self.assertEqual(self.client.get(f'/teacher/students/{self.student.id}').status_code, 404)
        self.assertEqual(self.client.get(f'/teacher/students?class_id={self.class_.id}').status_code, 404)
        self.class_.assistant_teachers.append(teacher)
        db.session.commit()
        self.assertIn(self.student.full_name.encode(), self.client.get(
            f'/teacher/students/class/{self.class_.id}').data)
        self.assertEqual(self.client.get(f'/teacher/students/{self.student.id}').status_code, 200)

    def test_search_deduplicates_and_preserves_filters_in_pagination(self):
        self.populate()
        self.hidden_class.primary_teacher_id = self.teacher.id
        self.student.full_name = 'Literal %_/'
        for index in range(22):
            db.session.add(Enrollment(class_=self.class_, student=Student(
                full_name=f'Other {index:02}', level='secondary',
            )))
        db.session.commit()
        path = f'/teacher/students/class/{self.class_.id}'
        html = self.client.get(path + '?q=%25_/').get_data(as_text=True)
        self.assertIn('1 học sinh', html)
        self.assertIn('Literal %_/', html)
        response = self.client.get(path, query_string={'q': 'Other'})
        html = response.get_data(as_text=True)
        self.assertIn('22 học sinh', html)
        self.assertIn('q=Other', html)
        self.assertIn(path, html)
        self.assertNotIn('Other 20', html)
        self.assertIn('Other 20', self.client.get(path + '?page=2&q=Other').get_data(as_text=True))

    def test_class_first_navigation_and_scope(self):
        self.populate()
        path = f'/teacher/students/class/{self.class_.id}'
        html = self.client.get('/teacher/students').get_data(as_text=True)
        self.assertIn(f'href="{path}"', html)
        self.assertNotIn(self.student.full_name, html)
        html = self.client.get(path).get_data(as_text=True)
        target = f'/teacher/students/{self.student.id}?class_id={self.class_.id}'
        self.assertIn(f'href="{target}"', html)
        detail = self.client.get(target).get_data(as_text=True)
        self.assertIn(f'href="{path}"', detail)
        self.assertEqual(self.client.get(f'/teacher/students/class/{self.hidden_class.id}').status_code, 404)
        self.assertEqual(self.client.get(f'/teacher/students?class_id={self.class_.id}').status_code, 302)
        with patch.object(User, 'can_access', return_value=False):
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_score_names_link_to_learning_only_when_accessible(self):
        self.populate()
        score = Score.query.filter_by(class_id=self.class_.id, student_id=self.student.id).one()
        score.score_type = 'continuous'
        score.semester = 'semester_1'
        db.session.commit()
        target = f'/teacher/students/{self.student.id}?class_id={self.class_.id}'
        path = f'/teacher/scores/{self.class_.id}/detai?year={self.start.year}&semester=semester_1'
        html = self.client.get(path).get_data(as_text=True)
        self.assertEqual(html.count(f'href="{target}"'), 2)
        self.assertEqual(self.client.get(target).status_code, 200)
        with patch.object(User, 'can_access', autospec=True, side_effect=lambda user, key: key != 'students'):
            self.assertNotIn(f'href="{target}"', self.client.get(path).get_data(as_text=True))
        self.enrollment.is_active = False
        db.session.commit()
        self.assertNotIn(f'href="{target}"', self.client.get(path).get_data(as_text=True))

    def test_modules_are_checked_server_side(self):
        self.populate()
        with patch.object(User, 'can_access', autospec=True, side_effect=lambda user, key: key == 'students'):
            html = self.client.get(f'/teacher/students/{self.student.id}').get_data(as_text=True)
            self.assertNotIn('0.0/10.0', html)
            self.assertNotIn('Work Synthetic class', html)
            self.assertNotIn('Allowed exam', html)
        with patch.object(User, 'can_access', return_value=False):
            self.assertEqual(self.client.get('/teacher/students').status_code, 403)
            self.assertEqual(self.client.get(f'/teacher/students/{self.student.id}').status_code, 403)

    def test_inactive_deleted_withdrawn_students_are_not_accessible(self):
        for attr in ('is_deleted', 'is_active', 'enrollment'):
            if attr == 'enrollment':
                self.enrollment.is_active = False
            else:
                setattr(self.student, attr, attr == 'is_deleted')
            db.session.commit()
            self.assertEqual(self.client.get(f'/teacher/students/{self.student.id}').status_code, 404)
            self.student.is_deleted = False
            self.student.is_active = True
            self.enrollment.is_active = True
        self.class_.is_active = False
        db.session.commit()
        self.assertEqual(self.client.get(f'/teacher/students/{self.student.id}').status_code, 404)

    def test_view_context_contains_only_safe_projection(self):
        self.populate()
        with patch('blueprints.teacher_students.render_template', return_value='OK') as render:
            response = self.client.get(f'/teacher/students/{self.student.id}')
        self.assertEqual(response.status_code, 200)
        context = render.call_args.kwargs
        self.assertEqual(set(context['student']), {'id', 'name', 'grade'})
        self.assertEqual(set(context['memberships'][0]._mapping),
                         {'id', 'full_name', 'current_grade', 'class_id', 'class_name'})

    def test_attendance_detail_only_lists_unexcused_before_limit(self):
        from models import Attendance
        path = f'/teacher/students/{self.student.id}'
        self.assertIn('Không có buổi vắng không phép.', self.client.get(path).get_data(as_text=True))
        absence = AttendanceWarningTests.session(self, 0, 'absent')
        for index in range(52):
            AttendanceWarningTests.session(self, 1, ('present', 'excused', 'late')[index % 3])
        with patch('blueprints.teacher_students.render_template', return_value='OK') as render:
            self.assertEqual(self.client.get(path).status_code, 200)
        attendance = render.call_args.kwargs['attendance']
        self.assertEqual(len(attendance), 1)
        self.assertEqual(attendance[0].status, 'absent')
        self.assertEqual(attendance[0].date, absence.date)
        html = self.client.get(path).get_data(as_text=True)
        self.assertIn('Vắng không phép', html)
        self.assertNotIn('Chỉ hiển thị dữ liệu học tập của lớp bạn đang phụ trách.', html)
        self.assertNotIn('Các đề bạn tạo và đã giao cho học sinh.', html)
        Attendance.query.filter_by(schedule_id=absence.id).one().status = 'present'
        db.session.commit()
        self.assertIn('Không có buổi vắng không phép.', self.client.get(path).get_data(as_text=True))

    def test_exam_scope_and_pending_not_presented_as_zero(self):
        self.populate()
        other_user = User(username='other', role='teacher', password_hash='test')
        db.session.add(other_user)
        db.session.flush()
        db.session.add(Exam(title='PRIVATE_OTHER_EXAM', created_by=other_user.id,
                            class_ids=str(self.class_.id), is_shared_with_teachers=True))
        db.session.add(Exam(title='PRIVATE_OTHER_TARGET', created_by=self.teacher.user_id,
                            class_ids=str(self.hidden_class.id)))
        db.session.add(ExamAttempt(exam=self.exam, user_id=self.teacher.user_id,
                                  student_id=self.student.id, status='submitted',
                                  result_json=json.dumps({'pending_essay_count': 1})))
        db.session.commit()
        html = self.client.get(f'/teacher/students/{self.student.id}').get_data(as_text=True)
        self.assertIn('Chờ chấm', html)
        self.assertNotIn('PRIVATE_OTHER_EXAM', html)
        self.assertNotIn('PRIVATE_OTHER_TARGET', html)

    def test_parent_and_wrong_active_role_cannot_access(self):
        parent = User(username='parent', role='parent', password_hash='test')
        db.session.add(parent)
        db.session.commit()
        self.login(parent)
        self.assertEqual(self.client.get('/teacher/students').status_code, 403)
        self.login(self.teacher.user)
        with self.client.session_transaction() as session:
            session['active_role'] = 'admin'
        g.pop('_login_user', None)
        self.assertEqual(self.client.get('/teacher/students').status_code, 403)


if __name__ == '__main__':
    unittest.main()
