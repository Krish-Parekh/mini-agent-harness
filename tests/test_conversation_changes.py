from __future__ import annotations

import uuid

from tests.test_persistence import broker, managed, service_for  # noqa: F401


class StatusRepository:
    def __init__(self) -> None:
        self.statuses: list[str] = []

    async def upsert_conversation(self, **kwargs) -> None:
        self.statuses.append(kwargs["status"])


async def test_persisting_a_status_notifies_only_that_users_feed(managed):  # noqa: F811
    repo = StatusRepository()
    service = service_for(repo)
    mine = service.subscribe_changes(managed.user_id)
    other = service.subscribe_changes(uuid.uuid4())

    await service._persist_status(managed)

    assert repo.statuses == ["running"]
    assert mine.get_nowait() == "c1"
    assert other.empty()


async def test_unsubscribed_feeds_stop_receiving(managed):  # noqa: F811
    service = service_for(StatusRepository())
    queue = service.subscribe_changes(managed.user_id)
    service.unsubscribe_changes(managed.user_id, queue)

    await service._persist_status(managed)

    assert queue.empty()
    assert service._change_feeds == {}
