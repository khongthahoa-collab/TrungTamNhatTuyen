"""
Single source of truth for the per-account feature permission system.

Every admin/teacher sidebar/nav item maps to a "module key". A User's
`permissions` column (see models.User) is either None (full access, implies
'write' everywhere) or a JSON dict of module_key -> 'read'/'write'/'deny'.
A GET request only needs 'read'; a mutating request (POST/PUT/PATCH/DELETE)
needs 'write'. CORE_MODULES are always accessible. MASTER_ONLY_MODULES are
hard-denied to any non-master account regardless of their permission dict.
"""

CORE_MODULES = {'dashboard', 'notifications'}

# Modules only the admin-master account may access at all (view or edit) —
# regardless of what a delegated admin's permission matrix says.
MASTER_ONLY_MODULES = {'teachers', 'salary'}

# (key, label, bootstrap-icon) — order matches the admin sidebar
ADMIN_MODULES = [
    ('students', 'Học sinh', 'bi-people'),
    ('classes', 'Lớp học', 'bi-journal-bookmark'),
    ('academic', 'Năm học', 'bi-calendar3'),
    ('rewards', 'Khen thưởng', 'bi-trophy'),
    ('attendance', 'Điểm danh', 'bi-person-check'),
    ('tuition', 'Học phí', 'bi-cash-stack'),
    ('expenses', 'Chi phí', 'bi-receipt'),
    ('salary', 'Lương', 'bi-cash-coin'),
    ('teachers', 'Giáo viên', 'bi-person-badge'),
    ('rooms', 'Phòng học', 'bi-door-open'),
    ('documents', 'Tài liệu', 'bi-folder2'),
    ('exams', 'Đề thi online', 'bi-pc-display'),
    ('reports', 'Báo cáo', 'bi-bar-chart-line'),
    ('schools', 'Trường học', 'bi-building'),
    ('courses', 'Môn học', 'bi-book'),
    ('users', 'Tài khoản', 'bi-person-gear'),
    ('inquiries', 'Liên hệ', 'bi-envelope'),
    ('settings', 'Cài đặt', 'bi-gear'),
]

# Modules a delegated admin's read/write/deny matrix can actually control —
# excludes MASTER_ONLY_MODULES, which are hard-gated to the master account.
ADMIN_PERMISSION_MODULES = [m for m in ADMIN_MODULES if m[0] not in MASTER_ONLY_MODULES]

# Admin sidebar layout: 'reports' and dashboard render as standalone links;
# everything else is grouped into collapsible sections. (group_key, label,
# icon, [module keys in ADMIN_MODULES]) — every ADMIN_MODULES key except
# 'reports' must appear in exactly one group.
ADMIN_SIDEBAR_GROUPS = [
    ('academic', 'Học vụ', 'bi-mortarboard-fill',
        ['students', 'classes', 'academic', 'attendance', 'rewards']),
    ('staff', 'Nhân sự & Cơ sở', 'bi-building',
        ['teachers', 'rooms', 'schools', 'courses']),
    ('finance', 'Tài chính', 'bi-cash-stack',
        ['tuition', 'expenses', 'salary']),
    ('content', 'Học liệu & Thi cử', 'bi-journal-text',
        ['documents', 'exams']),
    ('system', 'Hệ thống', 'bi-gear-fill',
        ['users', 'inquiries', 'settings']),
]

# (key, label, bootstrap-icon) — order matches the teacher bottom nav
TEACHER_MODULES = [
    ('schedule', 'Lịch dạy', 'bi-calendar3'),
    ('attendance', 'Điểm danh', 'bi-person-check'),
    ('scores', 'Điểm số', 'bi-pencil-square'),
    ('exams', 'Đề thi online', 'bi-pc-display'),
    ('documents_teacher', 'Tài liệu lớp', 'bi-folder2'),
]

