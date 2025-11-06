#!/usr/bin/env python

"""Prometheus exporter for BorgBackup repositories."""

from datetime import datetime, timedelta
import os
import sys
import json
import subprocess

from time import sleep, mktime
from typing import BinaryIO
from dateutil import parser

from prometheus_client import start_http_server, Gauge, Enum, Info
from config import Configuration, RepositoryConfiguration

# define prometheus metrics as global variables for the http_server to access
successful_scan_timestamp_seconds        = Gauge('borg_repository_successful_scan_timestamp_seconds', 'UNIX timestamp of the last successfully completed scan of the repository by the exporter', ['repository_id', 'repository_name'])
scan_timestamp_seconds                   = Gauge('borg_repository_scan_timestamp_seconds', 'UNIX timestamp of the last scan of the repository by the exporter', ['repository_name'])
scan_returncode                          = Gauge('borg_repository_scan_returncode', 'Return code (exitcode) of the borg info subprocess used for scanning the repository. Zero if successfully scanned.', ['repository_name'])
scan_info                                = Info('borg_repository_scan', 'Information about the last scan of the repository. Even if scan failed.', ['repository_name'])
repository_locked                        = Gauge('borg_repository_locked', 'Whether the repository is currently locked (1=yes, 0=no)', ['repository_name'])
chunks_count                             = Gauge('borg_repository_chunks_count', 'Number of chunks', ['repository_id', 'repository_name'])
compressed_size_bytes                    = Gauge('borg_repository_compressed_size_bytes', 'Total compressed and encrypted size of all chunks multiplied with their reference counts in bytes', ['repository_id', 'repository_name'])
size_bytes                               = Gauge('borg_repository_size_bytes', 'Total uncompressed size of all chunks multiplied with their reference counts', ['repository_id', 'repository_name'])
unique_chunks_count                      = Gauge('borg_repository_unique_chunks_count', 'Number of unique chunks', ['repository_id', 'repository_name'])
unique_compressed_size_bytes             = Gauge('borg_repository_unique_compressed_size_bytes', 'Compressed and encrypted size of all chunks in bytes', ['repository_id', 'repository_name'])
unique_size_bytes                        = Gauge('borg_repository_unique_size_bytes', 'Uncompressed size of all chunks', ['repository_id', 'repository_name'])
last_modified_timestamp_seconds          = Gauge('borg_repository_last_modified_timestamp_seconds', 'Last modified UNIX timestamp', ['repository_id', 'repository_name'])
encryption_mode                          = Enum('borg_repository_encryption_mode', 'Encryption mode of the repository', ['repository_id', 'repository_name'], states=['none', 'repokey', 'keyfile', 'authenticated', 'keyfile-blake2', 'repokey-blake2', 'authenticated-blake2'])
latest_archive_info                      = Info('borg_repository_latest_archive', 'Information about the latest/last archive/backup stored in the repository', ['repository_id', 'repository_name'])
latest_archive_duration_seconds          = Gauge('borg_repository_latest_archive_duration_seconds', 'Seconds it took to create the latest archive', ['repository_id', 'repository_name'])
latest_archive_start_timestamp_seconds   = Gauge('borg_repository_latest_archive_start_timestamp_seconds', 'UNIX timestamp when the creation of the latest archive was initiated', ['repository_id', 'repository_name'])
latest_archive_end_timestamp_seconds     = Gauge('borg_repository_latest_archive_end_timestamp_seconds', 'UNIX timestamp when the creation of the latest archive was completed', ['repository_id', 'repository_name'])
latest_archive_compressed_size_bytes     = Gauge('borg_repository_latest_archive_compressed_size_bytes', 'Size after compression in bytes', ['repository_id', 'repository_name'])
latest_archive_deduplicated_size_bytes   = Gauge('borg_repository_latest_archive_deduplicated_size_bytes', 'Deduplicated size (against the current repository, not when the archive was created) in bytes', ['repository_id', 'repository_name'])
latest_archive_nfiles_count              = Gauge('borg_repository_latest_archive_nfiles_count', 'Number of regular files in the archive', ['repository_id', 'repository_name'])
latest_archive_original_size_bytes       = Gauge('borg_repository_latest_archive_original_size_bytes', 'Size of files and metadata before compression in bytes', ['repository_id', 'repository_name'])
latest_archive_limits_archive_size_ratio = Gauge('borg_repository_latest_archive_limits_archive_size_ratio', 'Float between 0 and 1 describing how large this archive is relative to the maximum size allowed by Borg', ['repository_id', 'repository_name'])

