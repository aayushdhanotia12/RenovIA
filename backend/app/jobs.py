"""Background jobs with numbered progress events.

Anything slower than a couple of seconds (detection, suggestions, rendering) runs as
a job. The customer's page subscribes to its events over Server-Sent Events; every
event carries a sequence number, so a page that reconnects resumes from the last one
it saw and never replays work it already showed.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from .store import Store

Progress = Callable[..., None]


class JobHub:
    def __init__(self, store: Store) -> None:
        self.store = store
        self._events: dict[str, list[dict]] = {}
        self._conds: dict[str, asyncio.Condition] = {}
        self._tasks: set[asyncio.Task] = set()

    def start(self, owner: str, pid: str, kind: str, work: Callable[[Progress], Any]) -> str:
        """Run `work(progress)` in a worker thread; returns the job id immediately."""
        jid = self.store.create_job(owner, pid, kind)
        self._events[jid] = []
        self._conds[jid] = asyncio.Condition()
        loop = asyncio.get_running_loop()

        def progress(stage: str, status: str = "running", detail: str | None = None, percent: int | None = None) -> None:
            asyncio.run_coroutine_threadsafe(self._emit(jid, stage, status, detail, percent), loop).result(timeout=10)

        async def runner() -> None:
            try:
                result = await asyncio.to_thread(work, progress)
                self.store.finish_job(jid, "done", result=result)
                await self._emit(jid, "JOB", "done", None, 100, result)
            except Exception as e:  # the customer sees a recovery message, never a stack trace
                message = str(e) or e.__class__.__name__
                self.store.finish_job(jid, "failed", error=message)
                await self._emit(jid, "JOB", "failed", message, None)

        task = asyncio.create_task(runner())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return jid

    async def _emit(self, jid: str, stage: str, status: str, detail: str | None, percent: int | None,
                    result: Any = None) -> None:
        cond = self._conds[jid]
        async with cond:
            event = {"seq": len(self._events[jid]) + 1, "stage": stage, "status": status, "detail": detail,
                     "percent": percent, "at": time.time()}
            if result is not None:
                event["result"] = result
            self._events[jid].append(event)
            cond.notify_all()

    async def stream(self, owner: str, jid: str, after_seq: int = 0) -> AsyncIterator[dict]:
        job = self.store.job(owner, jid)  # ownership check
        if jid not in self._conds:  # finished before a restart: report the stored outcome
            yield {"seq": after_seq + 1, "stage": "JOB", "status": job["status"], "detail": job.get("error"),
                   "percent": 100 if job["status"] == "done" else None, "result": job.get("result")}
            return
        cond, seen = self._conds[jid], after_seq
        while True:
            async with cond:
                while len(self._events[jid]) <= seen:
                    await cond.wait()
                fresh = self._events[jid][seen:]
            for event in fresh:
                seen = event["seq"]
                yield event
                if event["stage"] == "JOB":
                    return

    def events(self, jid: str) -> list[dict]:
        return list(self._events.get(jid, []))
