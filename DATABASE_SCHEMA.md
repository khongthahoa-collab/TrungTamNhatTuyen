# Nhat Tuyen Tutoring Center - Database Schema Documentation

## System Overview

**Nhat Tuyen** là hệ thống quản lý trung tâm dạy thêm toàn diện với các module:
- 👤 **User Management**: Admin, Teachers, Parents
- 🎓 **Academic**: Courses, Classes, Students, Grades
- 📅 **Scheduling**: Class schedules, Attendance
- 📊 **Assessment**: Scores, Rewards
- 💰 **Finance**: Tuition, Salaries, Expenses
- 📄 **Documents**: Class materials
- 💬 **Communication**: Zalo notifications

## Database Architecture

### ERD (Entity Relationship Diagram)

```mermaid
erDiagram
    USER ||--o{ TEACHER : "has"
    USER ||--o{ STUDENT : "parent_of"
    TEACHER ||--o{ SCHEDULE : "teaches"
    COURSE ||--o{ CLASS : "offers"
    CLASS ||--o{ SCHEDULE : "has"
    CLASS ||--o{ ENROLLMENT : "has"
    STUDENT ||--o{ ENROLLMENT : "enrolls_in"
    STUDENT ||--o{ ATTENDANCE : "has"
    SCHEDULE ||--o{ ATTENDANCE : "tracks"
    STUDENT ||--o{ SCORE : "receives"
    CLASS ||--o{ SCORE : "grades_in"
    SCORE ||--o{ REWARD : "triggers"
    STUDENT ||--o{ REWARD : "earns"
    STUDENT ||--o{ TUITION_PAYMENT : "pays"
    CLASS ||--o{ TUITION_PAYMENT : "charges"
    TEACHER ||--o{ SALARY : "receives"
    ACADEMIC_YEAR ||--o{ SEMESTER : "contains"
    SEMESTER ||--o{ SCHEDULE : "schedules_in"
    USER ||--o{ EXPENSE : "records"
    CLASS ||--o{ CLASS_DOCUMENT : "has"
    USER ||--o{ CLASS_DOCUMENT : "uploads"
    USER ||--o{ ZALO_LOG : "sends"

    USER {
        int id PK
        string full_name
        string username UK
        string phone UK
        string password_hash
        string role FK "admin|teacher|parent"
        boolean is_active
        datetime created_at
        datetime last_login
    }

    TEACHER {
        int id PK
        int user_id FK UK
        string specialty
        boolean is_staff
        float base_salary
        text note
    }

    STUDENT {
        int id PK
        string full_name
        date date_of_birth
        string gender "male|female"
        string current_school
        string current_grade
        string level FK "primary|secondary|high_school"
        string parent_name
        string parent_phone
        int parent_user_id FK
        text note
        boolean is_active
        datetime created_at
    }

    COURSE {
        int id PK
        string name
        string level "primary|secondary|high_school|all"
        text description
        boolean is_active
        datetime created_at
    }

    CLASS {
        int id PK
        string name
        int course_id FK
        string grade_level
        int max_students
        date start_date
        date end_date
        boolean is_active
        text description
        datetime created_at
    }

    ENROLLMENT {
        int id PK
        int student_id FK
        int class_id FK
        datetime enrolled_at
        boolean is_active
        float discount_pct
        string note
    }

    ACADEMIC_YEAR {
        int id PK
        string name "2025-2026"
        date start_date
        date end_date
        boolean is_active
        datetime created_at
    }

    SEMESTER {
        int id PK
        int academic_year_id FK
        string name
        string semester_type FK "summer|semester_1|semester_2"
        date start_date
        date end_date
    }

    SCHEDULE {
        int id PK
        int class_id FK
        int teacher_id FK
        date date
        time start_time
        time end_time
        string room
        string topic
        string schedule_type "regular|intensive"
        int semester_id FK
        boolean is_cancelled
        string cancel_reason
        boolean teacher_checked_in
        datetime teacher_check_in_time
        datetime created_at
    }

    ATTENDANCE {
        int id PK
        int schedule_id FK
        int student_id FK
        string status FK "present|absent|late|excused"
        string note
        datetime recorded_at
        int recorded_by FK
        boolean zalo_notified
    }

    SCORE {
        int id PK
        int student_id FK
        int class_id FK
        string score_source FK "center|school"
        string score_type FK "continuous|quiz_15|oral|midterm|final"
        float score_value
        float max_score
        date exam_date
        string school_name
        string note
        int entered_by FK
        boolean reward_suggested
        datetime created_at
    }

    REWARD {
        int id PK
        int student_id FK
        string reason
        float amount "VND"
        string reward_type "cash|gift"
        date reward_date
        text note
        boolean is_suggested
        boolean is_confirmed
        int score_id FK
        int created_by FK
        int confirmed_by FK
        datetime confirmed_at
    }

    TUITION_PAYMENT {
        int id PK
        int student_id FK
        int class_id FK
        float amount "VND"
        int month
        int year
        datetime paid_at
        string method "cash|transfer"
        int received_by FK
        string note
        boolean is_paid
        datetime created_at
    }

    SALARY {
        int id PK
        int teacher_id FK
        int month
        int year
        float base_amount
        float bonus
        float deduction
        float total
        int sessions_scheduled
        int sessions_checked_in
        boolean is_finalized
        datetime paid_at
        text note
        datetime created_at
    }

    EXPENSE {
        int id PK
        string category FK
        float amount "VND"
        string description
        date expense_date
        int fiscal_year
        boolean is_tax_deductible
        string receipt_no
        int created_by FK
        datetime created_at
    }

    CLASS_DOCUMENT {
        int id PK
        int class_id FK
        int uploaded_by FK
        string title
        string description
        string original_filename
        string stored_filename
        int file_size "bytes"
        string file_type
        boolean is_active
        datetime uploaded_at
    }

    ZALO_LOG {
        int id PK
        string recipient_phone
        string recipient_name
        string message_type
        text content_summary
        datetime sent_at
        string status "success|failed|pending|mock"
        text error_msg
    }

    SYSTEM_CONFIG {
        int id PK
        string key UK
        text value
        string description
        datetime updated_at
    }
```

