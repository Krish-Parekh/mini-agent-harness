from __future__ import annotations

import argparse
import sys

from miniagent.config import Settings, export_provider_keys
from miniagent.confirm import ConfirmPolicy
from miniagent.conversation import Conversation, Status
from miniagent.events import ActionEvent, Event, MessageEvent
from miniagent.factory import build_agent
from miniagent.sandbox.local import LocalSandbox


def _print_step(event: Event) -> None:
    if isinstance(event, ActionEvent):
        print(f"→ {event.tool_name} {event.arguments}", file=sys.stderr)


def _final_answer(events: list[Event]) -> str:
    for event in reversed(events):
        if isinstance(event, ActionEvent) and event.tool_name == "finish":
            return event.arguments.get("message", "")
        if isinstance(event, MessageEvent) and event.role == "assistant" and event.text.strip():
            return event.text
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="mini-agent", description="Run one task headless on a local workspace."
    )
    parser.add_argument("task")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--model")
    parser.add_argument("--max-iterations", type=int)
    args = parser.parse_args()

    overrides = {"model": args.model, "max_iterations": args.max_iterations}
    settings = Settings(**{k: v for k, v in overrides.items() if v is not None})
    export_provider_keys(settings)
    conversation = Conversation(
        agent=build_agent(settings, preset="headless"),
        sandbox=LocalSandbox(args.workspace),
        on_event=_print_step,
        max_iterations=settings.max_iterations,
        confirm_policy=ConfirmPolicy("never"),
    )
    conversation.send_message(args.task)
    try:
        conversation.run()
    finally:
        conversation.agent.close()
    print(_final_answer(conversation.events))
    return 0 if conversation.status == Status.FINISHED else 1


if __name__ == "__main__":
    raise SystemExit(main())
