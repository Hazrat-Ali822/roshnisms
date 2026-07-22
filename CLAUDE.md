# CLAUDE.md — Project orientation for AI code agents

> **Read this first.** This single file explains what this project is, how it is
> built, where everything lives, and the rules you must not break. It is written
> for an AI coding agent (Claude Code, Cursor, etc.) or a new developer opening
> the repo cold. If something here disagrees with the code, the code wins —
> update this file.

---

## 1. What this project is

**Roshni SMS** — a **School Management System** for Pakistani schools, built in
**Django** with **server-rendered templates** (no React/Vue, no REST API). It runs
an entire school from one login: students, staff, attendance, exams & report
cards, fees & online payments, admissions, timetable, HR/payroll, library,
transport, hostel, inventory, communication (SMS/WhatsApp), certificates, and
more.

It has a **dual identity** — the same codebase serves both:

1. **Single-school install** — runs on one school PC / LAN, **works fully
   offline** (no internet). All data in a local `db.sqlite3`. `DEBUG` defaults ON
   so it runs out-of-the-box; WhiteNoise serves static files.
2. **Multi-tenant SaaS** — one deployment hosting many schools, each on its own
   subdomain **or** URL path, each with **its own separate SQLite file**, managed
   from a `/saas-admin/` portal with subscriptions/billing.

Context: Pakistan. Currency **PKR**, gateways **JazzCash / Easypaisa / bank**,
fields like CNIC/B-Form, timezone **Asia/Karachi**.

---

## 2. Quick facts

| Thing | Value |
|---|---|
| Framework | Django 4.2–5.0 (`requirements.txt`: `Django>=4.2,<5.1`) |
| Language / UI | Python + Django Templates (server-rendered). **No** DRF, **no** JS framework. |
| Database | SQLite (one file per tenant school; see §5) |
| Django apps | **One real app: `core`**. Project package: `roshni`. (`saas_tenant/` exists but is **dead/unused** — ignore it.) |
| Static | WhiteNoise. Self-hosted fonts + Chart.js in `core/static/vendor/` (no external CDNs — must stay offline-capable). |
| Auth | Django auth; login by **username OR email** (`core/backends.py`). |
| Sessions | **Signed-cookie** sessions (`SESSION_ENGINE = signed_cookies`) — required so DB-swapping mid-request doesn't break sessions. |
| Size | `core/views.py` ≈ 7,700 lines · `core/models.py` ≈ 1,370 lines · ~121 URL routes · ~101 templates · ~59 migrations · ~60 test modules |
| Config | Environment variables prefixed `ROSHNI_` (see §9). |

---

