from extensions import db
from flask_login import UserMixin
from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash


# ============================================================
# Constants & Enums - Standard English naming
# ============================================================

class UserRole:
    """Role types for system users"""
    ADMIN = 'admin'
    TEACHER = 'teacher'
    PARENT = 'parent'


class StudentLevel:
    """Education level classification"""
    PRIMARY = 'primary'           # Tiểu học
    SECONDARY = 'secondary'       # THCS
    HIGH_SCHOOL = 'high_school'   # THPT
    
    LABELS = {
        'primary': 'Tiểu học',
        'secondary': 'THCS',
        'high_school': 'THPT'
    }


class ScheduleType:
    """Class schedule type"""
    REGULAR = 'regular'           # Lịch thường
    INTENSIVE = 'intensive'       # Lịch tăng cường
    
    LABELS = {
        'regular': 'Lịch thường',
        'intensive': 'Lịch tăng cường'
    }


class AttendanceStatus:
    """Student attendance status"""
    PRESENT = 'present'           # Có mặt
    ABSENT = 'absent'             # Vắng
    LATE = 'late'                 # Trễ
    EXCUSED = 'excused'           # Vắng có phép
    
    LABELS = {
        'present': 'Có mặt',
        'absent': 'Vắng',
        'late': 'Trễ',
        'excused': 'Vắng có phép'
    }


class ScoreSource:
    """Where the score comes from"""
    SCHOOL = 'school'             # Thi trường (external)
    CENTER = 'center'             # Kiểm tra TT (internal)
    
    LABELS = {
        'school': 'Thi trường',
        'center': 'Kiểm tra TT'
    }


class ScoreType:
    """Type of assessment score"""
    CONTINUOUS = 'continuous'     # Thường xuyên (TX)
    QUIZ_15 = 'quiz_15'          # 15 phút
    ORAL = 'oral'                # Miệng
    MIDTERM = 'midterm'          # Giữa kỳ (GK)
    FINAL = 'final'              # Cuối kỳ (CK)
    
    LABELS = {
        'continuous': 'Thường xuyên',
        'quiz_15': '15 phút',
        'oral': 'Miệng',
        'midterm': 'Giữa kỳ',
        'final': 'Cuối kỳ'
    }


class SemesterType:
    """Academic semester or term"""
    SUMMER = 'summer'             # Hè
    SEMESTER_1 = 'semester_1'     # Học kỳ 1
    SEMESTER_2 = 'semester_2'     # Học kỳ 2
    
    LABELS = {
        'summer': 'Học kỳ Hè',
        'semester_1': 'Học kỳ 1',
        'semester_2': 'Học kỳ 2'
    }


class TuitionMethod:
    """Payment method for tuition"""
    CASH = 'cash'                # Tiền mặt
    TRANSFER = 'transfer'        # Chuyển khoản
    
    LABELS = {
        'cash': 'Tiền mặt',
        'transfer': 'Chuyển khoản'
    }


class ExpenseCategory:
    """Categories for center expenses"""
    SALARY = 'salary'            # Lương giáo viên
    RENT = 'rent'                # Thuê mặt bằng
    UTILITIES = 'utilities'      # Điện nước
    INTERNET = 'internet'        # Internet
    REWARD = 'reward'            # Thưởng học sinh
    OFFICE_SUPPLIES = 'office_supplies'  # Văn phòng phẩm
    GIFT = 'gift'                # Quà tặng
    MARKETING = 'marketing'      # Marketing
    OTHER = 'other'              # Khác
    
    LABELS = {
        'salary': 'Lương giáo viên',
        'rent': 'Thuê mặt bằng',
        'utilities': 'Điện nước',
        'internet': 'Internet',
        'reward': 'Thưởng học sinh',
        'office_supplies': 'Văn phòng phẩm',
        'gift': 'Quà tặng',
        'marketing': 'Marketing',
        'other': 'Chi phí khác',
    }


# ============================================================
# Association Tables (Many-to-Many relationships)
# ============================================================

teacher_courses = db.Table(
    'teacher_courses',
    db.Column('teacher_id', db.Integer, db.ForeignKey('teachers.id'), primary_key=True),
    db.Column('course_id', db.Integer, db.ForeignKey('courses.id'), primary_key=True)
)

teacher_classes = db.Table(
    'teacher_classes',
    db.Column('teacher_id', db.Integer, db.ForeignKey('teachers.id'), primary_key=True),
    db.Column('class_id', db.Integer, db.ForeignKey('classes.id'), primary_key=True)
)


