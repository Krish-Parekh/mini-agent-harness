from __future__ import annotations

from miniagent.policy import CommandPolicy, PolicyClassifier


class ScriptedLLM:
    def __init__(self, responses: list[CommandPolicy | Exception]) -> None:
        self._responses = responses
        self.calls: list[list[dict]] = []
        self.response_models: list[type] = []

    def complete_structured(self, messages, response_model):
        self.calls.append(messages)
        self.response_models.append(response_model)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_policy_classifier_uses_structured_bash_output():
    llm = ScriptedLLM(
        [
            CommandPolicy(
                risk="safe",
                read_only=True,
                is_verification=True,
                reason="pytest only reads and verifies",
            )
        ]
    )
    classifier = PolicyClassifier(llm)  # type: ignore[arg-type]

    policy = classifier.classify_bash("python -m pytest -q")

    assert policy.read_only
    assert policy.is_verification
    assert llm.response_models == [CommandPolicy]
    assert "Return a structured response" in llm.calls[0][0]["content"]


def test_policy_classifier_fails_closed_on_structured_failure():
    classifier = PolicyClassifier(ScriptedLLM([ValueError("bad schema")]))  # type: ignore[arg-type]

    policy = classifier.classify_bash("rm -rf .")

    assert policy.risk == "unknown"
    assert not policy.read_only
    assert "failed closed" in policy.reason


def test_finish_policy_fallback_requires_real_verification_unavailable_reason():
    classifier = PolicyClassifier(ScriptedLLM([ValueError("bad schema")]))  # type: ignore[arg-type]

    policy = classifier.classify_finish_message("done")

    assert policy.risk == "safe"
    assert policy.read_only
    assert not policy.verification_unavailable
