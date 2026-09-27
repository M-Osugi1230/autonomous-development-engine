from datetime import UTC, datetime, timedelta
import unittest

from ade.execution_lease import ExecutionLease, acquire_lease, renew_lease, release_lease


class ExecutionLeaseTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 27, 3, 0, tzinfo=UTC)

    def test_duplicate_owner_is_idempotent(self):
        lease = acquire_lease(task_id="t1", owner_id="run-1", now=self.now, ttl=timedelta(minutes=10))
        self.assertEqual(acquire_lease(task_id="t1", owner_id="run-1", now=self.now + timedelta(seconds=1), ttl=timedelta(minutes=10), current=lease), lease)

    def test_live_lease_blocks_second_owner(self):
        lease = acquire_lease(task_id="t1", owner_id="run-1", now=self.now, ttl=timedelta(minutes=10))
        with self.assertRaises(RuntimeError):
            acquire_lease(task_id="t1", owner_id="run-2", now=self.now + timedelta(minutes=1), ttl=timedelta(minutes=10), current=lease)

    def test_expired_lease_is_reclaimed_with_next_attempt(self):
        lease = acquire_lease(task_id="t1", owner_id="run-1", now=self.now, ttl=timedelta(minutes=10))
        reclaimed = acquire_lease(task_id="t1", owner_id="run-2", now=self.now + timedelta(minutes=10), ttl=timedelta(minutes=5), current=lease)
        self.assertEqual(reclaimed.attempt, 2)
        self.assertEqual(reclaimed.owner_id, "run-2")

    def test_next_task_replaces_previous_global_lease(self):\n        lease = acquire_lease(task_id="t1", owner_id="run-1", now=self.now, ttl=timedelta(minutes=10))\n        next_lease = acquire_lease(task_id="t2", owner_id="run-2", now=self.now + timedelta(minutes=1), ttl=timedelta(minutes=10), current=lease)\n        self.assertEqual((next_lease.task_id, next_lease.owner_id, next_lease.attempt), ("t2", "run-2", 1))\n\n    def test_stale_owner_cannot_renew_or_release(self):
        lease = acquire_lease(task_id="t1", owner_id="run-1", now=self.now, ttl=timedelta(minutes=10))
        with self.assertRaises(RuntimeError): renew_lease(lease, owner_id="run-2", now=self.now + timedelta(minutes=1), ttl=timedelta(minutes=10))
        with self.assertRaises(RuntimeError): release_lease(lease, owner_id="run-2")

    def test_expired_lease_cannot_be_renewed(self):
        lease = acquire_lease(task_id="t1", owner_id="run-1", now=self.now, ttl=timedelta(minutes=10))
        with self.assertRaises(RuntimeError): renew_lease(lease, owner_id="run-1", now=self.now + timedelta(minutes=10), ttl=timedelta(minutes=10))


if __name__ == "__main__": unittest.main()
