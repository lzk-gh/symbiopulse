import os
import time
from pathlib import Path
from typing import Iterator, List, Optional, Set, Tuple

try:
    import pathspec
except ImportError:
    pathspec = None


class ScanBudgetExceeded(RuntimeError):
    """Raised before a scan can publish a partial, unbounded snapshot."""


class PathFilter:
    """Canonical path policy shared by every project traversal."""

    DEFAULT_IGNORES = [
        ".git/",
        ".symbio/",
        "node_modules/",
        ".*-node-modules-link*/",
        "node_modules.failed-*/",
        ".tools/",
        ".worktrees/",
        ".codex-worktrees/",
        ".codex-temp/",
        ".codex-trash/",
        ".venv/",
        "venv/",
        "__pycache__/",
        "dist/",
        "build/",
        "target/",
        ".next/",
        "coverage/",
        "htmlcov/",
        ".cursor/",
        ".github/",
        ".idea/",
        ".vscode/",
        ".pytest_cache/",
        ".mypy_cache/",
        ".ruff_cache/",
        "*.pyc",
        ".DS_Store",
        "*.zip",
        "*.tar",
        "*.tgz",
        "*.tar.gz",
    ]

    _REPARSE_POINT = 0x400
    _SAFETY_DIR_NAMES = {".git", ".symbio"}

    def __init__(self, root: str, extra_patterns: Optional[List[str]] = None):
        self.root = Path(root).resolve()
        patterns = list(self.DEFAULT_IGNORES)
        for ignore_name in (".gitignore", ".symbioignore"):
            ignore_file = self.root / ignore_name
            if ignore_file.exists():
                patterns.extend(ignore_file.read_text(encoding="utf-8", errors="ignore").splitlines())
        if extra_patterns:
            patterns.extend(extra_patterns)
        self.patterns = [line.strip() for line in patterns if line.strip() and not line.lstrip().startswith("#")]
        self.spec = pathspec.PathSpec.from_lines("gitignore", self.patterns) if pathspec else None

    def relative_path(self, path: Path) -> Optional[str]:
        """Return a stable project-relative path, rejecting root escapes."""
        try:
            candidate = path.resolve(strict=False)
            relative = candidate.relative_to(self.root)
        except (OSError, ValueError):
            return None
        return relative.as_posix()

    def ignore_reason(self, path: Path, is_dir: Optional[bool] = None) -> Optional[str]:
        if path != self.root and self._is_link_or_reparse(path):
            return "filesystem_link"
        relative = self.relative_path(path)
        if relative is None:
            return "outside_root"
        if not relative:
            return None
        if self._SAFETY_DIR_NAMES.intersection(relative.split("/")):
            return "safety_boundary"
        if self.spec and self.spec.match_file(relative + ("/" if is_dir else "")):
            return "ignore_rule"
        if not self.spec and self._fallback_match(relative, bool(is_dir)):
            return "ignore_rule"
        return None

    def is_ignored(self, path: str, is_dir: Optional[bool] = None) -> bool:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        return self.ignore_reason(candidate, is_dir=is_dir) is not None

    def walk(
        self,
        max_directories: int,
        max_files: int,
        max_seconds: float,
        deadline: Optional[float] = None,
    ) -> Iterator[Tuple[Path, str, List[str]]]:
        """Traverse without following links, aliases, mounts, or repeated identities."""
        deadline = deadline or (time.monotonic() + max_seconds)
        stack = [self.root]
        visited: Set[Tuple[int, int]] = set()
        directory_count = 0
        file_count = 0

        while stack:
            if time.monotonic() > deadline:
                raise ScanBudgetExceeded(f"scan exceeded {max_seconds:.1f}s time budget")
            current = stack.pop()
            identity = self._identity(current)
            if identity is None or identity in visited:
                continue
            visited.add(identity)
            directory_count += 1
            if directory_count > max_directories:
                raise ScanBudgetExceeded(f"scan exceeded {max_directories} directory budget")

            relative = self.relative_path(current)
            if relative is None:
                continue
            files: List[str] = []
            children: List[Path] = []
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        if time.monotonic() > deadline:
                            raise ScanBudgetExceeded(f"scan exceeded {max_seconds:.1f}s time budget")
                        entry_path = Path(entry.path)
                        try:
                            if entry.is_symlink() or self._is_link_or_reparse(entry_path):
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                if os.path.ismount(entry_path):
                                    continue
                                if self.ignore_reason(entry_path, is_dir=True) is None:
                                    children.append(entry_path)
                            elif entry.is_file(follow_symlinks=False):
                                if self.ignore_reason(entry_path, is_dir=False) is None:
                                    files.append(entry.name)
                                    file_count += 1
                                    if file_count > max_files:
                                        raise ScanBudgetExceeded(f"scan exceeded {max_files} file budget")
                        except OSError:
                            continue
            except (OSError, PermissionError):
                continue

            if relative:
                yield current, relative, sorted(files)
            stack.extend(reversed(sorted(children, key=lambda item: item.name.lower())))

    def _fallback_match(self, relative: str, is_dir: bool) -> bool:
        parts = relative.split("/")
        for pattern in self.patterns:
            normalized = pattern.strip("/")
            if not normalized or pattern.startswith("!"):
                continue
            if pattern.endswith("/") and normalized in parts:
                return True
            if pattern.startswith("*.") and relative.endswith(pattern[1:]):
                return True
            if normalized == relative or normalized in parts:
                return True
            if normalized.startswith(".*-") and normalized.rstrip("*/") in relative:
                return True
        return False

    def _identity(self, path: Path) -> Optional[Tuple[int, int]]:
        try:
            stat_result = os.stat(path, follow_symlinks=False)
            if stat_result.st_ino:
                return stat_result.st_dev, stat_result.st_ino
            return stat_result.st_dev, hash(str(path.resolve(strict=False)).lower())
        except OSError:
            return None

    def _is_link_or_reparse(self, path: Path) -> bool:
        try:
            stat_result = path.lstat()
        except OSError:
            return True
        attributes = getattr(stat_result, "st_file_attributes", 0)
        return path.is_symlink() or bool(attributes & self._REPARSE_POINT)