# endpoint function name (without the 'admin.' prefix) -> module key
ADMIN_ENDPOINT_MODULES = {
    # students.py
    'students': 'students', 'students_bulk_delete': 'students', 'export_students': 'students',
    'import_students': 'students', 'student_add': 'students', 'student_detail': 'students',
    'student_reset_parent_password': 'students', 'student_create_parent_account': 'students',
    'student_edit': 'students',
    'student_enroll': 'students', 'student_unenroll': 'students',
    'student_photo_upload': 'students', 'student_photo_delete': 'students',

    # classes.py (schedule sub-actions belong to the class detail page)
    'classes': 'classes', 'class_add': 'classes', 'class_detail': 'classes', 'class_edit': 'classes',
    'class_reschedule': 'classes', 'class_delete_weekly_slot': 'classes', 'class_add_students': 'classes',
    'add_schedule': 'classes', 'cancel_schedule': 'classes', 'delete_schedule': 'classes',

    # academic.py
    'academic_years': 'academic', 'academic_year_add': 'academic',
    'academic_year_activate': 'academic', 'semester_add': 'academic', 'semester_delete': 'academic',
    'academic_sync_grades': 'academic',

    # rewards.py
    'rewards': 'rewards', 'reward_confirm': 'rewards', 'reward_cancel': 'rewards', 'reward_add': 'rewards',

    # attendance.py
    'attendance_list': 'attendance', 'attendance_session': 'attendance', 'save_attendance': 'attendance',

    # leave_requests.py
    'manage_leave_requests': 'attendance', 'leave_request_student_search': 'attendance',
    'leave_request_edit': 'attendance',

    # finance.py — split across 4 modules
    'tuition': 'tuition', 'tuition_class_detail': 'tuition', 'tuition_add': 'tuition',
    'tuition_mark_paid': 'tuition', 'tuition_remind_zalo': 'tuition',
    'monthly_fees': 'tuition', 'monthly_fee_update': 'tuition', 'monthly_fee_generate': 'tuition',
    'tuition_adjust_amount': 'tuition', 'tuition_void': 'tuition', 'tuition_unvoid': 'tuition',
    'tuition_reverse_payment': 'tuition',
    'expenses': 'expenses', 'expense_add': 'expenses', 'expense_delete': 'expenses',
    'salary': 'salary', 'salary_calculate': 'salary', 'salary_detail': 'salary',
    'salary_start': 'salary', 'salary_print': 'salary',

    # teachers.py — master-only (see MASTER_ONLY_MODULES)
    'teachers': 'teachers', 'teacher_add': 'teachers',
    'teacher_detail': 'teachers', 'teacher_delete': 'teachers',
    'teacher_reset_password': 'teachers', 'teacher_promote': 'teachers',
    'teacher_promote_academic_manager': 'teachers',

    # rooms.py
    'rooms': 'rooms', 'room_add': 'rooms', 'room_edit': 'rooms',
    'room_delete': 'rooms', 'rooms_available': 'rooms',

    # documents.py
    'documents': 'documents', 'document_upload': 'documents',
    'document_delete': 'documents', 'document_download': 'documents',

    # exams.py — shared with teacher role via require_admin_or_teacher
    'exams_list': 'exams', 'exam_folder_create': 'exams', 'exam_folder_edit': 'exams',
    'exam_folder_delete': 'exams', 'exam_duplicate': 'exams', 'exams_results': 'exams',
    'exams_new': 'exams', 'exams_edit': 'exams', 'exams_confirm': 'exams', 'exams_delete': 'exams',
    'exams_preview': 'exams', 'exams_export': 'exams',

    # reports.py
    'reports': 'reports',

    # schools.py
    'schools': 'schools', 'school_add': 'schools', 'school_edit': 'schools', 'school_delete': 'schools',

    # settings.py — split across 4 modules
    'settings': 'settings', 'settings_save': 'settings',
    'inquiries': 'inquiries', 'inquiry_delete': 'inquiries',
    'users': 'users', 'user_add': 'users', 'user_edit': 'users', 'user_delete': 'users',
    'user_reset_password': 'users', 'user_toggle_active': 'users', 'user_group_update': 'users',
    'admin_permission': 'users', 'permission_group_add': 'users', 'permission_group_rename': 'users',
    'permission_group_delete': 'users', 'permission_group_update': 'users',
    'courses': 'courses', 'course_add': 'courses', 'course_edit': 'courses',
}

# endpoint function name (without the 'teacher.' prefix) -> module key
TEACHER_ENDPOINT_MODULES = {
    'schedule': 'schedule', 'checkin': 'schedule',
    'available_rooms': 'schedule', 'create_intensive': 'schedule',
    'attendance_list': 'attendance', 'attendance_session': 'attendance', 'save_attendance': 'attendance',
    'scores': 'scores', 'scores_list': 'scores',
    'documents': 'documents_teacher', 'delete_document': 'documents_teacher',
    # teacher's own exam screens (blueprints/teacher_exams.py) — separate routes from admin's,
    # gated by the same 'exams' module key as the admin side
    'exams_list': 'exams', 'exam_duplicate': 'exams', 'exams_results': 'exams',
    'exams_new': 'exams', 'exams_edit': 'exams', 'exams_confirm': 'exams',
    'exams_delete': 'exams', 'exams_preview': 'exams', 'exams_export': 'exams',
}
