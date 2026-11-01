"""
End-of-work cleanup of build directories inside the checkout (`clean-directories`).
Only `devops-tools container clean` uses this, and only when a person asks for it.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from pathlib import Path

from devops_tools.exceptions import CleanupRefusedError


def select_paths_to_remove(
    repository_root: Path, candidate_paths: Sequence[Path], protected_directories: Sequence[str]
) -> list[Path]:
    """
    Return the candidates that exist, in order. Refuse the whole set if any is unsafe.
    Unsafe: outside the checkout (after resolving `..` and symlinks in parent directories), the
    checkout itself, a symlink, or inside one of `protected_directories`.
    """
    resolved_root = repository_root.resolve()
    selected_paths: list[Path] = []
    for candidate_path in candidate_paths:
        # Resolve the parent but keep the last component, so a symlinked directory is caught
        # below instead of being followed. `.` and `..` have no last component to keep.
        if candidate_path.name in ("", ".", ".."):
            resolved_candidate = candidate_path.resolve()
        else:
            resolved_candidate = candidate_path.parent.resolve() / candidate_path.name
        if (
            not resolved_candidate.is_relative_to(resolved_root)
            or resolved_candidate == resolved_root
        ):
            raise CleanupRefusedError(f"refusing {candidate_path}: not inside {resolved_root}")
        relative_candidate = resolved_candidate.relative_to(resolved_root)
        for protected_directory in protected_directories:
            if relative_candidate.is_relative_to(Path(protected_directory)):
                raise CleanupRefusedError(
                    f"refusing {candidate_path}: {protected_directory}/ is never cleaned"
                )
        if resolved_candidate.is_symlink():
            raise CleanupRefusedError(f"refusing {candidate_path}: it is a symlink")
        if resolved_candidate.exists():
            selected_paths.append(resolved_candidate)
    return selected_paths


def measure_directory_size_bytes(directory_path: Path) -> int:
    """
    Sum of file sizes under `directory_path`, not following symlinks.
    """
    total_bytes = 0
    for walk_root, _, file_names in os.walk(directory_path):
        for file_name in file_names:
            total_bytes += (Path(walk_root) / file_name).lstat().st_size
    return total_bytes


def remove_directory_tree(directory_path: Path) -> None:
    shutil.rmtree(directory_path)
