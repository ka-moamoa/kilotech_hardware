import asyncio
import time

import pytest

from kilotech_common.protocol import JobSpec, JobState, WorkerInfo
from kilotech_gateway.queue import LeaseLost, MemoryQueue, QueueFull


def worker(name="w1", tasks=("generate",), models=("m1",), **labels):
    return WorkerInfo(worker_id=name, tasks=list(tasks), models=list(models), labels=labels)


def run(coro):
    return asyncio.run(coro)


def test_claim_only_matching_model_and_task():
    async def main():
        q = MemoryQueue()
        a = await q.submit(JobSpec(model="m1"))
        b = await q.submit(JobSpec(model="m2"))
        await q.submit(JobSpec(task="other", model="m2"))
        got = await q.claim(worker(models=["m2"]), 0)
        assert got.id == b.id and got.state == JobState.LEASED and got.attempt == 1
        assert await q.claim(worker(models=["m2"]), 0) is None
        assert (await q.claim(worker(models=["m1"]), 0)).id == a.id

    run(main())


def test_any_model_job_and_fifo_then_priority():
    async def main():
        q = MemoryQueue()
        first = await q.submit(JobSpec())
        second = await q.submit(JobSpec(model="m1"))
        urgent = await q.submit(JobSpec(priority=5))
        w = worker()
        assert [(await q.claim(w, 0)).id for _ in range(3)] == [urgent.id, first.id, second.id]

    run(main())


def test_requirements_select_workers_by_label():
    async def main():
        q = MemoryQueue()
        await q.submit(JobSpec(requirements={"accel": "nvidia"}))
        assert await q.claim(worker(accel="cpu"), 0) is None
        assert await q.claim(worker(accel="nvidia"), 0) is not None

    run(main())


def test_long_poll_wakes_on_submit():
    async def main():
        q = MemoryQueue()
        claim = asyncio.create_task(q.claim(worker(), 5))
        await asyncio.sleep(0.05)
        job = await q.submit(JobSpec())
        started = time.monotonic()
        got = await claim
        assert got.id == job.id and time.monotonic() - started < 1

    run(main())


def test_long_poll_times_out():
    async def main():
        q = MemoryQueue()
        started = time.monotonic()
        assert await q.claim(worker(), 0.1) is None
        assert 0.09 < time.monotonic() - started < 1

    run(main())


def test_expired_lease_is_requeued_then_fails_after_max_attempts():
    async def main():
        q = MemoryQueue(lease_s=0.01, max_attempts=2)
        job = await q.submit(JobSpec())
        first = await q.claim(worker("a"), 0)
        await asyncio.sleep(0.02)
        await q.reap()
        assert (await q.get(job.id)).state == JobState.QUEUED
        with pytest.raises(LeaseLost):  # the stale worker can no longer report
            await q.complete(job.id, first.lease_id, {}, {})
        second = await q.claim(worker("b"), 0)
        assert second.attempt == 2 and second.worker_id == "b"
        await asyncio.sleep(0.02)
        await q.reap()
        final = await q.get(job.id)
        assert final.state == JobState.FAILED and "lease expired" in final.error

    run(main())


def test_fail_retryable_requeues_and_permanent_fails():
    async def main():
        q = MemoryQueue()
        job = await q.submit(JobSpec())
        leased = await q.claim(worker(), 0)
        await q.fail(job.id, leased.lease_id, "flaky", True, {})
        assert (await q.get(job.id)).state == JobState.QUEUED
        leased = await q.claim(worker(), 0)
        await q.fail(job.id, leased.lease_id, "bad input", False, {})
        assert (await q.get(job.id)).state == JobState.FAILED

    run(main())


def test_release_worker_requeues_its_jobs():
    async def main():
        q = MemoryQueue()
        job = await q.submit(JobSpec())
        await q.claim(worker("gone"), 0)
        assert await q.release_worker("gone") == 1
        assert (again := await q.claim(worker("other"), 0)).id == job.id and again.attempt == 2
        assert await q.release_worker("other", count_attempt=False) == 1
        assert (await q.claim(worker("third"), 0)).attempt == 2  # refunded

    run(main())


def test_cancel_queued_and_leased():
    async def main():
        q = MemoryQueue()
        queued = await q.submit(JobSpec())
        await q.cancel(queued.id)
        assert await q.claim(worker(), 0) is None

        running = await q.submit(JobSpec())
        leased = await q.claim(worker(), 0)
        await q.cancel(running.id)
        with pytest.raises(LeaseLost):
            await q.heartbeat(running.id, leased.lease_id)
        assert (await q.stats())["queued"] == 0

    run(main())


def test_queue_full_and_wait():
    async def main():
        q = MemoryQueue(max_queued=1)
        job = await q.submit(JobSpec())
        with pytest.raises(QueueFull):
            await q.submit(JobSpec())
        leased = await q.claim(worker(), 0)
        waiter = asyncio.create_task(q.wait(job.id, 5))
        await q.complete(job.id, leased.lease_id, {"response": "hi"}, {"run_s": 1})
        done = await waiter
        assert done.state == JobState.SUCCEEDED and done.output == {"response": "hi"}
        assert (await q.wait(job.id, 0)).state == JobState.SUCCEEDED

    run(main())


def test_finished_jobs_are_garbage_collected():
    async def main():
        q = MemoryQueue(result_ttl_s=0)
        job = await q.submit(JobSpec())
        await q.cancel(job.id)
        await asyncio.sleep(0.01)
        await q.reap()
        assert await q.get(job.id) is None

    run(main())
