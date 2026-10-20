import inspect

from support import load, stub

stub(
    "logfire",
    "src",
    "src.config",
    "src.db",
    "src.db.models",
    "src.db.session",
    "src.services",
    "src.services.graph",
    "src.services.graph.prompts",
    "src.services.history",
    "src.services.history.repository",
    "src.services.llm",
)
titles = load("titles", "src/services/history/titles.py")

if titles.TITLE_MAX_CHARS != 60:
    raise SystemExit(f"TITLE_MAX_CHARS is {titles.TITLE_MAX_CHARS}, expected 60")
cleaned = titles.clean_title('  "Deploying Kubernetes."  ')
if cleaned != "Deploying Kubernetes":
    raise SystemExit(f"clean_title returned {cleaned!r}")
if len(titles.clean_title("x" * 100)) != 60:
    raise SystemExit("clean_title does not cap at 60 characters")
if "clean_title(" not in inspect.getsource(titles.generate_title):
    raise SystemExit("generate_title does not use clean_title")
