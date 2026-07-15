# Roshni Public School - Management System

A complete, integrated school management system: one login, real role-based
access, and one shared database, built step by step.

- **Stack:** Django + Django Templates + SQLite (PostgreSQL-ready)
- **Auth:** Django's built-in authentication

---

## How to run (inside the `roshni_sms` folder)

> Cleanest: unzip into a **fresh folder**, then run the commands below.

```
# (optional) virtual environment
python -m venv venv
# Windows:  venv\Scripts\activate
# macOS/Linux:  source venv/bin/activate

pip install -r requirements.txt

python manage.py makemigrations core
python manage.py migrate
python manage.py seed --demo      # demo data (skip this for a real school)

python manage.py runserver
```

Open: **http://127.0.0.1:8000/**  (stop with `Ctrl + C`)

To use it across the school over Wi-Fi (no internet), see
**SYNC_AND_DEPLOYMENT.md**.

---

## Login accounts (password for all: **roshni123**)

| Username     | Role               | Highlights                                                        |
|--------------|--------------------|-------------------------------------------------------------------|
| `principal`  | Admin / Principal  | Students, Staff, Admissions, Communication, Transport, Library, Certificates, Calendar, Inventory, Visitors, **Users & Roles** |
| `teacher`    | Teacher            | Mark Attendance, Enter Marks                                       |
| `parent`     | Parent             | Child's Attendance, Results, Fees                                 |
| `student`    | Student            | Own Attendance, Results, Fees                                     |
| `finance`    | Finance            | Fee Collection, Receipts, Defaulters, Expenses                    |
| `admin`      | Superuser          | Everything + Django admin (`/admin`)                             |

---

## What Step 6 adds: Users & Roles (sign in as `principal`)

- **Create user:** username, password, full name, and a **role**. For a teacher
  you can attach a class; for a parent/student you can attach a student.
- **Change role:** pick a new role for any user and **Update** - their access
  changes immediately. This is the live proof that "Admin / Principal / Accountant"
  are just **roles**, not separate systems.
- **Reset password** to `roshni123`, and **Disable / Enable** accounts (you cannot
  disable yourself or the superuser).

Try it: create a user with the Teacher role and a class, sign out, sign in as that
new user - they get the teacher view automatically.

### Offline + sync
That is an architecture topic, not a screen. See **SYNC_AND_DEPLOYMENT.md** for
(a) running this app across the school with no internet today, and (b) the
offline-first design for the future mobile (Flutter) app.

---

## The full build, step by step (all runnable)

- **Step 1:** login + role-based access + shared database.
- **Step 2:** attendance + marks (teacher writes, parent/student reads).
- **Step 3:** fees & finance (collection, receipts, defaulters, expenses).
- **Step 4:** admissions, communication (SMS), transport, library.
- **Step 5:** students, staff, certificates, calendar, inventory, visitors.
- **Step 6:** Users & Roles management + offline/deployment design.

Reset the demo data anytime with: `python manage.py seed --demo`
(For a **real school**, use `python manage.py setup_school` instead — it creates
a blank school with one admin login and **no** demo data. See
**SETUP_FOR_SCHOOLS.md**.)

---

## Student / Parent portal — rich UI (matches the prototype)

The parent and student views now mirror the original prototype, driven by real
database data:

- **Dashboard** — stat cards (attendance %, latest result %, fee status, subjects)
  plus quick links.
- **Subjects & Materials** — subject cards that open a materials list (notes,
  books, slides, past papers). Files are modelled in the database; actual file
  download is enabled once a school uploads real files.
- **Attendance** — a full month **calendar** with colour-coded Present / Absent /
  Leave / Holiday cells and a legend, built from real attendance records.
- **Results** — a printable **report card** (school crest, per-subject grades with
  colour, total, percentage and overall grade). Use the Print button to save PDF.
- **Timetable** — the class's weekly grid, with today's column highlighted.
- **Fees** — a printable **fee voucher** (tuition + lab breakdown) and full
  payment history.
- **Profile** — the student's details on record.

Sign in as `parent` or `student` (password `roshni123`) to see all of the above.
The same upgrade can be applied to the teacher, finance and admin screens next.

---

## Assignments & Quizzes — now fully functional (no longer "coming soon")

**Teacher** (sign in as `teacher`):
- **Assignments** — create an assignment (title, subject, due date, instructions),
  then open it to see every student's submission and type a grade / feedback.
- **Quizzes** — create a quiz, add MCQ questions (4 options + correct answer),
  and see each student's auto-scored attempt.

**Student** (sign in as `student`):
- **Assignments** — read the task and submit your answer; see your status and the
  teacher's grade once marked.
- **Quizzes** — take the quiz, get an **instant auto-score**, review the answer key,
  and retake if you want.

**Parent** sees the same assignment status, submissions and quiz scores for their
child (read-only).

The demo seed adds 3 assignments and 3 quizzes (with questions) to Class 9-A.
Ayaan's account is left with nothing submitted/attempted so you can test the full
flow end to end.
