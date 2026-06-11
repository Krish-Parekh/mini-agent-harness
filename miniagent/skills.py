from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from miniagent.text import clip

_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")

_MAX_DESCRIPTION = 200


class SkillRef(NamedTuple):
    name: str
    description: str
    scope: str 
    repo: str | None = None  

class SkillLibrary:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    def index(self, repo: str | None) -> list[SkillRef]:
        """The repo's skills plus all global ones, as (name, description)."""
        refs: list[SkillRef] = []
        for scope, directory in self._scope_dirs(repo):
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.md")):
                ref_repo = repo if scope == "repo" else None
                refs.append(SkillRef(path.stem, _description_of(path), scope, ref_repo))
        return refs

    def all_skills(self) -> list[SkillRef]:
        """Every skill in the library, across all repos plus global."""
        refs: list[SkillRef] = []
        repos_dir = self._root / "repos"
        if repos_dir.is_dir():
            for path in sorted(repos_dir.glob("*/*/*.md")):
                repo = f"{path.parent.parent.name}/{path.parent.name}"
                refs.append(SkillRef(path.stem, _description_of(path), "repo", repo))
        global_dir = self._root / "global"
        if global_dir.is_dir():
            for path in sorted(global_dir.glob("*.md")):
                refs.append(SkillRef(path.stem, _description_of(path), "global"))
        return refs

    def read(self, name: str, repo: str | None) -> str | None:
        if not _SLUG_RE.fullmatch(name):
            return None
        for _, directory in self._scope_dirs(repo):
            path = directory / f"{name}.md"
            if path.is_file():
                return path.read_text(encoding="utf-8")
        return None

    def write(
        self, *, name: str, description: str, body: str, scope: str, repo: str | None
    ) -> Path:
        slug = self.slugify(name)
        description = clip(" ".join(description.split()), _MAX_DESCRIPTION)
        path = next(
            (
                d / f"{slug}.md"
                for _, d in self._scope_dirs(repo)
                if (d / f"{slug}.md").is_file()
            ),
            None,
        )
        if path is None:
            effective = "repo" if scope == "repo" and repo else "global"
            path = self._dir_for(effective, repo) / f"{slug}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        content = f"---\nname: {slug}\ndescription: {description}\n---\n\n{body.strip()}\n"
        path.write_text(content, encoding="utf-8")
        return path

    @staticmethod
    def slugify(name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64].rstrip("-")
        if not _SLUG_RE.fullmatch(slug):
            raise ValueError(f"cannot derive a skill slug from {name!r}")
        return slug

    def _scope_dirs(self, repo: str | None) -> list[tuple[str, Path]]:
        """Candidate (scope, dir) pairs in lookup order: repo first, then global."""
        dirs: list[tuple[str, Path]] = []
        if repo:
            dirs.append(("repo", self._dir_for("repo", repo)))
        dirs.append(("global", self._dir_for("global", None)))
        return dirs

    def _dir_for(self, scope: str, repo: str | None) -> Path:
        if scope == "repo":
            if not repo:
                raise ValueError("repo scope requires a repo")
            owner, _, name = repo.partition("/")
            return self._root / "repos" / owner / name
        return self._root / "global"


def _description_of(path: Path) -> str:
    """Pull `description:` out of the frontmatter; tolerate files we didn't write."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("description:"):
            return line.removeprefix("description:").strip()
    return ""
