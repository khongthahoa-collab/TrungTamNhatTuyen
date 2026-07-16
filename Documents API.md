# REST API — Trung tâm Nhất Tuyên

Base URL: `/api/v1` (same host as the web app, e.g. `https://<domain>/api/v1`)

This API sits alongside the existing server-rendered web app. It doesn't
change any existing page — it's an additive JSON layer for future use
(mobile app, integrations, automation scripts). It reuses the same
business logic and the same per-account permission system as the web
app, so a token has exactly the access that account has in the browser.

## Authentication

Bearer token, not session cookies, not JWT. Log in once to get a token,
then send it on every request:

```
Authorization: Bearer <token>
```

### `POST /api/v1/auth/login`

Body (JSON or form): `{"phone_or_username": "...", "password": "..."}`
(`phone` or `username` are also accepted as the identifier key).

```bash
curl -X POST https://yourdomain/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"phone_or_username": "nhattuyen", "password": "..."}'
```

```json
{"data": {"token": "a1b2c3...", "user": {"id": 1, "full_name": "...", "role": "admin", ...}}}
```

Logging in again issues a **new** token and invalidates the previous
one (one active session per account, same as re-logging-in on the web
invalidates nothing but here simplifies revocation — logging in
elsewhere kicks out the old token).

### `POST /api/v1/auth/logout`

Requires a valid token. Clears it — the token is rejected on any
subsequent request.

### `GET /api/v1/auth/me`

Returns the caller's own profile (`id`, `full_name`, `username`,
`phone`, `role`, `role_label`, `is_master`, `is_active`).

### Errors

- No token / invalid token / token cleared by logout → `401`
- Token valid, but the account's permissions deny that module → `403`

## Permissions

Every endpoint (except `/auth/login`) requires a valid token. Most also
require a **module permission** — the exact same module keys and
read/write levels used by the web app's admin sidebar
(`blueprints/permissions.py`). A GET needs `read` (or `write`); a
POST/PUT/DELETE needs `write`. An account with `permissions = None`
(full access) passes everything; a delegated admin's explicit
`{"students": "deny"}`-style matrix is honored identically to the web
UI — **note this is an allow-list**: as soon as an account has *any*
explicit permission dict, every module not mentioned in it defaults to
`deny`, not `allow`.

| Resource | Module key |
|---|---|
| Students | `students` |
| Classes, Schedules | `classes` |
| Teachers | `teachers` (master-account only, same as the web app) |
| Attendance | `attendance` |
| Scores | `students` (no separate module exists on the web side either) |
| Tuition Payments | `tuition` |
| Rewards | `rewards` |
| Rooms | `rooms` |
| Courses | `courses` |
| Schools | `schools` |
| Notifications | none — always scoped to the caller's own notifications |

## Conventions

**Response envelope.** Success:
```json
{"data": {...}}
```
List endpoints add pagination info:
```json
{"data": [...], "meta": {"page": 1, "pages": 4, "total": 87, "per_page": 30}}
```
Errors:
```json
{"error": {"message": "Không tìm thấy học sinh.", "code": "not_found"}}
```

**Pagination.** List endpoints take `?page=` (default 1) and
`?per_page=` (default 30, max 100).

**Dates & times.** Dates: `YYYY-MM-DD`. Times: `HH:MM` (24h). Same
formats the web forms already use.

**Request bodies.** Every write endpoint accepts either a JSON body
(`Content-Type: application/json`) or a regular form-encoded POST —
whichever is more convenient for the caller.