# ============================================================
# Database Models - Core entities
# ============================================================

class SystemConfig(db.Model):
    """System configuration settings"""
    __tablename__ = 'system_config'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)
    description = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get(key, default=None):
        """Get configuration value by key"""
        row = SystemConfig.query.filter_by(key=key).first()
        return row.value if row else default

    @staticmethod
    def set(key, value, description=None):
        """Set configuration value"""
        row = SystemConfig.query.filter_by(key=key).first()
        if row:
            row.value = value
        else:
            row = SystemConfig(key=key, value=value, description=description)
            db.session.add(row)
        db.session.commit()

    def __repr__(self):
        return f'<SystemConfig {self.key}={self.value}>'


class AcademicYear(db.Model):
    """Academic year entity (e.g., 2025-2026)"""
    __tablename__ = 'academic_years'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # One academic year can have multiple semesters
    semesters = db.relationship('Semester', backref='academic_year', lazy='dynamic',
                                cascade='all, delete-orphan', order_by='Semester.start_date')

    def __repr__(self):
        return f'<AcademicYear {self.name}>'


class Semester(db.Model):
    """Semester or term within an academic year"""
    __tablename__ = 'semesters'
    
    id = db.Column(db.Integer, primary_key=True)
    academic_year_id = db.Column(db.Integer, db.ForeignKey('academic_years.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    semester_type = db.Column(db.String(20), nullable=False)  # summer/semester_1/semester_2
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)

    @property
    def type_label(self):
        """Get human-readable semester type label"""
        return SemesterType.LABELS.get(self.semester_type, self.semester_type)

    def __repr__(self):
        return f'<Semester {self.name}>'


class User(UserMixin, db.Model):
    """System user (admin, teacher, or parent)"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    phone = db.Column(db.String(15), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=UserRole.PARENT)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    # Relationships
    teacher_profile = db.relationship('Teacher', backref='user', uselist=False)
    children = db.relationship('Student', backref='parent_user',
                               foreign_keys='Student.parent_user_id', lazy='dynamic')

    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify password against hash"""
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN

    @property
    def is_teacher(self):
        return self.role == UserRole.TEACHER

    @property
    def is_parent(self):
        return self.role == UserRole.PARENT

    @property
    def role_label(self):
        """Get human-readable role label"""
        return {
            UserRole.ADMIN: 'Quản trị viên',
            UserRole.TEACHER: 'Giáo viên',
            UserRole.PARENT: 'Phụ huynh'
        }.get(self.role, self.role)

    def __repr__(self):
        return f'<User {self.username}>'


class Teacher(db.Model):
    """Teacher profile extending User"""
    __tablename__ = 'teachers'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    is_staff = db.Column(db.Boolean, default=True)  # True = full-time staff receiving salary
    base_salary = db.Column(db.Float, default=0)
    note = db.Column(db.Text)

    # Relationships - Teacher can teach multiple courses and classes
    courses = db.relationship('Course', secondary=teacher_courses, backref='teachers',
                            lazy='dynamic')
    classes = db.relationship('Class', secondary=teacher_classes, backref='teachers',
                             lazy='dynamic')
    schedules = db.relationship('Schedule', backref='teacher', lazy='dynamic')
    salaries = db.relationship('Salary', backref='teacher', lazy='dynamic')

    @property
    def full_name(self):
        return self.user.full_name if self.user else ''

    @property
    def phone(self):
        return self.user.phone if self.user else ''

    @property
    def specialties(self):
        """Get list of courses this teacher teaches"""
        return [c.name for c in self.courses.all()]

    def __repr__(self):
        return f'<Teacher {self.full_name}>'


class Course(db.Model):
    """Course offering (e.g., Math for secondary)"""
    __tablename__ = 'courses'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    level = db.Column(db.String(20))  # primary/secondary/high_school/all
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    classes = db.relationship('Class', backref='course', lazy='dynamic')

    @property
    def level_label(self):
        """Get human-readable level label"""
        return StudentLevel.LABELS.get(self.level, 'All levels')

    def __repr__(self):
        return f'<Course {self.name}>'


class Room(db.Model):
    """Classroom/room entity (supports multi-branch)"""
    __tablename__ = 'rooms'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    branch = db.Column(db.String(200))       # chi nhánh / địa chỉ
    floor = db.Column(db.String(20))          # tầng
    room_number = db.Column(db.String(20))    # số phòng
    capacity = db.Column(db.Integer, default=20)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def display_name(self):
        parts = []
        if self.room_number:
            parts.append(f'Phòng {self.room_number}')
        if self.floor:
            parts.append(f'Tầng {self.floor}')
        if self.branch:
            parts.append(self.branch)
        return ' – '.join(parts) if parts else self.name

    def __repr__(self):
        return f'<Room {self.name}>'


class Class(db.Model):
    """Class offering with schedule and students"""
    __tablename__ = 'classes'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    grade_level = db.Column(db.String(20))  # e.g., "Class 10", "Class 6A"
    max_students = db.Column(db.Integer, default=20)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True)
    description = db.Column(db.Text)
    primary_teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=True)
    assistant_teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    enrollments = db.relationship('Enrollment', backref='class_', lazy='dynamic',
                                  cascade='all, delete-orphan')
    schedules = db.relationship('Schedule', backref='class_', lazy='dynamic',
                                order_by='Schedule.date')
    documents = db.relationship('ClassDocument', backref='class_', lazy='dynamic',
                                cascade='all, delete-orphan')
    primary_teacher = db.relationship('Teacher', foreign_keys=[primary_teacher_id],
                                      backref='primary_classes')
    assistant_teacher = db.relationship('Teacher', foreign_keys=[assistant_teacher_id],
                                        backref='assistant_classes')

    @property
    def current_enrollment(self):
        """Count active enrollments"""
        return self.enrollments.filter_by(is_active=True).count()

    @property
    def active_students(self):
        """Get list of active students"""
        return [e.student for e in self.enrollments.filter_by(is_active=True).all()]

    def is_student_enrolled(self, student_id):
        """Check if student is enrolled"""
        return self.enrollments.filter_by(student_id=student_id, is_active=True).first() is not None

    def __repr__(self):
        return f'<Class {self.name}>'


