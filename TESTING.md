# Testing guide — Roshni SMS

This project is a product headed to market, so it keeps an **automated test
suite** that anyone (or a CI server) can run in one command. This file explains
what kinds of testing we do, how each maps to real tools here, and how to run
everything.

---

## TL;DR — run everything

```bash
python run_tests.py            # whole test suite
python run_tests.py --coverage # + how much code is tested (HTML report)
python run_tests.py --all      # + security check too
```

Or the plain Django way:

```bash
python manage.py test core                      # all tests
python manage.py test core.tests.test_timetable # one module
python manage.py test core.tests.test_smoke     # fast smoke check
```

A green run means the product still works. Every push to GitHub also runs the
suite automatically (see [CI](#continuous-integration-ci)).

---

## The types of testing, and how we do them here

| Type | What it checks | How it's done in this repo | Automated? |
|---|---|---|---|
| **Unit** | One function/piece of logic in isolation | `core/tests/test_*.py` (Django `TestCase`) | ✅ |
| **Integration** | Several pieces working together (e.g. collect fee → receipt → SMS) | Feature tests using the test `Client` | ✅ |
| **Functional** | A feature does what a user expects | `Client.get/post` asserting the outcome | ✅ |
| **System / End-to-End** | A whole flow: login → add → result | Multi-step `Client` tests; a real browser is optional (Playwright) | ✅ (server-level) |
| **Regression** | Old features didn't break after a change | Re-run the **whole suite** after every change | ✅ |
| **Smoke / Sanity** | Nothing is on fire — key pages load | `core/tests/test_smoke.py` (200 for each role) | ✅ |
| **Security** | Access control + safe deployment config | `test_access.py`, `test_security.py` + `manage.py check --deploy` | ✅ |
| **Performance / Load** | Speed when many users hit it at once | Locust (opt-in, see below) | ⚙️ opt-in |
| **Usability** | Is it easy for a real person? | Manual — the checklist below | 📋 manual |
| **Acceptance (UAT)** | Meets the customer's agreed requirements | Done with real schools before launch | ⏳ later |

There are ~60 test modules in `core/tests/`. `core/tests/factory.py::build_world()`
builds a complete school (one user per role, classes, students, exams) — use it
in new tests.

---

## Measuring coverage (how much is tested)

```bash
python run_tests.py --coverage
# then open htmlcov/index.html
```

Coverage shows the percentage of `core/` executed by the tests and highlights the
exact lines never run — a to-do list for where to add tests next. Config is in
`.coveragerc`.

---

## Continuous Integration (CI)

`.github/workflows/tests.yml` runs the full suite (with coverage) and the
security check on **every push and pull request to `main`**. You do nothing —
GitHub shows a ✓ or ✗ on each commit. This is real "automated testing": broken
changes are caught before they ship.

---

## Writing a new test (pattern)

```python
from django.test import Client, TestCase
from core.tests.factory import build_world

class MyFeatureTests(TestCase):
    def setUp(self):
        self.w = build_world()

    def test_teacher_marks_attendance(self):
        c = Client(); c.force_login(self.w.teacher_u)
        resp = c.post('/attendance/', {...})
        self.assertEqual(resp.status_code, 302)   # saved + redirect
        # assert the record now exists in the database
```

Rule of thumb: **every behaviour you change or add gets a test**, so the next
change can't silently break it.

> Note on tenancy: the per-request database switch is **disabled under tests**
> (`if 'test' in sys.argv`), so tests run against one clean test DB. Keep that
> guard intact (see `CLAUDE.md` §5).

---

## Opt-in: Performance / Load testing (Locust)

Not part of the default suite (it needs a running server and extra tooling).
When you want it:

```bash
pip install locust
# start the app in one terminal:
python manage.py runserver
# create locustfile.py with your user flows, then in another terminal:
locust -f locustfile.py --host http://127.0.0.1:8000
```

Locust opens a web dashboard where you set "N users" and watch response times —
this is how you learn how many concurrent users one server can hold before it
slows down. Ask and we can add a ready-made `locustfile.py` covering login +
dashboard + fee collection.

---

## Manual: Usability checklist

Some things only a human can judge. Before a release, click through:

- [ ] Sign in on a **phone** — is text readable, are buttons tappable?
- [ ] Add a student, collect a fee, print a receipt — is the flow obvious?
- [ ] Try a wrong password — is the error message clear and helpful?
- [ ] Switch to **dark mode** — is everything still legible?
- [ ] Change the school's accent colour — do buttons/text stay readable?
- [ ] Open the app **offline** — does it still work?
