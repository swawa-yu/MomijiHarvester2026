#!/usr/bin/env python3
"""Refuse a consumer update that changes anything outside its data binding."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


def allowed_paths(
    data_file: str,
    history_paths: tuple[str, ...] = (),
) -> set[str]:
    if not data_file or Path(data_file).name != data_file:
        raise ValueError("data file must be a non-empty basename")
    allowed = {
        f"data/{data_file}",
        "data/subjectDataManifest.json",
        "data/department_constants.json",
        "data/subject_structure.json",
        "data/derivedSubjectConstants.json",
        "src/types/subjectConstants.ts",
        "src/subject/activeSubjectData.ts",
        "src/types/rawSubjectProperties.ts",
    }
    for history_path in history_paths:
        if not re.fullmatch(
            r"data/history/\d{4}/(?:index|history_[A-Za-z0-9._-]+)\.json",
            history_path,
        ):
            raise ValueError(f"unsafe history path: {history_path}")
        allowed.add(history_path)
    return allowed


def obsolete_path(data_file: str, obsolete_data_file: str | None) -> str | None:
    if obsolete_data_file is None:
        return None
    if (
        Path(obsolete_data_file).name != obsolete_data_file
        or not re.fullmatch(
            r"subject_details_main_[A-Za-z0-9._-]+\.json",
            obsolete_data_file,
        )
        or obsolete_data_file == data_file
    ):
        raise ValueError("obsolete data file must be a different safe generation")
    return f"data/{obsolete_data_file}"


def assert_allowed_changes(
    changes: list[tuple[str, str]],
    data_file: str,
    history_paths: tuple[str, ...] = (),
    obsolete_data_file: str | None = None,
) -> None:
    allowed = allowed_paths(data_file, history_paths)
    obsolete = obsolete_path(data_file, obsolete_data_file)
    unexpected = [
        f"{status} {path}"
        for status, path in changes
        if not (
            (path in allowed and status in {"??", " M", " A", "A "})
            or (path == obsolete and status == " D")
        )
    ]
    if unexpected:
        raise ValueError(
            "unexpected consumer changes: " + ", ".join(unexpected)
        )


def parse_porcelain(output: bytes) -> list[tuple[str, str]]:
    fields = output.decode("utf-8").split("\0")
    changes = []
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        if len(field) < 4 or field[2] != " ":
            raise ValueError(f"invalid git porcelain status: {field!r}")
        status, path = field[:2], field[3:]
        if not path:
            raise ValueError("git porcelain status has an empty path")
        if "R" in status or "C" in status:
            if index >= len(fields) or not fields[index]:
                raise ValueError("git porcelain rename/copy is incomplete")
            index += 1
            changes.append((status, path))
            continue
        changes.append((status, path))
    return changes


def parse_name_status(output: bytes) -> list[tuple[str, str]]:
    fields = output.decode("utf-8").split("\0")
    changes = []
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        try:
            status, path = field.split("\t", 1)
        except ValueError as error:
            raise ValueError(
                f"invalid git name-status entry: {field!r}"
            ) from error
        if not path:
            raise ValueError("git name-status entry has an empty path")
        if status.startswith(("R", "C")):
            if index >= len(fields) or not fields[index]:
                raise ValueError("git name-status rename/copy is incomplete")
            index += 1
        changes.append((status, path))
    return changes


def assert_allowed_patch_changes(
    changes: list[tuple[str, str]],
    data_file: str,
    history_paths: tuple[str, ...] = (),
    obsolete_data_file: str | None = None,
) -> None:
    allowed = allowed_paths(data_file, history_paths)
    obsolete = obsolete_path(data_file, obsolete_data_file)
    unexpected = [
        f"{status} {path}"
        for status, path in changes
        if not (
            (path in allowed and status in {"A", "M"})
            or (path == obsolete and status == "D")
        )
    ]
    if unexpected:
        raise ValueError(
            "unexpected consumer branch changes: " + ", ".join(unexpected)
        )


def git_changes(consumer: Path) -> list[tuple[str, str]]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(consumer),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
        check=True,
        capture_output=True,
    )
    return parse_porcelain(completed.stdout)


def git_patch_changes(
    consumer: Path, base_ref: str, head_ref: str
) -> list[tuple[str, str]]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(consumer),
            "diff",
            "--name-status",
            "-z",
            f"{base_ref}...{head_ref}",
        ],
        check=True,
        capture_output=True,
    )
    return parse_name_status(completed.stdout)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--consumer", required=True, type=Path)
    parser.add_argument("--data-file", required=True)
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    parser.add_argument("--history-path", action="append", default=[])
    parser.add_argument("--obsolete-data-file")
    args = parser.parse_args()
    if bool(args.base_ref) != bool(args.head_ref):
        raise ValueError("base-ref and head-ref must be provided together")
    if args.base_ref:
        assert_allowed_patch_changes(
            git_patch_changes(args.consumer, args.base_ref, args.head_ref),
            args.data_file,
            tuple(args.history_path),
            args.obsolete_data_file,
        )
    else:
        assert_allowed_changes(
            git_changes(args.consumer),
            args.data_file,
            tuple(args.history_path),
            args.obsolete_data_file,
        )


if __name__ == "__main__":
    main()
