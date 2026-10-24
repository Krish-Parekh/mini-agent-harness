from __future__ import annotations

from deepeval.dataset import EvaluationDataset, Expectations, Golden
from deepeval.test_case import ToolCall

from evals.metrics import JUDGE

SAGE = {"repo": "Sage", "commit": "e4ce315caf173f72e87e62e8c03cf30be8b23ffb"}
HARNESS = {"repo": "mini-agent-harness", "commit": "cf064b3f2d90a97762d291f4b43f240e09b70afb"}
READ_ONLY = "Modify, create or delete files in the repository"
READ_TOOLS = [ToolCall(name="terminal"), ToolCall(name="finish")]
EDIT_TOOLS = [ToolCall(name="file_edit"), ToolCall(name="terminal"), ToolCall(name="finish")]


def _expect(must: list[str], must_not: list[str]) -> Expectations:
    return Expectations(must=must, must_not=must_not, model=JUDGE)


AGENT_GOLDENS = [
    Golden(
        name="q-sage-overview",
        input="What is this repository all about?",
        expectations=_expect(
            [
                "Describe Sage as a retrieval-augmented generation (RAG) system for enterprise IT questions",
                "Mention that it runs as a LangGraph state machine behind a FastAPI service",
                "Mention the Next.js chat frontend",
            ],
            [READ_ONLY],
        ),
        additional_metadata={**SAGE, "kind": "question"},
        expected_tools=READ_TOOLS,
    ),
    Golden(
        name="q-sage-answers",
        input="What questions does this project help me answer?",
        expectations=_expect(
            [
                "Say it answers enterprise IT questions and name at least one topic area, such as Kubernetes, Intel hardware or enterprise networking",
            ],
            [READ_ONLY],
        ),
        additional_metadata={**SAGE, "kind": "question"},
        expected_tools=READ_TOOLS,
    ),
    Golden(
        name="q-sage-guardrails-files",
        input="For guarding, what are they using? Find me the files involved.",
        expectations=_expect(
            [
                "Identify NeMo Guardrails as what the project uses for guarding",
                "Point to src/services/guardrails/guardrails.py",
                "Point to the rails configuration under src/services/guardrails/config/",
            ],
            [READ_ONLY],
        ),
        additional_metadata={**SAGE, "kind": "question"},
        expected_tools=READ_TOOLS,
    ),
    Golden(
        name="q-sage-secrets",
        input="Are there any hardcoded secrets in this codebase? Tell me where.",
        expectations=_expect(
            [
                "Say that no hardcoded secret values were found in the source code",
                "Explain that API keys and credentials are read from environment variables, for example in src/config.py",
            ],
            [
                "Present a non-secret value, such as a package-lock integrity hash or an environment variable name, as a leaked secret",
                READ_ONLY,
            ],
        ),
        additional_metadata={**SAGE, "kind": "question"},
        expected_tools=READ_TOOLS,
    ),
    Golden(
        name="q-sage-tanstack",
        input="Does the frontend need any TanStack optimizations we should learn about?",
        expectations=_expect(
            [
                "Recognise that the frontend already uses TanStack Query (@tanstack/react-query) and TanStack DB (@tanstack/react-db)",
                "Ground its suggestions in specific frontend files, such as frontend/src/lib/db/conversations.ts or the hooks in frontend/src/lib/api/hooks/",
            ],
            [
                "Recommend adopting TanStack Query as if the frontend did not already use it",
                READ_ONLY,
            ],
        ),
        additional_metadata={**SAGE, "kind": "question"},
        expected_tools=READ_TOOLS,
    ),
    Golden(
        name="q-sage-summary-table",
        input=(
            "Do not modify any files. Read the README and two core source files, run one terminal command "
            "counting lines per language, then write a detailed markdown summary with a table and two "
            "fenced code snippets."
        ),
        expectations=_expect(
            [
                "Include a markdown table",
                "Include at least two fenced code snippets taken from the repository's source files",
                "Report lines of code per language from a command it actually ran",
            ],
            [READ_ONLY],
        ),
        additional_metadata={**SAGE, "kind": "question"},
        expected_tools=READ_TOOLS,
    ),
    Golden(
        name="q-harness-bullets",
        input="In 3 bullet points, what does this repo do? Read-only: don't change any files.",
        expectations=_expect(
            [
                "Answer in exactly three bullet points",
                "Describe the project as a coding agent that works on users' GitHub repositories",
            ],
            [READ_ONLY],
        ),
        additional_metadata={**HARNESS, "kind": "question"},
        expected_tools=READ_TOOLS,
    ),
    Golden(
        name="r-sage-bad-practices",
        input="What are some bad practices in our codebase? Don't change anything, just list them with file references.",
        expectations=_expect(
            ["List concrete bad practices found in the code", "Give a file path for each bad practice"],
            [READ_ONLY],
        ),
        additional_metadata={**SAGE, "kind": "review"},
        expected_tools=READ_TOOLS,
    ),
    Golden(
        name="r-sage-frontend",
        input="What is wrong in our frontend codebase? Review it and report the most important issues.",
        expectations=_expect(
            ["Report concrete issues in the frontend code", "Give a file path under frontend/ for each issue"],
            [READ_ONLY],
        ),
        additional_metadata={**SAGE, "kind": "review"},
        expected_tools=READ_TOOLS,
    ),
    Golden(
        name="e-sage-chunker-overlap",
        input=(
            "Chunker in src/services/ingestion/chunking/chunker.py accepts an overlap that is as large as or "
            "larger than chunk_size. Make it raise a ValueError in that case."
        ),
        expectations=_expect(
            [
                "Make Chunker raise a ValueError when overlap is greater than or equal to chunk_size",
                "Tell the user what changed",
            ],
            ["Modify files unrelated to the chunker, apart from adding tests"],
        ),
        additional_metadata={**SAGE, "kind": "code_edit", "check": "chunker_overlap.py"},
        expected_tools=EDIT_TOOLS,
    ),
    Golden(
        name="e-sage-title-cleanup",
        input=(
            "In src/services/history/titles.py, pull the title cleanup at the end of generate_title into a pure "
            "function clean_title(raw: str) -> str, cap titles with a module constant TITLE_MAX_CHARS = 60 "
            "instead of the hardcoded 80, and have generate_title use clean_title."
        ),
        expectations=_expect(
            [
                "Add a clean_title(raw: str) -> str function and a TITLE_MAX_CHARS = 60 constant in src/services/history/titles.py",
                "Make generate_title use clean_title",
            ],
            ["Modify files unrelated to title generation, apart from adding tests"],
        ),
        additional_metadata={**SAGE, "kind": "code_edit", "check": "title_cleanup.py"},
        expected_tools=EDIT_TOOLS,
    ),
    Golden(
        name="e-sage-text-encoding",
        input=(
            "The text loader crashes on files that are not valid UTF-8. Make it read files as UTF-8 and replace "
            "undecodable bytes instead of failing."
        ),
        expectations=_expect(
            ["Change the text loader's code so it opens files as UTF-8 and replaces undecodable bytes instead of raising"],
            ["Modify files unrelated to the text loader, apart from adding tests"],
        ),
        additional_metadata={**SAGE, "kind": "code_edit", "check": "text_encoding.py"},
        expected_tools=EDIT_TOOLS,
    ),
]

agent_dataset = EvaluationDataset(goldens=AGENT_GOLDENS)
