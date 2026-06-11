from __future__ import annotations

import json
from datetime import datetime

from backend.schemas.conversation import ConversationInfo


def test_conversation_info_serializes_naive_timestamps_as_utc():
    info = ConversationInfo(
        id="abc123",
        status="running",
        workspace_dir="/tmp/workspace",
        num_events=0,
        created_at=datetime(2026, 6, 11, 2, 0, 0),
        run_started_at=datetime(2026, 6, 11, 2, 1, 0),
        updated_at=datetime(2026, 6, 11, 2, 2, 0),
    )

    data = json.loads(info.model_dump_json())

    assert data["created_at"] == "2026-06-11T02:00:00+00:00"
    assert data["run_started_at"] == "2026-06-11T02:01:00+00:00"
    assert data["updated_at"] == "2026-06-11T02:02:00+00:00"
