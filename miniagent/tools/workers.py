from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from miniagent.tracing import bind_context

if TYPE_CHECKING:
    from miniagent.tools.worker import Worker

MAX_WORKERS = 10


class WorkerPool:
    """Background workers of one conversation. A worker that ends lands in the
    inbox; the parent delivers it between its own steps, never mid-step."""

    def __init__(self) -> None:
        self._changed = threading.Condition()
        self._live: dict[str, Worker] = {}
        self._inbox: list[Worker] = []
        self.git_lock = threading.Lock()
        self.on_inbox: Callable[[], None] = lambda: None

    def live(self) -> int:
        with self._changed:
            return len(self._live)

    def live_ids(self) -> set[str]:
        with self._changed:
            return set(self._live)

    def is_live(self, worker_id: str) -> bool:
        with self._changed:
            return worker_id in self._live

    def reserve(self, count: int) -> None:
        with self._changed:
            if len(self._live) + count > MAX_WORKERS:
                raise ValueError(
                    f"At most {MAX_WORKERS} workers can run at once; "
                    f"{len(self._live)} are running. Wait for some to finish."
                )

    def start(self, worker: Worker, run: Callable[[], None]) -> None:
        with self._changed:
            self._live[worker.state.worker_id] = worker
        threading.Thread(
            target=bind_context(self._run),
            args=(worker, run),
            name=f"worker-{worker.state.worker_id}",
            daemon=True,
        ).start()

    def _run(self, worker: Worker, run: Callable[[], None]) -> None:
        try:
            run()
        finally:
            with self._changed:
                self._live.pop(worker.state.worker_id, None)
                self._inbox.append(worker)
                self._changed.notify_all()
            self.on_inbox()

    def has_results(self) -> bool:
        with self._changed:
            return bool(self._inbox)

    def take(self) -> list[Worker]:
        with self._changed:
            taken, self._inbox = self._inbox, []
            return taken

    def cancel_all(self) -> None:
        with self._changed:
            live = list(self._live.values())
        for worker in live:
            worker.conversation.request_cancel()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until a result is waiting; False once nothing is running and
        nothing is waiting, or on timeout."""
        with self._changed:
            self._changed.wait_for(lambda: self._inbox or not self._live, timeout)
            return bool(self._inbox)
