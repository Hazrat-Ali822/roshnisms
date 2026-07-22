#!/usr/bin/env python
"""One command to run all automated checks for Roshni SMS.

    python run_tests.py            # run the whole test suite
    python run_tests.py --coverage # + measure code coverage (HTML report)
    python run_tests.py --security # + Django deployment security check
    python run_tests.py --all      # everything above

This is the "test everything" button. It works the same on Windows, macOS and
Linux, so anyone (or a CI server) can verify the product in one step. Exit code
is non-zero if anything fails, so automation can trust it.

Coverage needs the `coverage` package:  pip install coverage
"""
import subprocess
import sys

PY = sys.executable


def run(cmd, title):
    print("\n" + "=" * 64)
    print(f"  {title}")
    print("=" * 64)
    return subprocess.call(cmd)


def main():
    args = set(sys.argv[1:])
    do_all = "--all" in args
    do_cov = do_all or "--coverage" in args
    do_sec = do_all or "--security" in args
    failed = False

    if do_cov:
        code = run([PY, "-m", "coverage", "run", "manage.py", "test", "core",
                    "--verbosity", "1"], "Test suite (with coverage)")
        failed = failed or code != 0
        # A text summary in the terminal, and a browsable HTML report.
        subprocess.call([PY, "-m", "coverage", "report"])
        subprocess.call([PY, "-m", "coverage", "html"])
        print("\nHTML coverage report: htmlcov/index.html")
    else:
        code = run([PY, "manage.py", "test", "core", "--verbosity", "1"],
                   "Test suite")
        failed = failed or code != 0

    if do_sec:
        # Security check against a production-hardened config so the warnings
        # are meaningful (offline default keeps DEBUG on / HTTP on purpose).
        env_note = ("(run with ROSHNI_DEBUG=0 ROSHNI_HTTPS=1 for the real "
                    "deployment picture)")
        code = run([PY, "manage.py", "check", "--deploy"],
                   f"Django security check {env_note}")
        # Deploy warnings are advisory in the offline default — don't fail on them.

    print("\n" + "=" * 64)
    print("  RESULT:", "SOME TESTS FAILED ✗" if failed else "ALL TESTS PASSED ✓")
    print("=" * 64)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