DEBUG_MODE: bool = False
BORG_VERSION: str = ""

class BorgRepositoryLockedError(RuntimeError):
    """Exception raised when the borg repository is locked."""
    def __init__(self):
        super().__init__('borg repository is locked')

LOGWARN=20
LOGINFO=10
LOGDEBUG=2

def log(level, message):
    """Log a message to stdout depending on the log level and debug mode."""
    if level < 5 and not DEBUG_MODE:
        return
    print(message)

def borg_info(config: RepositoryConfiguration) -> subprocess.CompletedProcess:
    """Executed `borg info ... $repopath` on the shell"""
    cmd = ['borg', 'info', '--json', '--last', '1']
    env = {}

    # proxy through all BORG_ env vars
    # (this must happen, before the other env vars get applied later,
    #  in order to prevent users overwriting our settings here)
    for k, v in os.environ.items():
        if k.lower().startswith("borg"):
            env[k] = v

    # unset possibly-dangerous env vars from parent environment
    env.pop("BORG_PASSPHRASE", None)
    env.pop("BORG_PASSCOMMAND", None)
    env.pop("BORG_PASSPHRASE_FD", None)
    env.pop("BORG_NEW_PASSPHRASE", None)
    env.pop("BORG_BYPASS_LOCK", None) # this does not exist YET (borg 1.4.1), but it looks like it may, so lets be ultra-careful
    env["BORG_DISPLAY_PASSPHRASE"] = "no"

    # internal configuration, we rely upon with out implementation here
    env["BORG_EXIT_CODES"] = "modern"
    env["BORG_REPO"] = config.path
    if config.bypass_lock:
        cmd.append('--bypass-lock')

    passphrase_file: BinaryIO | None = None

    try:
        if config.has_passphrase_file():
            passphrase_file = open(config.passphrase_file, mode="rb", buffering=0) # pylint: disable=consider-using-with
            os.set_inheritable(passphrase_file.fileno(), True)
            env["BORG_PASSPHRASE_FD"] = str(passphrase_file.fileno())

        proc = subprocess.run(cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=False,
            check=False,
            env=env)

        return proc
    finally:
        if passphrase_file is not None:
            passphrase_file.close()


def scan_repository(config: RepositoryConfiguration):
    """Scan the borg repository and update prometheus metrics."""
    name = config.name

    borg_process = borg_info(config)
    stdout = borg_process.stdout.decode("utf-8")
    stderr = borg_process.stderr.decode("utf-8")
    args = borg_process.args
    log(LOGDEBUG, f"borg process: stdout={stdout}, stderr={stderr}")

    scan_timestamp_seconds.labels(name).set(mktime(datetime.now().timetuple()))
    scan_returncode.labels(name).set(borg_process.returncode)
    scan_info.labels(name).info({
        'returncode': str(borg_process.returncode),
        'stdout': stdout,
        'stderr': stderr,
        'args': ' '.join('"' + x + '"' for x in args),
        'cmd': 'info',
        'executable': 'borg',
        'borg_version': BORG_VERSION
    })

    if borg_process.returncode != 0:
        # first, try to inspect stderr as json (might not always work: borg sometimes outputs plain text errors, even with `--json`)
        try:
            error_str = stderr
            error_json = json.loads(error_str)
            if error_json['msgid'] == "LockTimeout":
                repository_locked.labels(name).set(1)
                raise BorgRepositoryLockedError()
        except json.JSONDecodeError:
            pass # okay, we failed but not due to a lock. Other errors may not be json-decodable.

        # alternatively, check for borg's modern exit codes (see BORG_EXIT_CODES=modern in borg documentation)
        # https://borgbackup.readthedocs.io/en/stable/internals/frontends.html#msgid
        if borg_process.returncode == 73:
            repository_locked.labels(name).set(1)
            raise BorgRepositoryLockedError()

    borg_process.check_returncode()

    raw_borg_json = stdout
    info = json.loads(raw_borg_json)
    repository_id = info['repository']['id']

    repository_locked.labels(name).set(0)
    successful_scan_timestamp_seconds.labels(repository_id, name).set(mktime(datetime.now().timetuple()))
    last_modified_timestamp_seconds.labels(repository_id, name).set(mktime(parser.parse(info['repository']['last_modified']).timetuple()))
    encryption_mode.labels(repository_id, name).state(info['encryption']['mode'])

    stats = info['cache']['stats']
    chunks_count.labels(repository_id, name).set(stats['total_chunks'])
    compressed_size_bytes.labels(repository_id, name).set(stats['total_csize'])
    size_bytes.labels(repository_id, name).set(stats['total_size'])
    unique_chunks_count.labels(repository_id, name).set(stats['total_unique_chunks'])
    unique_compressed_size_bytes.labels(repository_id, name).set(stats['unique_csize'])
    unique_size_bytes.labels(repository_id, name).set(stats['unique_size'])

    if len(info['archives']) == 0:
        log(LOGINFO, f"repository '{name}' is empty, no archives found")
        return

    last = info['archives'][0]
    latest_archive_info.labels(repository_id, name).info({
        'id': last['id'],
        'name': last['name'],
        'comment': last['comment'],
        'command_line': ' '.join(str(x) for x in last['command_line']),
        'chunker_params': ','.join(str(x) for x in last['chunker_params']),
        'username': last['username'],
        'hostname': last['hostname']
    })
    latest_archive_duration_seconds.labels(repository_id, name).set(last['duration'])
    latest_archive_start_timestamp_seconds.labels(repository_id, name).set(mktime(parser.parse(last['start']).timetuple()))
    latest_archive_end_timestamp_seconds.labels(repository_id, name).set(mktime(parser.parse(last['end']).timetuple()))
    latest_archive_compressed_size_bytes.labels(repository_id, name).set(last['stats']['compressed_size'])
    latest_archive_deduplicated_size_bytes.labels(repository_id, name).set(last['stats']['deduplicated_size'])
    latest_archive_nfiles_count.labels(repository_id, name).set(last['stats']['nfiles'])
    latest_archive_original_size_bytes.labels(repository_id, name).set(last['stats']['original_size'])
    latest_archive_limits_archive_size_ratio.labels(repository_id, name).set(last['limits']['max_archive_size'])

