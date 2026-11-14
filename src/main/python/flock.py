"""file lock manager"""

from contextlib import contextmanager
import fcntl
import os
from time import monotonic, sleep
from typing import BinaryIO, Generator

from log import log, LOGDEBUG
from prometheus_client import Gauge

class BorgRepositoryFlockedError(RuntimeError):
    """Exception raised when the external flock for a borg repository cannot be acquired."""
    def __init__(self, repository_name: str, flock_file: str):
        super().__init__(f"repository '{repository_name}' is locked via flock '{flock_file}'")

class BorgRepositoryDoubleFlocked(RuntimeError):
    """Exception raised when trying to acquire a flock twice."""
    def __init__(self, repository_name: str):
        super().__init__(f"trying to acquire a flock twice: BUG! ({repository_name})")

class Flock:
    """
    File-Lock manager for a single borg repository.
    Reports whether the file lock was acquired successfully (0) or not (1) on the provided metric.
    """
    _enabled: bool
    _path: str
    _timeout_seconds: float
    _repo_name: str
    _acquired: bool
    _backoffs: list[float]

    def __init__(self,
            enabled: bool,
            path: str,
            timeout_seconds: float,
            repo_name: str,
            backoffs: list[float] | None = None
        ):
        self._enabled = enabled
        self._path = path
        self._timeout_seconds = timeout_seconds
        self._repo_name = repo_name
        self._acquired = False
        self._backoffs = backoffs if backoffs is not None else [0.01, 0.05, 0.1, 0.25, 1.0, 10.0]

        if enabled:
            with self._open():
                pass # ensure the flock file exists

    def is_enabled(self) -> bool:
        """returns whether flocking is enabled for this repository"""
        return self._enabled

    def get_file_path(self) -> str:
        """returns the path to the flock file"""
        return self._path

    def get_timeout_seconds(self) -> float:
        """returns the flock timeout in seconds"""
        return self._timeout_seconds

    @contextmanager
    def acquire(self, metric: Gauge) -> Generator[None, None, None]:
        """
        Acquires the file lock (if enabled) and releases it upon close(). Useful within a `with` statement.
        Reports whether the file lock was acquired successfully (0) or not (1) on the provided metric.
        If not `is_enabled()`, the lock is considered acquired automatically and this method becomes effectively a no-op.
        """
        if not self._enabled:
            metric.labels(self._repo_name).set(0)
            yield
            return

        if self._acquired:
            raise BorgRepositoryDoubleFlocked(self._repo_name)

        deadline = monotonic() + self._timeout_seconds
        backoffs = self._backoffs.copy()

        with self._open() as lock_file:
            while True:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        metric.labels(self._repo_name).set(1)
                        raise BorgRepositoryFlockedError(self._repo_name, self._path) from exc
                    sleep(min(backoffs[0], remaining))
                    backoffs = backoffs[1:] if len(backoffs) > 1 else backoffs

            log(LOGDEBUG, f"acquired shared flock '{self._path}' for repository '{self._repo_name}'")
            metric.labels(self._repo_name).set(0)
            self._acquired = True
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                self._acquired = False
                log(LOGDEBUG, f"released shared flock '{self._path}' for repository '{self._repo_name}'")

    def _open(self) -> BinaryIO:
        """
        Open an existing flock file read-only (works on read-only mounts), or create it if missing.
        Caller must close the returned BinaryIO.
        """
        try:
            reader = open(self._path, mode="rb")
        except FileNotFoundError:
            reader = open(self._path, mode="a+b")
        os.set_inheritable(reader.fileno(), False)
        return reader
