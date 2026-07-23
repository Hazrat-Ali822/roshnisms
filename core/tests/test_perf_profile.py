"""Measure how heavy each main page is on a FULL school.

Not a pass/fail unit test — it prints a table of (time, SQL queries) per page
against the real demo school (~280 students), so slow pages and N+1 query
problems are obvious. Run it on its own:

    python manage.py test core.tests.test_perf_profile

The number that matters most is the query count: a page whose queries grow with
the number of students/rows is an N+1 problem and will get slower as a real
school fills up.
"""
import time

from django.core.management import call_command
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext

from core.models import Profile


# A page may run this many SQL queries at most. Generous — today's worst page
# uses ~36 — but low enough that an N+1 (thousands) fails loudly.
PAGE_QUERY_BUDGET = 80
# The first request of the day also runs the lazy daily automation.
DAILY_JOB_QUERY_BUDGET = 100

PAGES = [
    ('Dashboard', '/'),
    ('Students list', '/students/'),
    ('Classes & Subjects', '/classes/'),
    ('Timetable', '/timetable/manage/'),
    ('Staff list', '/staff/'),
    ('Fee Collection', '/fees/collection/'),
    ('Receipts', '/fees/receipts/'),
    ('Defaulters', '/fees/defaulters/'),
    ('Expenses', '/fees/expenses/'),
    ('Online Payments', '/fees/online/'),
    ('Daily Absent List', '/attendance/absent/'),
    ('Insights', '/insights/'),
    ('Reports', '/reports/'),
    ('Admissions', '/admissions/'),
    ('Library', '/library/'),
    ('Inventory', '/inventory/'),
    ('Transport', '/transport/'),
    ('Hostel', '/hostel/'),
    ('Discipline', '/discipline/'),
    ('Payroll', '/staff/payroll/'),
    ('Audit Log', '/audit/'),
    ('School Settings', '/settings/'),
    ('Help', '/help/'),
]


class PagePerformanceProfile(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed', demo=True, verbosity=0)

    def test_profile_every_main_page(self):
        user = Profile.objects.get(user__username='office').user
        c = Client()
        c.force_login(user)

        # Warm-up: the FIRST request of the day also runs the lazy daily jobs
        # (late fees, reminders). Get that out of the way so the numbers below
        # show what a normal page load really costs.
        warm_start = time.perf_counter()
        with CaptureQueriesContext(connection) as warm:
            c.get('/help/')
        print('\n\nFirst-request-of-the-day cost (daily jobs): %.0f ms, %d queries'
              % ((time.perf_counter() - warm_start) * 1000, len(warm)))

        results = []
        for label, url in PAGES:
            with CaptureQueriesContext(connection) as ctx:
                start = time.perf_counter()
                resp = c.get(url)
                elapsed = (time.perf_counter() - start) * 1000
            results.append((label, url, resp.status_code, elapsed, len(ctx)))

        results.sort(key=lambda r: -r[4])          # worst query count first
        print('\n\n%-22s %-22s %5s %9s %8s' %
              ('PAGE', 'URL', 'CODE', 'TIME(ms)', 'QUERIES'))
        print('-' * 72)
        for label, url, code, elapsed, queries in results:
            flag = '  <-- HEAVY' if queries > 60 or elapsed > 800 else ''
            print('%-22s %-22s %5d %9.0f %8d%s'
                  % (label, url, code, elapsed, queries, flag))
        print('-' * 72)
        print('Pages profiled: %d   Total queries: %d\n'
              % (len(results), sum(r[4] for r in results)))

        # Nothing should 500.
        broken = [r for r in results if r[2] >= 500]
        self.assertFalse(broken, 'pages returned a server error: %s' % broken)

        # --- Regression guard -------------------------------------------
        # These budgets are far above what any page needs today (the worst is
        # ~36) but far below an N+1 explosion (which runs into the thousands).
        # If this fails, a page started querying once per row — prefetch it.
        over = [(label, q) for label, _u, _c, _t, q in results
                if q > PAGE_QUERY_BUDGET]
        self.assertFalse(
            over,
            'N+1 regression — these pages exceed %d queries on one school: %s'
            % (PAGE_QUERY_BUDGET, over))

        self.assertLessEqual(
            len(warm), DAILY_JOB_QUERY_BUDGET,
            'the first request of the day now costs %d queries (budget %d) — '
            'the daily automation regressed to per-row queries'
            % (len(warm), DAILY_JOB_QUERY_BUDGET))