class Enrollment(db.Model):
    """Student enrollment in a class"""
    __tablename__ = 'enrollments'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    enrolled_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    discount_pct = db.Column(db.Float, default=0)  # Discount percentage
    note = db.Column(db.String(255))

    __table_args__ = (db.UniqueConstraint('student_id', 'class_id', name='uq_enrollment'),)

    def __repr__(self):
        return f'<Enrollment student={self.student_id} class={self.class_id}>'


class Student(db.Model):
    """Student entity"""
    __tablename__ = 'students'
    
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    date_of_birth = db.Column(db.Date)
    gender = db.Column(db.String(10))  # male/female
    current_school = db.Column(db.String(100))  # Current school name
    current_grade = db.Column(db.String(20))    # e.g., "6A1", "10B"
    level = db.Column(db.String(20), nullable=False)  # primary/secondary/high_school
    parent_name = db.Column(db.String(100))
    parent_phone = db.Column(db.String(15))
    parent_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    note = db.Column(db.Text)
    photo_path = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    status = db.Column(db.String(20), default='active', server_default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    enrollments = db.relationship('Enrollment', backref='student', lazy='dynamic')
    attendances = db.relationship('Attendance', backref='student', lazy='dynamic')
    scores = db.relationship('Score', backref='student', lazy='dynamic')
    rewards = db.relationship('Reward', backref='student', lazy='dynamic')
    tuition_payments = db.relationship('TuitionPayment', backref='student', lazy='dynamic')

    @property
    def active_classes(self):
        """Get list of active classes"""
        return [e.class_ for e in self.enrollments.filter_by(is_active=True).all()]

    @property
    def level_label(self):
        """Get human-readable education level"""
        return StudentLevel.LABELS.get(self.level, self.level)

    def __repr__(self):
        return f'<Student {self.full_name}>'


class Schedule(db.Model):
    """Class schedule/session"""
    __tablename__ = 'schedules'
    
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=True)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    room = db.Column(db.String(50))
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=True)
    topic = db.Column(db.String(255))
    schedule_type = db.Column(db.String(20), default=ScheduleType.REGULAR)
    semester_id = db.Column(db.Integer, db.ForeignKey('semesters.id'), nullable=True)
    is_cancelled = db.Column(db.Boolean, default=False)
    cancel_reason = db.Column(db.String(255))
    teacher_checked_in = db.Column(db.Boolean, default=False)
    teacher_check_in_time = db.Column(db.DateTime)  # When teacher checked in
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    attendances = db.relationship('Attendance', backref='schedule', lazy='dynamic',
                                  cascade='all, delete-orphan')
    semester = db.relationship('Semester', backref='schedules')
    room_obj = db.relationship('Room', foreign_keys=[room_id], backref='schedules')

    @property
    def is_today(self):
        """Check if schedule is for today"""
        return self.date == date.today()

    @property
    def attendance_taken(self):
        """Check if attendance has been recorded"""
        return self.attendances.count() > 0

    @property
    def type_label(self):
        """Get human-readable schedule type"""
        return ScheduleType.LABELS.get(self.schedule_type, self.schedule_type)

    def __repr__(self):
        return f'<Schedule class={self.class_id} date={self.date}>'


