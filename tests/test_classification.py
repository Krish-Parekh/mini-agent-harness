from __future__ import annotations

from miniagent.classification import TaskClassifier, TaskRoute, TaskRouteDecision


class ScriptedLLM:
    def __init__(self, responses: list[TaskRouteDecision | Exception]) -> None:
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


def test_task_classifier_uses_structured_route_output():
    llm = ScriptedLLM(
        [TaskRouteDecision(route="code_edit", reason="user asked for edits")]
    )
    classifier = TaskClassifier(llm)  # type: ignore[arg-type]

    route = classifier.classify_task_route("make the router use an llm")

    assert route == TaskRoute.CODE_EDIT
    assert "Return a structured response" in llm.calls[0][0]["content"]
    assert llm.response_models == [TaskRouteDecision]


def test_task_classifier_accepts_review_route():
    llm = ScriptedLLM([TaskRouteDecision(route="review", reason="audit")])
    classifier = TaskClassifier(llm)  # type: ignore[arg-type]

    assert classifier.classify_task_route("audit this") == TaskRoute.REVIEW


def test_task_classifier_falls_back_to_default_on_structured_failure():
    llm = ScriptedLLM([ValueError("invalid structured output")])
    classifier = TaskClassifier(llm)  # type: ignore[arg-type]

    assert classifier.classify_task_route("plan this") == TaskRoute.DEFAULT


def test_task_classifier_caches_by_request_text():
    llm = ScriptedLLM([TaskRouteDecision(route="question", reason="asks why")])
    classifier = TaskClassifier(llm)  # type: ignore[arg-type]

    assert classifier.classify_task_route("why?") == TaskRoute.QUESTION
    assert classifier.classify_task_route("why?") == TaskRoute.QUESTION
    assert len(llm.calls) == 1
