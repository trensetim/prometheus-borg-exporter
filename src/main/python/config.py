"""Handles loading the configuration of the program"""

import enum
import os
import re
from string import Template
import json
from typing import Any
from flock import Flock

def _parse_bool(s: str | bool) -> bool:
    if isinstance(s, bool):
        return s
    s = s.lower().strip()
    return s in ["true", "yes", "y", "t"]

def _parse_int(s: str | int) -> int:
    if isinstance(s, int):
        return s
    s = s.strip()
    if not s.isdigit():
        raise ValueError(f"Invalid integer value: {s}")
    return int(s)

class InvalidRepositoryConfigurationError(RuntimeError):
    """Thrown if schema of a RepositoryConfiguration is wrong"""
    def __init__(self, message: str | None) -> None:
        if message is None:
            message = "repository configuration invalid"
        else:
            message = "repository configuration invalid: " + message
        super().__init__(message)

class BorgLockConfigurtation(enum.Enum):
    """Whether the borg-internal locking mechanism shall be used."""

    BYPASS = "bypass"
    """Call borg with --bypass-lock. Useful for read-only filesystems."""

    ACQUIRE = "acquire"
    """
    The default for borg: acquires a suitable lock for interacting with the repo through the borg cli.
    Since this program is a prometheus-exporter, it performs only read-only operations on the repo and thus borg cli
    will only acquire shared locks (not exclusive ones).
    """

    RESPECT = "respect"
    """
    Call borg with --bypass-lock, but manually inspect the repository directory structure before,
    to determine whether the repo is exclusively locked.
    Does not perform a liveness check on the other locking processes, which borg would normally do.
    This is useful when working on a read-only filesystem, or in containers, where
    the writing processes would live in a different process namespace and/or the exporter only gets
    a RO-mount of the repo. It is also helpful if working on an rsynced replica of the repo, where the
    writer only exists on a different host and we must behave exclusively read-only to not disturb
    concurrent rsync operations.
    """

    def is_append_bypass_arg(self):
        """Whether we should call borg cli with --bypass-lock"""
        if self == BorgLockConfigurtation.BYPASS:
            return True
        if self == BorgLockConfigurtation.ACQUIRE:
            return False
        if self == BorgLockConfigurtation.RESPECT:
            return True
        raise RuntimeError(f"Unknown {BorgLockConfigurtation.__name__}: {str(self)}")


    @staticmethod
    def parse(raw: str) -> "BorgLockConfigurtation":
        """Parse from a configuration value."""
        lraw = raw.lower()
        if lraw == "acquire":
            return BorgLockConfigurtation.ACQUIRE
        if lraw == "bypass":
            return BorgLockConfigurtation.BYPASS
        if lraw == "respect":
            return BorgLockConfigurtation.RESPECT
        raise RuntimeError(f"Unknown value for a {BorgLockConfigurtation.__name__}: " + raw)