class Attendance(db.Model):
    """Student attendance record"""
    __tablename__ = 'attendances'
    
    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey('schedules.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=AttendanceStatus.PRESENT)
    note = db.Column(db.String(255))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)
    recorded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    zalo_notified = db.Column(db.Boolean, default=False)  # Whether parent was notified via Zalo

    __table_args__ = (db.UniqueConstraint('schedule_id', 'student_id', name='uq_attendance'),)

    @property
    def status_label(self):
        """Get human-readable status"""
        return AttendanceStatus.LABELS.get(self.status, self.status)

    @property
    def status_badge_class(self):
        """Get Bootstrap badge class for status"""
        return {
            AttendanceStatus.PRESENT: 'success',
            AttendanceStatus.ABSENT: 'danger',
            AttendanceStatus.LATE: 'warning',
            AttendanceStatus.EXCUSED: 'secondary',
        }.get(self.status, 'secondary')

    def __repr__(self):
        return f'<Attendance student={self.student_id} status={self.status}>'


class Score(db.Model):
    """Student score/grade"""
    __tablename__ = 'scores'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    score_source = db.Column(db.String(20), nullable=False, default=ScoreSource.CENTER)  # center/school
    score_type = db.Column(db.String(20), nullable=False)  # continuous/quiz_15/oral/midterm/final
    score_value = db.Column(db.Float, nullable=False)
    max_score = db.Column(db.Float, default=10.0)
    exam_date = db.Column(db.Date)
    school_name = db.Column(db.String(100))  # For external/school scores
    note = db.Column(db.String(255))
    entered_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    reward_suggested = db.Column(db.Boolean, default=False)  # Manual reward suggestion flag
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    class_ = db.relationship('Class', foreign_keys=[class_id])
    rewards = db.relationship('Reward', backref='score', foreign_keys='Reward.score_id', lazy='dynamic')

    @property
    def score_type_label(self):
        """Get human-readable score type"""
        return ScoreType.LABELS.get(self.score_type, self.score_type)

    @property
    def score_source_label(self):
        """Get human-readable score source"""
        return ScoreSource.LABELS.get(self.score_source, self.score_source)

    def __repr__(self):
        return f'<Score student={self.student_id} value={self.score_value}>'


class Reward(db.Model):
    """Student reward or incentive"""
    __tablename__ = 'rewards'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Float, default=0)  # Cash amount in VND
    reward_type = db.Column(db.String(20), default='cash')  # cash/gift
    reward_date = db.Column(db.Date, default=date.today)
    note = db.Column(db.Text)
    is_suggested = db.Column(db.Boolean, default=False)  # Auto-suggested based on score
    is_confirmed = db.Column(db.Boolean, default=False)  # Confirmed by admin
    score_id = db.Column(db.Integer, db.ForeignKey('scores.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    confirmed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    confirmed_at = db.Column(db.DateTime)

    def __repr__(self):
        return f'<Reward student={self.student_id} amount={self.amount}>'


class TuitionPayment(db.Model):
    """Student tuition payment record"""
    __tablename__ = 'tuition_payments'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    paid_at = db.Column(db.DateTime)
    method = db.Column(db.String(20), default=TuitionMethod.CASH)  # cash/transfer
    received_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    note = db.Column(db.String(255))
    is_paid = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    class_ = db.relationship('Class', foreign_keys=[class_id])

    @property
    def method_label(self):
        """Get human-readable payment method"""
        return TuitionMethod.LABELS.get(self.method, self.method)

    def __repr__(self):
        return f'<TuitionPayment student={self.student_id} month_year={self.month}/{self.year}>'


class Salary(db.Model):
    """Teacher monthly salary record"""
    __tablename__ = 'salaries'
    
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    base_amount = db.Column(db.Float, default=0)  # Base salary
    bonus = db.Column(db.Float, default=0)        # Bonuses
    deduction = db.Column(db.Float, default=0)    # Deductions
    total = db.Column(db.Float, default=0)        # Final amount
    sessions_scheduled = db.Column(db.Integer, default=0)  # Total scheduled sessions
    sessions_checked_in = db.Column(db.Integer, default=0)  # Sessions teacher checked in
    is_finalized = db.Column(db.Boolean, default=False)  # Salary locked/finalized
    paid_at = db.Column(db.DateTime)
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('teacher_id', 'month', 'year', name='uq_salary'),)

    def __repr__(self):
        return f'<Salary teacher={self.teacher_id} month_year={self.month}/{self.year}>'


class Expense(db.Model):
    """Center operating expense"""
    __tablename__ = 'expenses'
    
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)  # salary/rent/utilities/etc
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(255))
    expense_date = db.Column(db.Date, nullable=False, default=date.today)
    fiscal_year = db.Column(db.Integer)  # For financial reporting
    is_tax_deductible = db.Column(db.Boolean, default=False)
    receipt_no = db.Column(db.String(50))  # Receipt number for tracking
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def category_label(self):
        """Get human-readable category"""
        return ExpenseCategory.LABELS.get(self.category, self.category)

    def __repr__(self):
        return f'<Expense category={self.category} amount={self.amount}>'


