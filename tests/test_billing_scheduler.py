"""Tests for the in-process billing job scheduler.

run_due_jobs() is deliberately pure bookkeeping plus the job calls, so the
interval logic is driven here with a fake clock - no thread, no sleeping, no
real jobs.
"""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import sys
import pathlib
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import unittest
from unittest.mock import patch

from app.services import billing_scheduler_service as scheduler


class TestRunDueJobs(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def _make(name, exit_code=0, boom=False):
            def _job():
                self.calls.append(name)
                if boom:
                    raise RuntimeError(f"{name} exploded")
                return exit_code
            return _job

        self._make = _make

    def _jobs(self, *specs):
        """specs: (name, interval, exit_code, boom)"""
        return tuple(
            (name, self._make(name, exit_code, boom), interval)
            for name, interval, exit_code, boom in specs
        )

    def test_every_job_runs_on_the_first_tick(self):
        jobs = self._jobs(("a", 100, 0, False), ("b", 900, 0, False))
        with patch.object(scheduler, "JOBS", jobs):
            last_run = scheduler.run_due_jobs(1000.0, {})

        self.assertEqual(self.calls, ["a", "b"])
        self.assertEqual(last_run, {"a": 1000.0, "b": 1000.0})

    def test_a_job_does_not_rerun_before_its_interval_elapses(self):
        jobs = self._jobs(("a", 100, 0, False))
        with patch.object(scheduler, "JOBS", jobs):
            last_run = scheduler.run_due_jobs(1000.0, {})
            last_run = scheduler.run_due_jobs(1099.0, last_run)

        self.assertEqual(self.calls, ["a"])
        self.assertEqual(last_run, {"a": 1000.0})

    def test_a_job_reruns_once_its_interval_has_elapsed(self):
        jobs = self._jobs(("a", 100, 0, False))
        with patch.object(scheduler, "JOBS", jobs):
            last_run = scheduler.run_due_jobs(1000.0, {})
            last_run = scheduler.run_due_jobs(1100.0, last_run)

        self.assertEqual(self.calls, ["a", "a"])
        self.assertEqual(last_run, {"a": 1100.0})

    def test_jobs_run_on_independent_schedules(self):
        """The 15-minute reconcile must not drag slower sweeps along with it."""
        jobs = self._jobs(("fast", 100, 0, False), ("slow", 10_000, 0, False))
        with patch.object(scheduler, "JOBS", jobs):
            last_run = scheduler.run_due_jobs(0.0, {})
            self.calls.clear()
            scheduler.run_due_jobs(500.0, last_run)

        self.assertEqual(self.calls, ["fast"])

    def test_a_failing_job_does_not_block_the_others(self):
        jobs = self._jobs(("boom", 100, 0, True), ("after", 100, 0, False))
        with patch.object(scheduler, "JOBS", jobs):
            last_run = scheduler.run_due_jobs(1000.0, {})

        self.assertEqual(self.calls, ["boom", "after"])
        # A crashed job is still marked as attempted, so one broken job cannot
        # be retried on every single tick.
        self.assertEqual(last_run, {"boom": 1000.0, "after": 1000.0})

    def test_a_nonzero_exit_code_is_recorded_not_raised(self):
        jobs = self._jobs(("a", 100, 3, False))
        with patch.object(scheduler, "JOBS", jobs):
            last_run = scheduler.run_due_jobs(1000.0, {})

        self.assertEqual(self.calls, ["a"])
        self.assertEqual(last_run, {"a": 1000.0})

    def test_interval_is_overridable_by_env(self):
        jobs = self._jobs(("a", 100, 0, False))
        with patch.object(scheduler, "JOBS", jobs), \
                patch.dict(os.environ, {"BILLING_SCHEDULER_A_SECONDS": "10"}):
            last_run = scheduler.run_due_jobs(1000.0, {})
            scheduler.run_due_jobs(1050.0, last_run)

        self.assertEqual(self.calls, ["a", "a"])

    def test_a_nonsense_interval_falls_back_to_the_default(self):
        """A zero or negative interval would busy-loop the job on every tick."""
        jobs = self._jobs(("a", 100, 0, False))
        for bad in ("0", "-5", "not-a-number"):
            self.calls.clear()
            with patch.object(scheduler, "JOBS", jobs), \
                    patch.dict(os.environ, {"BILLING_SCHEDULER_A_SECONDS": bad}):
                last_run = scheduler.run_due_jobs(1000.0, {})
                scheduler.run_due_jobs(1050.0, last_run)

            self.assertEqual(self.calls, ["a"], f"interval {bad!r} should fall back")


class TestRealJobWiring(unittest.TestCase):
    def test_the_billing_jobs_are_registered(self):
        """The whole point of this module - the first three had never run.

        Pinned as an exact list so a job cannot be dropped by accident. The
        provider-balance check joined them because one shared USD key funds
        every pooled tenant, and nothing else notices when it empties.
        """
        names = [name for name, _, _ in scheduler.JOBS]
        self.assertEqual(
            names,
            [
                "reconcile_subscription_orders",
                "process_subscription_lifecycle",
                "generate_billing_notifications",
                "check_ai_provider_balance",
            ],
        )

    def test_each_registered_job_resolves_to_a_real_main(self):
        """Deferred imports mean a typo would only surface at runtime."""
        from app.jobs.reconcile_subscription_orders import main as reconcile_main
        from app.jobs.process_subscription_lifecycle import main as lifecycle_main
        from app.jobs.generate_billing_notifications import main as notifications_main
        from app.jobs.check_ai_provider_balance import main as balance_main

        for job_main in (reconcile_main, lifecycle_main, notifications_main, balance_main):
            self.assertTrue(callable(job_main))

    def test_default_job_cadences_are_independent(self):
        intervals = {name: interval for name, _, interval in scheduler.JOBS}

        self.assertEqual(intervals["reconcile_subscription_orders"], 15 * 60)
        self.assertEqual(intervals["process_subscription_lifecycle"], 10 * 60)
        self.assertEqual(intervals["generate_billing_notifications"], 24 * 60 * 60)

    def test_lifecycle_interval_override_still_uses_existing_env_var(self):
        jobs = (
            ("process_subscription_lifecycle", lambda: 0, scheduler.LIFECYCLE_INTERVAL_SECONDS),
        )
        with patch.object(scheduler, "JOBS", jobs), patch.dict(
            os.environ,
            {"BILLING_SCHEDULER_PROCESS_SUBSCRIPTION_LIFECYCLE_SECONDS": "5"},
        ):
            last_run = scheduler.run_due_jobs(1000.0, {})
            last_run = scheduler.run_due_jobs(1004.0, last_run)
            rerun = scheduler.run_due_jobs(1005.0, last_run)

        self.assertEqual(rerun["process_subscription_lifecycle"], 1005.0)

    def test_render_blueprint_does_not_define_subscription_lifecycle_cron(self):
        render_yaml = (_REPO_ROOT / "render.yaml").read_text(encoding="utf-8")

        self.assertNotIn("type: cron", render_yaml)
        self.assertNotIn("python -m app.jobs.process_subscription_lifecycle", render_yaml)


if __name__ == "__main__":
    unittest.main()