class RepositoryConfiguration:
    """Configuration for reading a single repository (parsed)"""
    name: str = "default"
    path: str = "/var/lib/borg/repositories/default"
    locking: BorgLockConfigurtation = BorgLockConfigurtation.ACQUIRE
    locking_timeout_seconds: int = 0
    passphrase_file: str = "/etc/borg/passphrases/default"
    flock: Flock

    def has_passphrase_file(self) -> bool:
        """returns whether a passphrase file is configured"""
        return len(self.passphrase_file.strip()) > 0

    def debug_repositories_info(self) -> dict[str, Any]:
        """Generates a json-serializable representation of this instance."""
        return {
            "name": self.name,
            "path": self.path,
            "locking": self.locking.value,
            "locking_timeout_seconds": self.locking_timeout_seconds,
            "passphrase_file": self.passphrase_file,
            "flock_enabled": self.flock.is_enabled(),
            "flock_file": self.flock.get_file_path(),
            "flock_timeout_seconds": self.flock.get_timeout_seconds(),
        }

    @staticmethod
    def _parse_flock(repo_name: str, json_obj: object) -> "Flock":
        enabled: bool
        path: str
        timeout_seconds: float
        backoffs: list[float] | None = None

        if "flock_enabled" in json_obj: # type: ignore
            enabled = _parse_bool(json_obj["flock_enabled"]) # type: ignore
        else:
            enabled = False
        if "flock_file" in json_obj: # type: ignore
            path = f"{json_obj['flock_file']}" # type: ignore
        else:
            path = ""

        if "flock_timeout_seconds" in json_obj: # type: ignore
            timeout_seconds = float(json_obj["flock_timeout_seconds"]) # type: ignore
            if timeout_seconds < 0:
                raise ValueError(f"flock_timeout_seconds for repository '{repo_name}' must be >= 0")
        else:
            timeout_seconds = 1.0 # final-fallback

        if "flock_backoffs" in json_obj: # type: ignore
            backoffs_1: list[str]
            if isinstance(json_obj["flock_backoffs"], str): # type: ignore
                backoffs_1 = f"{json_obj['flock_backoffs']}".split(",") # type: ignore
            elif isinstance(json_obj["flock_backoffs"], list): # type: ignore
                backoffs_1 = [str(b) for b in json_obj["flock_backoffs"]] # type: ignore
            else:
                raise ValueError(f"flock_backoffs for repository '{repo_name}' must be a string or a list of strings")
            backoffs = [float(b) for b in backoffs_1]

        if backoffs is not None and len(backoffs) == 0:
            raise ValueError(f"flock_backoffs for repository '{repo_name}' must not be empty")

        for i in backoffs or []:
            if i <= 0:
                raise ValueError(f"flock_backoffs for repository '{repo_name}' must contain positive values")

        if enabled \
            and (
                len(path.strip()) ==  0
                or len(path.strip()) != len(path)
                or not re.match(r"^/?([^/:]+/)+[^/:]+$", path)
            ):
            raise ValueError(f"flock_enabled is true for repository '{repo_name}', but flock_file is not a valid path")

        return Flock(
            enabled=enabled,
            path=path,
            timeout_seconds=timeout_seconds,
            repo_name=repo_name,
            backoffs=backoffs
        )

    @staticmethod
    def parse(name: str, json_obj: dict[str, Any]) -> "RepositoryConfiguration":
        """parses a json-deserialized object into the actual class"""

        if json_obj.get("locking") is None:
            if json_obj.get("bypass_lock") is not None: # down-compatibility
                if _parse_bool(json_obj.get("bypass_lock", "false")):
                    json_obj["locking"] = BorgLockConfigurtation.BYPASS.value
                else:
                    json_obj["locking"] = BorgLockConfigurtation.ACQUIRE.value
            else:
                json_obj["locking"] = BorgLockConfigurtation.ACQUIRE.value
        if not isinstance(json_obj["locking"], str) or len(json_obj["locking"]) == 0:
            raise InvalidRepositoryConfigurationError("'locking' must be nonempty str")

        if not isinstance(json_obj.get("path"), str) or len(json_obj["path"]) == 0:
            raise InvalidRepositoryConfigurationError("'path' must be nonempty str")

        if json_obj.get("passphrase_file") is not None:
            if not isinstance(json_obj.get("passphrase_file"), str): # allow empty if unused
                raise InvalidRepositoryConfigurationError("'passphrase_file' must be str")

        locking_timeout_seconds = _parse_int(json_obj.get("locking_timeout_seconds", 0))
        if locking_timeout_seconds < 0:
            raise InvalidRepositoryConfigurationError("'locking_timeout_seconds' must be non-negative (0 = disabled)")

        r = RepositoryConfiguration()
        r.name = name
        r.path = json_obj["path"]
        r.locking = BorgLockConfigurtation.parse(json_obj["locking"])
        r.passphrase_file = json_obj["passphrase_file"] or ""
        r.locking_timeout_seconds = locking_timeout_seconds
        r.flock = RepositoryConfiguration._parse_flock(name, json_obj)
        return r