**Soft delete.** `DELETE` on Students/Classes/Teachers/Rooms/Courses/
Schools doesn't remove the row — it flips `is_active`/`is_deleted`
(mirrors the web app's own delete buttons). `DELETE` on Schedules and
Scores is a real delete (nothing else depends on those rows). Rewards'
`/cancel` also hard-deletes (matches the web app: an unconfirmed
suggested reward is just discarded).

**Status codes:** `200` ok, `201` created, `400` validation error,
`401` unauthorized, `403` forbidden, `404` not found, `409` conflict
(schedule clash, duplicate, etc.).

---

## Students

| Method | Path | Write? |
|---|---|---|
| GET | `/students` | |
| GET | `/students/<id>` | |
| POST | `/students` | ✓ |
| PUT | `/students/<id>` | ✓ |
| DELETE | `/students/<id>` | ✓ |
| POST | `/students/<id>/enroll` | ✓ |
| DELETE | `/students/<id>/enroll/<class_id>` | ✓ |

List filters: `q` (name search), `grade` (exact `current_grade`, e.g.
`Lớp 6`), `school_q` (school name search), `active` (`1`/`0`, default
`1`).

`GET /students/<id>` additionally embeds `active_classes` (array of
`Class.to_dict()`).

Create/update body:
```json
{
  "full_name": "Nguyễn Văn A",
  "level": "secondary",
  "current_grade": "Lớp 6",
  "gender": "male",
  "date_of_birth": "2014-05-01",
  "current_school": "THCS ABC",
  "school_id": 3,
  "parent_name": "Nguyễn Văn B",
  "parent_phone": "0900000000",
  "note": "..."
}
```
`level` must be one of `primary` / `secondary` / `high_school`, and
`current_grade` must be a valid grade label for that level (e.g.
`secondary` → `Lớp 6`..`Lớp 9`; `primary` → `Tiền tiểu học`, `Lớp 1`..
`Lớp 5`; `high_school` → `Lớp 10`..`Lớp 12`) — same `GRADE_BY_LEVEL`
table the web form validates against. `full_name`, `level`,
`current_grade` are required on create.

`POST /students/<id>/enroll` — body `{"class_id": 5}`. Runs the exact
same schedule-conflict check the web app's "Thêm học sinh vào lớp" uses
(`find_student_schedule_conflict`) — returns `409` with the same
human-readable Vietnamese conflict message if the student is already
scheduled elsewhere at an overlapping time.

`DELETE /students/<id>/enroll/<class_id>` — soft-unenrolls (sets the
enrollment inactive, doesn't delete the row).

## Classes

| Method | Path | Write? |
|---|---|---|
| GET | `/classes` | |
| GET | `/classes/<id>` | |
| GET | `/classes/<id>/schedules` | |
| POST | `/classes` | ✓ |
| PUT | `/classes/<id>` | ✓ |
| DELETE | `/classes/<id>` | ✓ |
| POST | `/classes/<id>/students` | ✓ |

List filters: `course_id`, `grade_level`, `teacher_id`, `active`
(default `1`).

`GET /classes/<id>` adds `current_enrollment` (int) to the payload.

`GET /classes/<id>/schedules` — optional `date_from`/`date_to`, returns
every `Schedule` row for that class.

**Create** — generates the full semester's worth of `Schedule` rows
automatically (same as the web app's "Thêm lớp học" — you don't create
Schedule rows yourself for a class's regular weekly slots, use
`POST /schedules` only for a one-off ad-hoc session):
```json
{
  "course_id": 3,
  "grade_level": "Lớp 7",
  "primary_teacher_id": 4,
  "assistant_teacher_ids": [5],
  "max_students": 20,
  "monthly_fee": 800000,
  "schedule": [
    {"weekday": 0, "start_time": "18:00", "end_time": "19:30", "room_id": 2, "teacher_id": 4}
  ]
}
```
`weekday` is `0`=Monday .. `6`=Sunday. `course_id`, `grade_level`,
`primary_teacher_id`, and at least one `schedule` row are required.
The class's start/end dates are always the current school year — not
settable via the API, same as the web form. Returns `409` (`code:
duplicate_slot`) if the teacher already has an identical class/slot
combo, or `409` (`code: schedule_conflict`) if the teacher is already
booked elsewhere at an overlapping time on any date from today onward
(past-date conflicts are ignored, matching the web app's fix for
false-positive conflict reports on already-elapsed school-year dates).

**Update** — partial; only send fields you're changing. Reassigning
`primary_teacher_id` automatically cascades to that class's *future*
`Schedule.teacher_id` rows (today onward) — past sessions keep their
original teacher on record, exactly like the web app's class-edit
screen.

**`POST /classes/<id>/students`** — body `{"student_ids": [1,2,3]}`.
Adds every student that has no schedule conflict; students that do
conflict are **skipped, not blocking the rest of the batch** — the
response reports both:
```json
{"data": {"added": 2, "skipped": [{"student_id": 3, "message": "... đã có lịch học trùng ..."}]}}
```

## Teachers

*Master-account tokens only* — the `teachers` module is hard-restricted
to `is_master` accounts regardless of a delegated admin's permission
matrix, same as the web app.

| Method | Path | Write? |
|---|---|---|
| GET | `/teachers` | |
| GET | `/teachers/<id>` | |
| POST | `/teachers` | ✓ |
| PUT | `/teachers/<id>` | ✓ |
| DELETE | `/teachers/<id>` | ✓ |

Create body: `{"full_name": "...", "gender": "male", "phone": "...", "username": "...", "is_staff": true, "base_salary": 5000000}`.
`full_name` and `gender` are required; `username` auto-generates if
omitted. The account is created with a temp password and
`must_change_password=true` — the response includes `temp_password` for
you to relay to the teacher once.

Delete soft-deletes the underlying `User` (`is_deleted=true,
is_active=false`).

## Schedules

| Method | Path | Write? |
|---|---|---|
| GET | `/schedules` | |
| GET | `/schedules/<id>` | |
| POST | `/schedules` | ✓ |
| PUT | `/schedules/<id>` | ✓ |
| POST | `/schedules/<id>/cancel` | ✓ |
| DELETE | `/schedules/<id>` | ✓ |

List filters: `class_id`, `teacher_id`, `date_from`, `date_to`.

`POST /schedules` creates a single **ad-hoc** session (a "buổi tăng
cường") — not for a class's regular weekly pattern, which is generated
by `POST /classes`. Body: `{"class_id":, "date":, "start_time":, "end_time":, "teacher_id":, "room_id":, "topic":, "schedule_type": "makeup"}`.
If `room_id` is set, checks for a room double-booking and returns `409`
(`code: room_conflict`) if that room is already reserved for an
overlapping time.

`POST /schedules/<id>/cancel` — body `{"reason": "..."}` (optional),
sets `is_cancelled=true`.

`DELETE /schedules/<id>` is a real delete (not soft).

## Attendance

| Method | Path | Write? |
|---|---|---|
| GET | `/schedules/<id>/attendance` | |
| POST | `/schedules/<id>/attendance` | ✓ |

`GET` returns the schedule plus the full class roster with each
student's current attendance status:
```json
{"data": {"schedule": {...}, "roster": [{"student_id": 1, "student_name": "...", "status": "present", "reason": null}]}}
```

`POST` is a bulk upsert — body:
```json
{"attendance": [{"student_id": 1, "status": "present"}, {"student_id": 2, "status": "absent", "reason": "Ốm"}]}
```
`status` must be one of `present` / `absent` / `late` / `excused`.
Recomputes the class's `AttendanceSummary` counts the same way the
web's "Lưu điểm danh" does. **A teacher-role token may only record
attendance for a class it's assigned to (primary or assistant teacher)
and only on the session's actual date** — an admin-role token has
neither restriction, matching the web app's own teacher-vs-admin
distinction on this route.

## Scores

| Method | Path | Write? |
|---|---|---|
| GET | `/scores` | |
| GET | `/scores/<id>` | |
| POST | `/scores` | ✓ |
| PUT | `/scores/<id>` | ✓ |
| DELETE | `/scores/<id>` | ✓ |

List filters: `student_id`, `class_id`.

Create body: `{"student_id":, "class_id":, "score_type": "midterm", "score_value": 8.5, "max_score": 10, "score_source": "center", "exam_date": "2026-05-01", "school_name": "...", "note": "..."}`.
`student_id`, `class_id`, `score_type`, `score_value` are required. On
create, this runs the same auto-suggested-reward logic the web app's
score entry uses (`create_suggested_reward`) — the response includes
`suggested_reward` (a `Reward` object, or `null` if the score didn't
qualify for one).

## Tuition Payments

| Method | Path | Write? |
|---|---|---|
| GET | `/tuition/overview` | |
| GET | `/tuition-payments` | |
| GET | `/tuition-payments/<id>` | |
| POST | `/tuition-payments` | ✓ |
| PUT | `/tuition-payments/<id>` | ✓ |
| POST | `/tuition-payments/<id>/pay` | ✓ |

Each `TuitionPayment` row is one student's bill for one class for one
month. `amount` is that month's fee only (defaults to `Class.monthly_fee`
when generated — there's no per-month fee-proration config, the standard
class fee applies to every actively-enrolled student unless edited per
row). `debt_carried_over` is any unpaid `total_due` automatically rolled
over from the same student+class's previous-month row (0 if none, or if
that month was fully paid — this happens automatically wherever a row is
created; there's no separate "run carryover" endpoint). `total_due`
(`amount + debt_carried_over`) and `amount_collected` (cumulative amount
actually received — a live sum of the underlying payment ledger, see
below) are what `status` is derived from: `paid` (`is_paid`) / `partial`
(`amount_collected > 0` but not fully paid) / `unpaid`.

**Payment ledger.** Every payment is an append-only `TuitionTransaction`
row (amount, method, note, who received it, when) — `amount_collected`
is always `SUM()` of these, recomputed inside the same DB transaction
every time a payment is recorded. A correction is a new transaction, not
an edit to history; this is what makes the numbers trustworthy for
accounting reconciliation. There's no endpoint to list individual
transactions yet (out of scope for this pass) — `amount_collected` /
`status` on the payment itself is the aggregate view.

**Fee-change audit log.** Every time a payment's `amount` is edited via
`PUT`, a `TuitionFeeAuditLog` row is written (old amount, new amount, who,
when) — not exposed via its own endpoint yet, but every fee override is
attributable in the database for financial transparency.

**`GET /tuition/overview`** — `?month=&year=&class_id=&course_id=` (all
optional, month/year default to today). KPI totals plus a per-class
breakdown:
```json
{"data": {
  "month": 7, "year": 2026,
  "total_expected": 45000000, "total_collected": 32000000, "total_outstanding": 13000000,
  "classes": [{"class_id": 3, "class_name": "Toán 7", "total_students": 20,
               "paid_count": 15, "unpaid_count": 5,
               "collected_amount": 12000000, "outstanding_amount": 3000000,
               "carried_debt_amount": 500000}]
}}
```
If `class_id` or `course_id` is given and doesn't exist, `404`.

List filters (`GET /tuition-payments`): `student_id`, `class_id`,
`month`, `year`, `is_paid` (`1`/`0`). `404` if `class_id` is given and
doesn't exist.

Create body: `{"student_id":, "class_id":, "month":, "year":, "amount":, "method": "cash", "note": "..."}`.
`debt_carried_over` is computed automatically from the previous month —
not settable directly. Returns `409` (`code: duplicate`) if a row for
that student+class+month already exists (the API enforces the same
one-row-per-student-per-class-per-month rule as the web app, backed by
a DB-level unique constraint).

**Update (`PUT`)** is pure field edits — `amount`, `note`, `method`.
Changing `amount` is a fee override for that one month, and writes a
`TuitionFeeAuditLog` row automatically. This endpoint does **not** record
payments (it no longer accepts `is_paid`/`amount_collected` — use `/pay`
below for that).

**`POST /tuition-payments/<id>/pay`** — records a payment. Body:
`{"amount":, "method": "cash", "note": "..."}` — `amount` omitted or `0`
collects the full remaining balance (same as leaving the web form's
amount field blank); a smaller amount records a **partial** payment.
Row-locked on Postgres and inserts a new ledger transaction, so two
concurrent requests against the same bill can't double-collect or race.

No delete endpoint — matches the web app, which doesn't offer one
either (tuition records are financial history, not deletable).

## Rewards

| Method | Path | Write? |
|---|---|---|
| GET | `/rewards` | |
| GET | `/rewards/<id>` | |
| POST | `/rewards` | ✓ |
| POST | `/rewards/<id>/confirm` | ✓ |
| POST | `/rewards/<id>/cancel` | ✓ |

List filter: `student_id`, `show` (`pending` / `confirmed` / omit for
all).

Create body: `{"student_id":, "reason": "...", "amount": 50000, "reward_type": "cash", "reward_date": "2026-07-01", "note": "..."}`.
Manually-created rewards are **not** auto-suggested/pending — they're
created directly (`is_suggested=false`); use `/confirm` to finalize a
reward that came from the auto-suggestion flow (`POST /scores`).

`POST /rewards/<id>/confirm` — optional body `{"amount": 60000}` to
adjust the amount before confirming.

`POST /rewards/<id>/cancel` — deletes the (unconfirmed) reward
suggestion outright.

## Rooms / Courses / Schools

Three parallel simple resources, same shape:

| Method | Path | Write? |
|---|---|---|
| GET | `/rooms`, `/courses`, `/schools` | |
| GET | `/rooms/<id>`, `/courses/<id>`, `/schools/<id>` | |
| POST | `/rooms`, `/courses`, `/schools` | ✓ |
| PUT | `/rooms/<id>`, `/courses/<id>`, `/schools/<id>` | ✓ |
| DELETE | `/rooms/<id>`, `/courses/<id>`, `/schools/<id>` | ✓ (soft) |

- **Room**: `{"name":, "branch":, "floor":, "room_number":, "capacity": 20}` — `name` required.
- **Course**: `{"name":, "level":, "description":}` — `name` required.
- **School**: `{"name":, "grade_from":, "grade_to":}` — `name` required, must be unique.

## Notifications

| Method | Path | Write? |
|---|---|---|
| GET | `/notifications` | |
| POST | `/notifications/<id>/read` | ✓ |

Always scoped to the caller's own notifications (`user_id` = token
owner) — no module permission needed, every authenticated account can
reach this, same as the bell icon in the web app's navbar.

---

## Out of scope (this pass)

Not yet exposed via the API — flagged as a deliberate cut, not an
oversight, for a possible phase 2:

- **Exams** (question banks, exam attempts, grading) — a large
  sub-system roughly the size of everything above combined.
- **Reports** — currently read-only aggregate views, derivable by
  combining the resources above.
- **Settings / system config, Zalo integration.**

## Deploying this

`User.api_token` is a new column (`migrate_add_api_token.py`, repo
root, not committed to git). It must be run against the **production**
database separately from the code deploy — the API will 500 on login
until that column exists there.