class ZaloLog(db.Model):
    """Log of Zalo messages sent to parents"""
    __tablename__ = 'zalo_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    recipient_phone = db.Column(db.String(15))
    recipient_name = db.Column(db.String(100))
    message_type = db.Column(db.String(50))
    content_summary = db.Column(db.Text)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pending')  # success/failed/pending/mock
    error_msg = db.Column(db.Text)

    def __repr__(self):
        return f'<ZaloLog message_type={self.message_type} status={self.status}>'


class ClassDocument(db.Model):
    """Document uploaded for a class"""
    __tablename__ = 'class_documents'
    
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(500))
    original_filename = db.Column(db.String(255))
    stored_filename = db.Column(db.String(255))
    file_size = db.Column(db.Integer)  # Size in bytes
    file_type = db.Column(db.String(20))  # Extension: pdf, docx, etc
    is_active = db.Column(db.Boolean, default=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    uploader = db.relationship('User', foreign_keys=[uploaded_by])

    @property
    def file_size_formatted(self):
        """Format file size for display"""
        if not self.file_size:
            return 'N/A'
        if self.file_size < 1024:
            return f'{self.file_size} B'
        elif self.file_size < 1024 * 1024:
            return f'{self.file_size / 1024:.1f} KB'
        return f'{self.file_size / (1024 * 1024):.1f} MB'

    @property
    def file_icon(self):
        """Get Bootstrap icon class for file type"""
        icons = {
            'pdf': 'bi-file-earmark-pdf text-danger',
            'doc': 'bi-file-earmark-word text-primary',
            'docx': 'bi-file-earmark-word text-primary',
            'ppt': 'bi-file-earmark-ppt text-warning',
            'pptx': 'bi-file-earmark-ppt text-warning',
            'xls': 'bi-file-earmark-excel text-success',
            'xlsx': 'bi-file-earmark-excel text-success',
            'jpg': 'bi-file-earmark-image text-info',
            'jpeg': 'bi-file-earmark-image text-info',
            'png': 'bi-file-earmark-image text-info',
            'zip': 'bi-file-earmark-zip text-secondary',
            'rar': 'bi-file-earmark-zip text-secondary',
            'mp4': 'bi-file-earmark-play text-danger',
        }
        return icons.get(self.file_type, 'bi-file-earmark')

    def __repr__(self):
        return f'<ClassDocument title={self.title}>'


class Notification(db.Model):
    """In-app notification for users (admin, teacher, parent)"""
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text)
    notif_type = db.Column(db.String(50), default='info')  # info/warning/success/danger
    link = db.Column(db.String(255))           # optional URL to navigate to
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id], backref='notifications')

    def __repr__(self):
        return f'<Notification user={self.user_id} title={self.title}>'


class ContactInquiry(db.Model):
    """Public contact/enrollment request from prospective parents"""
    __tablename__ = 'contact_inquiries'

    id           = db.Column(db.Integer, primary_key=True)
    student_name = db.Column(db.String(100), nullable=False)
    grade        = db.Column(db.String(50))    # e.g. "Lớp 6A"
    subject      = db.Column(db.String(100))   # môn học muốn học
    school       = db.Column(db.String(150))   # trường của học sinh
    parent_phone = db.Column(db.String(20), nullable=False)
    note         = db.Column(db.Text)
    confirm_tuition = db.Column(db.Boolean, default=False)  # Parent wants tuition confirmed before starting
    is_read      = db.Column(db.Boolean, default=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<ContactInquiry student={self.student_name}>'
