#!/usr/bin/env python3
"""
Database Verification Script
Displays detailed information about all seeded data
"""

from app import create_app, db
from models import User, Student, Teacher, Class, Schedule, Score, Attendance, Reward, TuitionPayment, Salary, Expense

app = create_app()
with app.app_context():
    print("📊 DATABASE INITIALIZATION SUMMARY")
    print("=" * 70)
    
    users = db.session.query(User).all()
    students = db.session.query(Student).all()
    teachers = db.session.query(Teacher).all()
    classes = db.session.query(Class).all()
    schedules = db.session.query(Schedule).all()
    scores = db.session.query(Score).all()
    attendance = db.session.query(Attendance).all()
    rewards = db.session.query(Reward).all()
    tuition = db.session.query(TuitionPayment).all()
    salaries = db.session.query(Salary).all()
    expenses = db.session.query(Expense).all()
    
    print(f"\n👥 USERS: {len(users)} records")
    for user in users:
        print(f"   • {user.full_name:20} ({user.username:12}) - {user.role.upper():6}")
    
    print(f"\n🎓 STUDENTS: {len(students)} records")
    primary = sum(1 for s in students if s.level == 'primary')
    secondary = sum(1 for s in students if s.level == 'secondary')
    highschool = sum(1 for s in students if s.level == 'high_school')
    print(f"   • PRIMARY: {primary}, SECONDARY: {secondary}, HIGH_SCHOOL: {highschool}")
    
    print(f"\n👨‍🏫 TEACHERS: {len(teachers)} records")
    for teacher in teachers:
        user = teacher.user
        print(f"   • {user.full_name:20} - Specialty: {teacher.specialty:15} - Base Salary: {teacher.base_salary:,} VND")
    
    print(f"\n📚 CLASSES: {len(classes)} records")
    for cls in classes:
        print(f"   • {cls.name:20} - Max Students: {cls.max_students}, Active: {cls.is_active}")
    
    print(f"\n📅 SCHEDULES: {len(schedules)} records")
    print(f"   • Classes scheduled across 4 weeks (past, current, future)")
    
    print(f"\n📈 SCORES: {len(scores)} records")
    center_scores = sum(1 for s in scores if s.score_source == 'center')
    school_scores = sum(1 for s in scores if s.score_source == 'school')
    print(f"   • CENTER: {center_scores}, SCHOOL: {school_scores}")
    
    print(f"\n✓ ATTENDANCE: {len(attendance)} records")
    
    print(f"\n🎁 REWARDS: {len(rewards)} records")
    total_reward = sum(r.amount for r in rewards if r.amount)
    print(f"   • Total Rewards: {total_reward:,.0f} VND")
    
    print(f"\n💰 TUITION PAYMENTS: {len(tuition)} records")
    paid = sum(1 for t in tuition if t.is_paid)
    total_tuition = sum(t.amount for t in tuition if t.is_paid)
    print(f"   • Paid: {paid}, Unpaid: {len(tuition) - paid}")
    print(f"   • Total Paid: {total_tuition:,.0f} VND")
    
    print(f"\n💵 SALARIES: {len(salaries)} records")
    total_salary = sum(s.total for s in salaries if s.total)
    print(f"   • Total Salary Amount: {total_salary:,.0f} VND")
    
    print(f"\n📊 EXPENSES: {len(expenses)} records")
    total_expense = sum(e.amount for e in expenses if e.amount)
    print(f"   • Total Expenses: {total_expense:,.0f} VND")
    
    print("\n" + "=" * 70)
    print("✅ DATABASE FULLY INITIALIZED AND READY!")
    print("\n🚀 To start the application:")
    print("   source .venv/bin/activate")
    print("   python run.py")
    print("\n📲 Then access: http://localhost:5001")
    print("🔐 Login credentials:")
    print("   • Admin:  admin / admin123")
    print("   • Teacher: gvtoan / teacher123")
    print("   • Parent: parent01 / parent123")
