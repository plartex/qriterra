"""Bounded source context and version checks for project reviews."""

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from pathspec import GitIgnoreSpec
from fnmatch import fnmatchcase


_EXCLUDED_DIRS = frozenset({
    ".git", ".runtime", ".venv", "venv", ".agents", ".codex", ".gemini", ".agent-shuttle",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules",
    "build", "dist", ".idea", ".vscode", "target", ".aws", ".ssh", "debug-runs",
})
_PRIVATE_FILES = (".env", ".env.*", "credentials*", "secrets*", "*.pem", "*.key",
                  "*.session.*.json", "*.last-batch.json", "*.recheck.json")
_SOURCE_SUFFIXES = frozenset({
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".go", ".rs",
    ".java", ".kt", ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".sh", ".ps1",
    ".sql", ".yaml", ".yml", ".toml", ".json", ".html", ".css", ".scss", ".xml",
})


class ProjectSnapshotError(RuntimeError):
    """The chosen source inventory could not be verified consistently."""


@dataclass(frozen=True)
class SourceFile:
    path: str
    sha256: str
    size: int
    content: str | None

    def to_dict(self, *, include_source=False):
        data = {"path": self.path, "sha256": self.sha256, "bytes": self.size,
                "embedded": self.content is not None}
        if include_source and self.content is not None:
            data["source_lines"] = self.content.splitlines()
        return data


@dataclass(frozen=True)
class ProjectSnapshot:
    files: tuple[SourceFile, ...]
    limitations: tuple[str, ...]
    discovery_mode: str = "filesystem"

    def to_dict(self, *, include_source=False):
        return {"files": [file.to_dict(include_source=include_source) for file in self.files],
                "limitations": list(self.limitations),
                "discovery_mode": self.discovery_mode,
                "excluded_directories": sorted(_EXCLUDED_DIRS)}

    def changes(self, root):
        current = capture_project(root, inline_bytes=0, discovery_mode=self.discovery_mode)
        before = {file.path: file.sha256 for file in self.files}
        after = {file.path: file.sha256 for file in current.files}
        return sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))


def _paths(root, discovery_mode=None):
    if discovery_mode != "filesystem":
        try:
            result = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=True,
            )
            paths = [Path(os.fsdecode(raw)) for raw in result.stdout.split(b"\0") if raw]
            return sorted(set(paths), key=lambda path: path.as_posix()), "git"
        except (OSError, subprocess.SubprocessError) as exc:
            if discovery_mode == "git":
                raise ProjectSnapshotError("Git source inventory is unavailable") from exc
    paths = []
    # A failed Git inventory in a repository must not silently bypass its
    # global/info excludes, which a filesystem walk cannot reproduce.
    if any((parent / ".git").exists() for parent in (root, *root.parents)):
        raise ProjectSnapshotError("Git source inventory is unavailable; refusing filesystem fallback in a repository")
    ignore_specs = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        folder = Path(folder)
        inherited = list(ignore_specs.get(folder, ()))
        ignore = folder / ".gitignore"
        if ignore.exists():
            try:
                if ignore.is_symlink():
                    raise OSError("symlink ignore file")
                inherited.append((folder, GitIgnoreSpec.from_lines(ignore.read_text(encoding="utf-8").splitlines())))
            except (OSError, UnicodeError, ValueError) as exc:
                raise ProjectSnapshotError("Ignore rules could not be read; no source was sent") from exc
        def ignored(path, directory=False):
            excluded = False
            for base, spec in inherited:
                match = spec.check_file(path.relative_to(base).as_posix() + ("/" if directory else ""))
                if match.include is not None:
                    excluded = match.include
            return excluded
        dirs[:] = [name for name in dirs if name.casefold() not in _EXCLUDED_DIRS
                   and not (folder / name).is_symlink() and not ignored(folder / name, True)]
        for name in dirs:
            ignore_specs[folder / name] = inherited
        paths.extend((folder / name).relative_to(root) for name in files
                     if not ignored(folder / name))
    return sorted(set(paths), key=lambda path: path.as_posix()), "filesystem"


def capture_project(root, *, inline_bytes=1_000_000, discovery_mode=None):
    if discovery_mode not in {None, "git", "filesystem"}:
        raise ValueError("Unknown project source discovery mode")
    root = Path(root).resolve(strict=True)
    files = []
    limitations = []
    remaining = inline_bytes
    paths, actual_mode = _paths(root, discovery_mode)
    for relative in paths:
        if (relative.is_absolute() or any(part.casefold() in _EXCLUDED_DIRS for part in relative.parts)
                or ".." in relative.parts
                or any(fnmatchcase(relative.name.casefold(), pattern) for pattern in _PRIVATE_FILES)
                or relative.suffix.casefold() not in _SOURCE_SUFFIXES
                and relative.name not in {"Dockerfile", "Makefile"}):
            continue
        path = root / relative
        if any(parent.is_symlink() for parent in (path, *list(path.parents)[:len(relative.parts) - 1])):
            continue
        if not path.is_file():
            continue
        try:
            path.resolve(strict=True).relative_to(root)
            data = path.read_bytes()
        except (OSError, ValueError) as exc:
            limitations.append(f"{relative.as_posix()}: source could not be read ({type(exc).__name__})")
            continue
        content = None
        if len(data) <= remaining:
            try:
                content = data.decode("utf-8")
            except UnicodeDecodeError:
                limitations.append(f"{relative.as_posix()}: source is not UTF-8")
            else:
                remaining -= len(data)
        elif inline_bytes:
            limitations.append(f"{relative.as_posix()}: not embedded; read it with project tools")
        files.append(SourceFile(relative.as_posix(), hashlib.sha256(data).hexdigest(), len(data), content))
    return ProjectSnapshot(tuple(files), tuple(limitations), actual_mode)