def scan_repositories(repos: list[RepositoryConfiguration], allow_locked: bool = False, allow_failure: bool = False):
    """Loops through all given repositories and collects the metrics for them"""
    try:
        for repo in repos:
            scan_repository(repo)
    except BorgRepositoryLockedError:
        if not allow_locked:
            sys.exit(15)
        log(LOGDEBUG, "repository is currently locked. will try again later")
    except subprocess.CalledProcessError as e:
        log(LOGWARN, f"scan failed with returncode={e.returncode} and stderr: {e.stderr}")
        if not allow_failure:
            sys.exit(2)
    except Exception as e: # pylint: disable=broad-except
        if not allow_failure:
            sys.exit(1)
        log(LOGWARN, f"scan failed, but that was allowed, so ignoring. Message was: {str(e)}")

if __name__ == '__main__':
    configuration = Configuration.load()
    DEBUG_MODE = configuration.debug
    BORG_VERSION = subprocess.run(['borg', '--version'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True).stdout.decode("utf-8")[5:-1]

    log(LOGDEBUG, f"http port: {configuration.http_port}")
    log(LOGDEBUG, f"rescan interval: {configuration.scan_interval_seconds}s")
    log(LOGDEBUG, f"allow initial scan failure: {configuration.initial_scan_failure_allowed}")
    log(LOGDEBUG, f"exit on failure: {configuration.exit_on_failure}")
    log(LOGDEBUG, f"borg version: {BORG_VERSION}")
    log(LOGDEBUG, f"debug mode: {DEBUG_MODE}")
    log(LOGDEBUG, f"repositories: {configuration.debug_repositories_info()}")

    log(LOGDEBUG, "performing initial scan")
    scan_repositories(configuration.repositories, True, configuration.initial_scan_failure_allowed)
    log(LOGINFO, "initial scan finished")

    log(LOGDEBUG, "starting http server")
    http_server = start_http_server(configuration.http_port)
    log(LOGINFO, "up.")

    try:
        while True:
            log(LOGDEBUG, f"next rescan scheduled for {(datetime.now() + timedelta(seconds = configuration.scan_interval_seconds)).strftime('%Y-%m-%d %H:%M:%S %z')}")
            sleep(configuration.scan_interval_seconds)
            log(LOGINFO, "performing scan")
            scan_repositories(configuration.repositories, True, configuration.exit_on_failure)
            log(LOGINFO, "scan finished")
    except (KeyboardInterrupt, InterruptedError):
        log(LOGWARN, "interrupted and stopped.")