## Data Model Details

### User Management Hierarchy
```
┌─ USER (Users table)
│  ├─ Role: admin, teacher, parent
│  ├─ Credentials: username, phone, password_hash
│  └─ Tracking: created_at, last_login
│
├─ TEACHER (Teacher profile)
│  ├─ Associated with: Schedules, Salaries
│  ├─ Specialty: Subject teaches
│  └─ Salary: base_salary + bonus - deduction
│
└─ STUDENT (Student profile)
   ├─ Associated with: Parent (User), Classes (Enrollment)
   ├─ Education level: primary, secondary, high_school
   └─ Tracking: Attendance, Scores, Rewards, Tuition
```

### Academic Structure
```
ACADEMIC_YEAR (2025-2026)
├─ SEMESTER (Học kỳ Hè, Kỳ 1, Kỳ 2)
│  └─ SCHEDULE (Class sessions)
│     ├─ teacher_id → TEACHER
│     ├─ class_id → CLASS
│     └─ ATTENDANCE (Student presence)
│
COURSE (Subject: Math, Physics, etc.)
└─ CLASS (Math 8A, Physics 10B, etc.)
   ├─ max_students, grade_level
   ├─ ENROLLMENT (Student registration)
   │  └─ SCORE (Student grades)
   │     └─ REWARD (Based on performance)
   └─ CLASS_DOCUMENT (Teaching materials)
```

### Financial Module
```
TUITION_PAYMENT
├─ student_id
├─ class_id
├─ amount: 800,000₫
├─ is_paid: true/false
└─ method: cash/transfer

SALARY
├─ teacher_id
├─ month/year: 03/2026
├─ base_amount: 8,000,000₫
├─ bonus/deduction
└─ is_finalized

EXPENSE
├─ category: salary|rent|utilities|…
├─ amount: flexible
└─ is_tax_deductible
```

## Key Relationships

| Relationship | Description |
|---|---|
| **User → Student** | Parent user can have multiple children (1-to-many) |
| **Teacher → Schedule** | One teacher teaches multiple schedules (1-to-many) |
| **Class → Enrollment** | Students enroll in classes via Enrollment junction table |
| **Schedule → Attendance** | Each schedule has attendance records for enrolled students |
| **Score → Reward** | High scores can auto-trigger reward suggestions |
| **Student → Tuition** | Track payment status per student per class |

## Database Setup Instructions

### Local development (SQLite — default, no setup needed)
```bash
pip install -r requirements.txt

# No DATABASE_URL needed: falls back to sqlite:///nhat_tuyen_dev.db
# (created automatically under instance/ on first run)
python run.py
```

### Production (Supabase PostgreSQL)
```bash
# 1. Get the connection string from Supabase dashboard:
#    Project Settings → Database → Connection string → Session pooler tab
#    (NOT "Direct connection" or "Transaction pooler" — both default to
#    IPv6-only, which Railway can't reach. Session pooler, port 5432, is
#    the free IPv4-compatible option.)
#    If the password has special characters (/, *, #, @, :, ...),
#    percent-encode it first — see urllib.parse.quote(password, safe='')

# 2. Create schema + import current local data into Supabase (run once)
FLASK_ENV=production DATABASE_URL="postgresql://..." python seed_supabase.py

# 3. Set the same DATABASE_URL as an env var on Railway (Variables tab)
```

## Important Tables

### System Configuration
- `system_config`: Store center name, address, Zalo links, etc.

### User Role Access
- **Admin**: Can access all modules
- **Teacher**: Can manage schedules, attendance, scores
- **Parent**: Can view child's attendance, scores, tuition status

### Constraints
- **Unique**: username, phone (for User)
- **Unique**: enrollment (student_id + class_id)
- **Unique**: attendance (schedule_id + student_id)
- **Unique**: salary (teacher_id + month + year)

## Schema Changes

There's no migrations/ folder — schema changes are applied by re-running
`db.create_all()` (via `seed_supabase.py` for Supabase, or automatically
on startup for local dev). Flask-Migrate is in requirements.txt but not
currently wired up.

## Backup Strategy

Use Supabase's own dashboard (Database → Backups) for production backups —
it handles this automatically on all plans. For a manual local snapshot:
```bash
pg_dump "postgresql://..." > backup_$(date +%Y%m%d).sql
```

---

**Created**: April 1, 2026  
**Last Updated**: April 1, 2026  
**Status**: Production Ready
