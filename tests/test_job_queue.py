from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support  # noqa: F401
from pixiv_artist_recsys.jobs import JobQueue
from pixiv_artist_recsys.storage import RecommendationRepository, SQLiteDatabase


class JobQueueTests(unittest.TestCase):
    def _queue(self, tmpdir: str, **kwargs) -> JobQueue:
        db = SQLiteDatabase(Path(tmpdir) / 'queue.sqlite3')
        RecommendationRepository(db).initialize()
        return JobQueue(database=db, **kwargs)

    def test_enqueue_claim_complete_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = self._queue(tmpdir)
            job_id = queue.enqueue(kind='hydrate', payload={'artist_id': 42})

            job = queue.claim(worker='w1')
            self.assertIsNotNone(job)
            self.assertEqual(job.job_id, job_id)
            self.assertEqual(job.kind, 'hydrate')
            self.assertEqual(job.payload, {'artist_id': 42})
            self.assertEqual(job.status, 'claimed')
            self.assertEqual(job.attempts, 1)

            # Claimed job is invisible to other workers.
            self.assertIsNone(queue.claim(worker='w2'))

            queue.complete(job_id=job_id, result={'ok': True})
            done = queue.get(job_id=job_id)
            self.assertEqual(done.status, 'done')
            self.assertEqual(done.result, {'ok': True})
            self.assertEqual(queue.counts(), {'done': 1})

    def test_fail_requeues_until_attempts_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = self._queue(tmpdir)
            job_id = queue.enqueue(kind='hydrate', max_attempts=2)

            first = queue.claim(worker='w1')
            queue.fail(job_id=first.job_id, error='boom-1')
            self.assertEqual(queue.get(job_id=job_id).status, 'pending')

            second = queue.claim(worker='w1')
            self.assertEqual(second.attempts, 2)
            queue.fail(job_id=second.job_id, error='boom-2')
            final = queue.get(job_id=job_id)
            self.assertEqual(final.status, 'failed')
            self.assertEqual(final.error, 'boom-2')
            self.assertIsNone(queue.claim(worker='w1'))

    def test_claim_filters_by_kind_and_orders_fifo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = self._queue(tmpdir)
            a = queue.enqueue(kind='hydrate')
            b = queue.enqueue(kind='rank')
            c = queue.enqueue(kind='hydrate')

            job = queue.claim(worker='w1', kinds=('rank',))
            self.assertEqual(job.job_id, b)
            job = queue.claim(worker='w1', kinds=('hydrate',))
            self.assertEqual(job.job_id, a)
            job = queue.claim(worker='w1')
            self.assertEqual(job.job_id, c)

    def test_recover_stale_requeues_timed_out_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            clock = {'now': 1000.0}
            queue = self._queue(tmpdir, now_fn=lambda: clock['now'], claim_timeout_s=600.0)
            job_id = queue.enqueue(kind='hydrate')
            queue.claim(worker='crashed-worker')

            # Before timeout nothing is recovered.
            clock['now'] += 100.0
            self.assertEqual(queue.recover_stale(), 0)

            clock['now'] += 700.0
            self.assertEqual(queue.recover_stale(), 1)
            job = queue.get(job_id=job_id)
            self.assertEqual(job.status, 'pending')
            reclaimed = queue.claim(worker='w2')
            self.assertEqual(reclaimed.job_id, job_id)
            self.assertEqual(reclaimed.attempts, 2)


if __name__ == '__main__':
    unittest.main()
