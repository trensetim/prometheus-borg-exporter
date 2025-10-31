"""Handles loading the configuration of the program"""

import os
from string import Template
import json

def _parse_bool(s: str) -> bool:
    s = s.lower().strip()
    return s in ["true", "yes", "y", "t"]

class RepositoryConfiguration:
    """Configuration for reading a single repository (parsed)"""
    name: str = "default"
    path: str = "/var/lib/borg/repositories/default"
    bypass_lock: bool = False
    passphrase_file: str = "/etc/borg/passphrases/default"

    @staticmethod
    def parse(name: str, json_obj: object) -> "RepositoryConfiguration":
        """parses a json-deserialized object into the actual class"""
        r = RepositoryConfiguration()
        r.name = name
        r.path = json_obj["path"]
        r.bypass_lock = _parse_bool(json_obj["bypass_lock"])
        r.passphrase_file = json_obj["passphrase_file"]
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
        return json.dumps([repo.__dict__ for repo in self.repositories], indent=indent)

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
            "BORG_REPOSITORY_BYPASS_LOCK": os.getenv("BORG_REPOSITORY_BYPASS_LOCK", "false"),
        })
        json_obj = json.loads(src)
        return Configuration.parse(json_obj)

    @staticmethod
    def parse(json_obj: object) -> "Configuration":
        """parses a json-deserialized object into the actual class"""
        r = Configuration()
        r.debug = _parse_bool(json_obj["logging"]["debug"])
        r.http_port = int(json_obj["http"]["port"])
        r.scan_interval_seconds = int(json_obj["scan"]["interval_seconds"])
        r.initial_scan_failure_allowed = _parse_bool(json_obj["scan"]["initial_failure_allowed"])
        r.exit_on_failure = _parse_bool(json_obj["scan"]["exit_on_failure"])
        for repo_name in json_obj["repositories"].keys():
            r.repositories.append(
                RepositoryConfiguration.parse(repo_name, json_obj["repositories"][repo_name])
            )
        return r