## 3. Run it / dev workflow

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py seed --demo        # demo data (SKIP for a real school)
python manage.py runserver          # http://127.0.0.1:8000/
```

- **Real (blank) school** instead of demo: `python manage.py setup_school`
  (creates one school + one `admin` login, no demo data). First real login is
  `admin` / `admin123` → forced password change.
- **Demo logins** (password `roshni123`): `admin` (superuser), `principal`,
  `teacher`, `finance`, `parent`, `student`.
- **Run tests:** `python manage.py test core` (or a module, e.g.
  `python manage.py test core.tests.test_timetable`).

**Management commands** (`core/management/commands/`): `seed`, `setup_school`,
`ensure_admin`, `backup_db`, `fees_generate`, `fees_daily`, `fees_remind`,
`migrate_tenants`, `reset_tenant`.

---

## 4. Where everything lives (architecture map)

Everything is in the **`core`** app. Start at the file that matches your task:

| File | What it holds |
|---|---|
| `core/models.py` | **40+ models** — the whole domain (see §7). |
| `core/views.py` | **Every view** (~7.7k lines). Giant flat file; find your feature by name. Helpers: `_pk()`, `_audit()`, `_build_pdf`, `_report_card_data`, `_generate_timetable`, `run_daily_jobs`. |
| `core/urls.py` | ~121 flat routes → views. The routing map. |
| `core/decorators.py` | `role_required(*roles)` — access control (see §6). |
| `core/middleware.py` | **The tenancy engine** — per-request DB swap + routing (see §5). **Most fragile code in the repo.** |
| `core/tenancy.py` | `build_clean_tenant_db()` — creates a fresh tenant SQLite (schema + that school's admin only). |
| `core/context_processors.py` | `branding` (theme colours from the school's logo/colours), `notifications`, `nav_children`, `pwa`. Runs on **every** page. |
| `core/backends.py` | `EmailOrUsernameBackend` — login by username or email. |
| `core/crypto.py` | At-rest encryption for gateway/SMS secrets (`EncryptedCharField`). |
| `core/sms.py`, `core/emailer.py`, `core/push.py`, `core/payments.py` | SMS/WhatsApp, email, web-push, and payment-gateway integrations. |
| `core/templates/` | ~101 templates. `base.html` = shell (sidebar, topbar, theme `:root` vars, global JS). Pages extend it. |
| `core/static/css/app.css` | The whole stylesheet. Theme is driven by CSS custom properties set from Python (see §8). Cache-busted with `?v=YYYYMMDD…`. |
| `roshni/settings.py` | Settings. Middleware order matters (see §5). |
| `roshni/urls.py` | Includes `core.urls` + Django `/admin/`. |

---

## 5. ⚠️ Tenancy — the most important & most fragile subsystem

This is **hand-rolled multi-tenancy**, NOT `django-tenants`. Understand it before
touching middleware, sessions, or anything DB-connection related.

**How it works:** on every request, `TenantDatabaseMiddleware` figures out which
school this request is for (from the **subdomain**, e.g. `myschool.host.com`, or
the **first URL path segment**, e.g. `/myschool/…`), then **re-points the
`default` DB connection at that school's own SQLite file** (`<subdomain>.sqlite3`)
by mutating `connection.settings_dict['NAME']` and reconnecting. The master
`db.sqlite3` holds the registry of schools; each tenant file holds that school's
data. If the tenant file doesn't exist yet, `build_clean_tenant_db()` creates it.

**Middleware order (in `settings.py`) is load-bearing — do not reorder blindly:**
1. `TenantDatabaseMiddleware` — resolves tenant & switches the DB **before**
   sessions/auth load, so auth reads the right database.
2. Django `SessionMiddleware` / `AuthenticationMiddleware`.
3. `TenantRoutingMiddleware` — subscription checks, cross-tenant redirects, and
   the lazy daily-jobs trigger, **after** the user is known.
4. `ForcePasswordChangeMiddleware`, `SessionIdleTimeoutMiddleware`.

**Rules & gotchas:**
- Connections are **thread-local**; the middleware resets to master at the top of
  each request so a previous request's tenant file can't answer "which school?".
- Sessions are **signed cookies** on purpose — a server-side session store would
  break when the DB is swapped mid-request.
- **Tests disable DB-switching** via `if 'test' in sys.argv`. Branding/tenant
  code paths therefore behave differently under test — keep that guard working.
- Path-based tenancy rewrites `PATH_INFO` and sets `SCRIPT_NAME` / script prefix
  so `{% url %}` and redirects keep the `/<subdomain>/` prefix. PWA/asset routes
  (`manifest.webmanifest`, `sw.js`, `assetlinks.json`) must stay reachable even
  when a subscription has lapsed.
- Branding (`context_processors.branding`) only shows a school's identity in an
  **explicit tenant context**; it reads `School.objects.first()` from the
  *tenant's own* DB, not the master registry.

---

## 6. Roles & access control

**7 roles** (`Profile.role`): `owner`, `principal`, `admin`, `finance`,
`teacher`, `parent`, `student`. `admin` = **"Office / Administrator"**, the
school-level **super-role**.

- Access = `@login_required` + `@role_required(*roles)` (`core/decorators.py`).
- **`role == 'admin'` bypasses EVERY `role_required` check** — the Office role
  sees all school modules. So `@role_required('finance')` admits `finance` **and**
  `admin`.
- There is **no object-level tenant check** in the decorator; tenant isolation is
  enforced entirely by the middleware (§5).
- **SaaS-admin** views use `@login_required` + in-view `is_superuser` checks (not
  `role_required`). Django `/admin/` is superuser-only (enforced in
  `TenantRoutingMiddleware`).
- The `dashboard` view (`/`) dispatches by role. Superuser hitting `/` →
  `/saas-admin/`.

⚠️ **Decorator ordering gotcha:** never insert a constant/helper *between*
`@login_required @role_required(...)` and the `def` — it silently decorates the
wrong object. Put module-level constants **above** the decorators.

---

## 7. Domain model (what's in `models.py`)

~40+ models. Key clusters:

- **People:** `School`, `Profile` (role + links), `Student`, `Guardian`,
  `ClassRoom` (has `class_teacher`), `Subject` (per class, `periods_per_week`),
  `TeachingAssignment` (teacher↔subject↔class).
- **Academics:** `Exam`, `Marks`/results, `TimetableSlot`, `Assignment`,
  `Submission`, `Quiz`/questions/attempts, attendance records.
- **Fees/Finance:** `FeeChallan`, `FeeHead`, payments, `OnlinePayment`,
  receipts, expenses, concessions, ledger.
- **HR:** staff, staff attendance, payroll/payslips, leave, appraisals.
- **Ops:** transport, hostel, library, inventory, visitors, discipline,
  complaints, calendar, certificates, ID cards, announcements/messages.
- **System:** `LoginAttempt` (lockout), audit log, SaaS subscription fields on
  `School`.

Migrations are **per-change and numerous (~59)** — always create migrations for
model edits (`python manage.py makemigrations core`) and keep them in order.

---

## 8. Theming & UI conventions

- The whole theme is **CSS custom properties** set from Python. `branding()`
  derives colours from the school's `primary_color` / `accent_color` (or its
  **logo**), computes readable text colours (sRGB luminance), and exposes them.
  `base.html` writes them into an inline `:root { --ink; --accent; --accent-rgb; … }`.
- Buttons/shadows use `rgba(var(--accent-rgb), a)` so they harmonise with **any**
  school colour. Do not hardcode brand colours in CSS.
- **No external CDNs** — fonts and Chart.js are self-hosted under
  `core/static/vendor/` so the app works fully offline. Keep it that way.
- Bump the `?v=` on `app.css` (and other static refs in `base.html`) when you
  change CSS so browsers pick it up.
- **Editing pattern:** listing rows are read-only with an **Edit** button that
  reveals an inline form (`.edit-row` + `rowEdit()` in `base.html`) — not
  inline-cell editing. Every listing page has a client-side search box.

---

## 9. Configuration (environment variables)

All optional; sensible offline defaults. Prefix `ROSHNI_`:

`ROSHNI_DEBUG` (default `1`/on), `ROSHNI_ALLOWED_HOSTS`, `ROSHNI_HTTPS` (set `1`
for real internet deploy — enables secure cookies/HSTS), `ROSHNI_SECRET_KEY`,
`ROSHNI_FIELD_KEY` (encryption; auto-generated to `.field_key` if unset),
`ROSHNI_IDLE_TIMEOUT`, `ROSHNI_SESSION_AGE`, SMS/VAPID vars. Secret/field/VAPID
keys auto-generate into dotfiles next to the DB — **back them up with the DB**.

---

## 10. Testing

- **Run everything:** `python run_tests.py` (add `--coverage` or `--all`). Plain
  Django: `python manage.py test core`, or one module e.g.
  `python manage.py test core.tests.test_smoke`.
- ~60 test modules in `core/tests/test_*.py` (unit + integration + functional +
  smoke + security). `core/tests/factory.py::build_world()` builds a full school
  with one user per role — use it in new tests.
- `core/tests/test_smoke.py` = fast "does every role's main page return 200".
- **Coverage:** `.coveragerc` present; `python run_tests.py --coverage` writes
  `htmlcov/index.html`.
- **CI:** `.github/workflows/tests.yml` runs the suite + `check --deploy` on every
  push/PR to `main`.
- Remember tenancy/DB-switching is disabled under test (`'test' in sys.argv`).
- Add/adjust tests for any behaviour you change; this repo keeps tests green.
- Full details + the testing-type map: **`TESTING.md`**.

---

## 11. Deploying a change (typical)

```bash
git pull origin main
python manage.py migrate                 # if you added migrations
python manage.py collectstatic --noinput # if you touched static/CSS
# then reload the app server (e.g. touch the wsgi file)
```

- **PythonAnywhere:** full guide in **`DEPLOY_PYTHONANYWHERE.md`**. The big
  performance levers there: set `ROSHNI_DEBUG=0` in the WSGI file (enables
  template caching + fast static), **map `/static/` in the Web tab** so PA serves
  assets directly, and `collectstatic` (WhiteNoise `CompressedStaticFilesStorage`
  pre-builds `.gz`/`.br`). Static config lives in `settings.py` `STORAGES`.
- **Convention in this repo:** changes are committed **and pushed to `main`**
  after each task (the maintainer wants auto-push). Commit messages end with a
  `Co-Authored-By:` trailer.
- **Data safety:** School Settings → Backup downloads a full copy; Restore
  re-imports a `.sqlite3` backup. Take a backup before destructive operations
  (e.g. year-end promotion).

---

## 12. Gotchas checklist (don't get burned)

- [ ] **Don't reorder middleware** — DB swap must run before sessions/auth (§5).
- [ ] **Don't put code between `@role_required` and `def`** (§6).
- [ ] **Don't add external CDN/font/script links** — breaks offline (§8).
- [ ] **Don't hardcode brand colours** — use the CSS variables (§8).
- [ ] **Do create migrations** for every model change (§7).
- [ ] **Keep the `'test' in sys.argv` guard** intact in tenancy code (§5, §10).
- [ ] **Ignore `saas_tenant/`** — it's a dead app.
- [ ] The in-app UI/text is **English**; user guide lives at `/help/` (role-aware,
      data in `views.py::_ROLE_GUIDE` / `_HELP_*`).

---

*Whole-project map for AI agents. Feature-level docs are in the `/help/` page and
the code itself. When you change how the system works, update this file so the
next agent starts from the truth.*