class Configuration:
    """Global program configuration (parsed)"""
    debug: bool = False
    http_port: int = 9401
    scan_interval_seconds: int = 1800
    initial_scan_failure_allowed: bool = False
    exit_on_failure: bool = False
    repositories: list[RepositoryConfiguration] = []

    def debug_repositories_info(self, pretty: bool = False) -> str:
        """Generates a pretty-json"""
        indent = 4 if pretty else None
        return json.dumps([repo.debug_repositories_info() for repo in self.repositories], indent=indent)

    @staticmethod
    def load(src: str | None = None) -> "Configuration":
        """loads the configuration json file, pipes it through envsubst and parses the content"""
        if src is None:
            src = os.getenv("PROMETHEUS_EXPORTER_CONFIG_FILE", "/etc/borg/exporter-config.json")
        with open(src, mode="r", encoding="utf-8") as f:
            src = f.read()
        src = Template(src).substitute({
            "PROMETHEUS_EXPORTER_DEBUG": os.getenv("PROMETHEUS_EXPORTER_DEBUG", "false"),
            "PROMETHEUS_EXPORTER_HTTP_PORT": os.getenv("PROMETHEUS_EXPORTER_HTTP_PORT", "9401"),
            "PROMETHEUS_EXPORTER_SCAN_INTERVAL_SECONDS": os.getenv("PROMETHEUS_EXPORTER_SCAN_INTERVAL_SECONDS", "1800"),
            "PROMETHEUS_EXPORTER_ALLOW_INITIAL_SCAN_FAILURE": os.getenv("PROMETHEUS_EXPORTER_ALLOW_INITIAL_SCAN_FAILURE", "false"),
            "PROMETHEUS_EXPORTER_EXIT_ON_FAILURE": os.getenv("PROMETHEUS_EXPORTER_EXIT_ON_FAILURE", "false"),
            "BORG_REPOSITORY_NAME": os.getenv("BORG_REPOSITORY_NAME", "default"),
            "BORG_REPOSITORY_PATH": os.getenv("BORG_REPOSITORY_PATH", "/var/lib/borg/repositories/default"),
            "BORG_REPOSITORY_PASSPHRASE_FILE": os.getenv("BORG_REPOSITORY_PASSPHRASE_FILE", "/etc/borg/passphrases/default"),
            "BORG_REPOSITORY_BYPASS_LOCK": os.getenv("BORG_REPOSITORY_BYPASS_LOCK", "false"), # for down-compatibility
            "BORG_REPOSITORY_LOCKING": os.getenv("BORG_REPOSITORY_LOCKING", BorgLockConfigurtation.ACQUIRE.value),
            "BORG_REPOSITORY_LOCKING_TIMEOUT_SECONDS": os.getenv("BORG_REPOSITORY_LOCKING_TIMEOUT_SECONDS", "0"),
            "BORG_REPOSITORY_FLOCK_ENABLED": os.getenv("BORG_REPOSITORY_FLOCK_ENABLED", "false"),
            "BORG_REPOSITORY_FLOCK_FILE": os.getenv("BORG_REPOSITORY_FLOCK_FILE", "/var/lock/borg/default"),
            "BORG_REPOSITORY_FLOCK_TIMEOUT_SECONDS": os.getenv("BORG_REPOSITORY_FLOCK_TIMEOUT_SECONDS", "1.0"),
            "BORG_REPOSITORY_FLOCK_BACKOFFS": os.getenv("BORG_REPOSITORY_FLOCK_BACKOFFS", "0.01,0.05,0.1,0.25,1.0,10.0"),
        })
        json_obj = json.loads(src)
        return Configuration.parse(json_obj)

    @staticmethod
    def parse(json_obj: object) -> "Configuration":
        """parses a json-deserialized object into the actual class"""
        r = Configuration()
        r.repositories = []
        r.debug = _parse_bool(json_obj["logging"]["debug"]) # type: ignore
        r.http_port = int(json_obj["http"]["port"]) # type: ignore
        r.scan_interval_seconds = int(json_obj["scan"]["interval_seconds"]) # type: ignore
        r.initial_scan_failure_allowed = _parse_bool(json_obj["scan"]["initial_failure_allowed"]) # type: ignore
        r.exit_on_failure = _parse_bool(json_obj["scan"]["exit_on_failure"]) # type: ignore
        for repo_name in json_obj["repositories"].keys(): # type: ignore
            r.repositories.append(
                RepositoryConfiguration.parse(repo_name, json_obj["repositories"][repo_name]) # type: ignore
            )
        return r
