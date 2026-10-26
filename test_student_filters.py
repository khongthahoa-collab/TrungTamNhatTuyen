"""Student teacher filters must preserve unique pagination and PostgreSQL ordering."""
from datetime import date, time
import unittest
from unittest.mock import patch

from sqlalchemy import event
from sqlalchemy.dialects.postgresql import psycopg

from app import create_app
from config import Config, config
from extensions import db
from models import Class, Course, Enrollment, Schedule, Student, Teacher, User


class StudentFilterConfig(Config):
    TESTING = True
    SECRET_KEY = 'student-filter-test'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


class StudentFilterTests(unittest.TestCase):
    def test_teacher_filter_with_grade_order_and_unique_pagination(self):
        config['student_filter_test'] = StudentFilterConfig
        app = create_app('student_filter_test')
        try:
            with app.app_context():
                db.create_all()
                admin = User(username='admin', role='admin', is_master=True, password_hash='test')
                user = User(username='teacher', role='teacher', password_hash='test')
                course = Course(name='Course')
                db.session.add_all([admin, user, course])
                db.session.flush()
                teacher = Teacher(user_id=user.id)
                db.session.add(teacher)
                db.session.flush()
                classes = [Class(name=f'Class {i}', course_id=course.id) for i in range(3)]
                db.session.add_all(classes)
                db.session.flush()
                for class_ in classes[:2]:
                    for day in (1, 2):
                        db.session.add(Schedule(
                            class_id=class_.id, teacher_id=teacher.id,
                            date=date(2026, 10, day), start_time=time(8), end_time=time(9),
                        ))
                students = [
                    Student(full_name=f'Student {i:02}', current_grade=grade, level='high_school')
                    for i, grade in enumerate(['Lớp 10'] * 11 + ['Lớp 2', 'Lớp 10', 'Lớp 10'])
                ]
                db.session.add_all(students)
                db.session.flush()
                for student in students[:12]:
                    for class_ in classes[:2]:
                        db.session.add(Enrollment(student_id=student.id, class_id=class_.id))
                db.session.add_all([
                    Enrollment(student_id=students[12].id, class_id=classes[0].id, is_active=False),
                    Enrollment(student_id=students[13].id, class_id=classes[2].id),
                ])
                db.session.commit()
                client = app.test_client()
                with client.session_transaction() as session:
                    session['_user_id'] = str(admin.id)
                    session['_fresh'] = True
                statements = []

                def record(state):
                    if state.is_select:
                        sql = str(state.statement.compile(dialect=psycopg.dialect()))
                        if 'ORDER BY CASE' in sql:
                            statements.append(sql)

                event.listen(db.session(), 'do_orm_execute', record)
                try:
                    with patch('blueprints.admin.students.render_template', return_value='ok') as render:
                        url = f'/admin/students?teacher_id={teacher.id}&grade=Lớp+10&per_page=10'
                        self.assertEqual(client.get(url).status_code, 200)
                        context = render.call_args.kwargs
                        self.assertEqual(context['pagination'].total, 11)
                        self.assertEqual([s.id for s in context['students']], [s.id for s in students[:10]])
                        self.assertEqual(client.get(url + '&page=2').status_code, 200)
                        self.assertEqual([s.id for s in render.call_args.kwargs['students']], [students[10].id])
                        self.assertEqual(client.get(
                            f'/admin/students?teacher_id={teacher.id}&per_page=all',
                        ).status_code, 200)
                        context = render.call_args.kwargs
                        self.assertEqual(context['pagination'].total, 12)
                        self.assertEqual(context['students'][0].id, students[11].id)
                    self.assertTrue(statements)
                    for sql in statements:
                        self.assertNotIn('SELECT DISTINCT students.', sql)
                finally:
                    event.remove(db.session(), 'do_orm_execute', record)
                    db.session.remove()
                    db.drop_all()
                    db.engine.dispose()
        finally:
            config.pop('student_filter_test', None)
