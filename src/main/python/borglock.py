"""
Checks the repository directory layout to determine if the repo is locked by a borg process.
(This only works by knowing implementation details of borg v1).
"""

import os
import json
from typing import Any, cast
from datetime import datetime

def _assert_repo_integrity(path: str) -> None:
    if not os.path.exists(path):
        raise RuntimeError("repository does not exist: " + path)
    if not os.path.isdir(path):
        raise RuntimeError("repository path is not a directory: " + path)

    if not os.path.exists(
        os.path.join(path, "config")
    ):
        raise RuntimeError("repository integrity check failed (no config file found): " + path)

def _is_ex_locked_by_roster(repo_path: str, timeout_seconds: int = 0, now: datetime | None = None) -> bool:
    roster_path = os.path.join(repo_path, "lock.roster")
    if not os.path.exists(roster_path):
        return False
    roster: Any
    with open(roster_path, "r", encoding="utf-8") as fd:
        roster = json.load(fd)

    if not isinstance(roster, dict):
        raise RuntimeError("repository lock.roster broken (not a json object): " + repo_path)

    def get_exclusive() -> list[Any] | None:
        r_roster = cast(dict[str, Any], roster)
        ex = r_roster.get("exclusive", None) # newer versions casing
        if ex is None:
            ex = r_roster.get("EXCLUSIVE", None) # older versions casing
        if ex is None:
            return None
        if not isinstance(ex, list):
            raise RuntimeError("repository lock.roster broken (EXCLUSIVE is not a list): " + repo_path)
        return ex # type: ignore

    exclusive_list = get_exclusive()
    if exclusive_list is None:
        return False

    now = now or datetime.now()
    if timeout_seconds != 0 and os.stat(roster_path).st_ctime + timeout_seconds < now.timestamp():
        return False # lock.roster is outdated: cannot possibly contain any newer locks

    return len(exclusive_list) > 0

def _is_ex_locked_by_dir(repo_path: str, timeout_seconds: int = 0, now: datetime | None = None) -> bool:
    dir_path = os.path.join(repo_path, "lock.exclusive")
    if not os.path.exists(dir_path):
        return False

    if not os.path.isdir(dir_path):
        raise RuntimeError("repository lock.exclusive borken (not a dir): " + repo_path)

    locks = os.listdir(dir_path)
    if len(locks) == 0:
        return False

    now = now or datetime.now()

    for l in locks:
        lock_path = os.path.join(dir_path, l)
        lock_age = now.timestamp() - os.stat(lock_path).st_ctime
        if timeout_seconds == 0 or lock_age <= timeout_seconds:
            return True

    return False

def is_borg_repo_ex_locked(path: str, timeout_seconds: int = 0, now: datetime | None = None) -> bool:
    """
    Inspects the repository directory on the filesystem to determine if the repository is **exclusively locked** by another borg process.
    Does not determine liveness of the indicated other process PID.
    Does so by knowing the implementation details of the borg repo layout: any presence of a
    `./lock.exclusive/*` child indicates presence of an exclusive lock.
    Secondarily, checks the `lock.roster` json file.

    See-Also: https://borgbackup.readthedocs.io/en/stable/internals/data-structures.html#lock-files
    """
    _assert_repo_integrity(path)

    # We allow them to disagree: during borg cli concurrently acquiring a lock, these files may diverge for a split-second.
    # We err on the side of "is locked", because borg cli also treats "atomic dir creation" as the primary signal.
    return (
        _is_ex_locked_by_dir(path, timeout_seconds, now)
        or
        _is_ex_locked_by_roster(path, timeout_seconds, now)
    )
