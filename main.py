#!/usr/bin/env python

from prometheus_client import start_http_server, Gauge, Enum, Info
from time import sleep, mktime
from dateutil import parser
from datetime import datetime, timedelta

import sys
import os
import json
import subprocess

# define prometheus metrics as global variables for the http_server to access
successful_scan_timestamp_seconds        = Gauge('borg_repository_successful_scan_timestamp_seconds', 'UNIX timestamp of the last successfully completed scan of the repository by the exporter', ['repository_id', 'repository_name'])
scan_timestamp_seconds                   = Gauge('borg_repository_scan_timestamp_seconds', 'UNIX timestamp of the last scan of the repository by the exporter', ['repository_name'])
scan_returncode                          = Gauge('borg_repository_scan_returncode', 'Return code (exitcode) of the borg info subprocess used for scanning the repository. Zero if successfully scanned.', ['repository_name'])
scan_info                                = Info('borg_repository_scan_info', 'Information about the last scan of the repository. Even if scan failed.', ['repository_name'])
repository_locked                        = Gauge('borg_repository_locked', 'Whether the repository is currently locked (1=yes, 0=no)', ['repository_name'])
chunks_count                             = Gauge('borg_repository_chunks_count', 'Number of chunks', ['repository_id', 'repository_name'])
compressed_size_bytes                    = Gauge('borg_repository_compressed_size_bytes', 'Total compressed and encrypted size of all chunks multiplied with their reference counts in bytes', ['repository_id', 'repository_name'])
size_bytes                               = Gauge('borg_repository_size_bytes', 'Total uncompressed size of all chunks multiplied with their reference counts', ['repository_id', 'repository_name'])
unique_chunks_count                      = Gauge('borg_repository_unique_chunks_count', 'Number of unique chunks', ['repository_id', 'repository_name'])
unique_compressed_size_bytes             = Gauge('borg_repository_unique_compressed_size_bytes', 'Compressed and encrypted size of all chunks in bytes', ['repository_id', 'repository_name'])
unique_size_bytes                        = Gauge('borg_repository_unique_size_bytes', 'Uncompressed size of all chunks', ['repository_id', 'repository_name'])
last_modified_timestamp_seconds          = Gauge('borg_repository_last_modified_timestamp_seconds', 'Last modified UNIX timestamp', ['repository_id', 'repository_name'])
encryption_mode                          = Enum('borg_repository_encryption_mode', 'Encryption mode of the repository', ['repository_id', 'repository_name'], states=['none', 'repokey', 'keyfile', 'authenticated', 'keyfile-blake2', 'repokey-blake2', 'authenticated-blake2'])
latest_archive_info                      = Info('borg_repository_latest_archive_info', 'Information about the latest/last archive/backup stored in the repository', ['repository_id', 'repository_name'])
latest_archive_duration_seconds          = Gauge('borg_repository_latest_archive_duration_seconds', 'Seconds it took to create the latest archive', ['repository_id', 'repository_name'])
latest_archive_start_timestamp_seconds   = Gauge('borg_repository_latest_archive_start_timestamp_seconds', 'UNIX timestamp when the creation of the latest archive was initiated', ['repository_id', 'repository_name'])
latest_archive_end_timestamp_seconds     = Gauge('borg_repository_latest_archive_end_timestamp_seconds', 'UNIX timestamp when the creation of the latest archive was completed', ['repository_id', 'repository_name'])
latest_archive_compressed_size_bytes     = Gauge('borg_repository_latest_archive_compressed_size_bytes', 'Size after compression in bytes', ['repository_id', 'repository_name'])
latest_archive_deduplicated_size_bytes   = Gauge('borg_repository_latest_archive_deduplicated_size_bytes', 'Deduplicated size (against the current repository, not when the archive was created) in bytes', ['repository_id', 'repository_name'])
latest_archive_nfiles_count              = Gauge('borg_repository_latest_archive_nfiles_count', 'Number of regular files in the archive', ['repository_id', 'repository_name'])
latest_archive_original_size_bytes       = Gauge('borg_repository_latest_archive_original_size_bytes', 'Size of files and metadata before compression in bytes', ['repository_id', 'repository_name'])
latest_archive_limits_archive_size_ratio = Gauge('borg_repository_latest_archive_limits_archive_size_ratio', 'Float between 0 and 1 describing how large this archive is relative to the maximum size allowed by Borg', ['repository_id', 'repository_name'])

borg_version = subprocess.run(['borg', '--version'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.decode("utf-8")[5:-1]

class BorgRepositoryLockedError(RuntimeError):
    def __init__(self):
        super().__init__('borg repository is locked')

def scan_repository(repository):
    borg_process = subprocess.run(['borg', 'info', '--json', '--log-json', '--last', '1', repository], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout = borg_process.stdout.decode("utf-8")
    stderr = borg_process.stderr.decode("utf-8")
    args = borg_process.args

    scan_timestamp_seconds.labels(repository).set(mktime(datetime.now().timetuple()))
    scan_returncode.labels(repository).set(borg_process.returncode)
    scan_info.labels(repository).info({
        'returncode': str(borg_process.returncode),
        'stdout': stdout,
        'stderr': stderr,
        'args': ' '.join('"' + x + '"' for x in args),
        'cmd': 'info',
        'executable': 'borg',
        'borg_version': borg_version
    })

    if borg_process.returncode != 0:
        error_str = stderr
        error_json = json.loads(error_str)
        if error_json['msgid'] == "LockTimeout":
            repository_locked.labels(repository).set(1)
            raise BorgRepositoryLockedError()

    borg_process.check_returncode()

    raw_borg_json = stdout
    info = json.loads(raw_borg_json)
    repository_id = info['repository']['id']

    repository_locked.labels(repository).set(0)
    successful_scan_timestamp_seconds.labels(repository_id, repository).set(mktime(datetime.now().timetuple()))
    last_modified_timestamp_seconds.labels(repository_id, repository).set(mktime(parser.parse(info['repository']['last_modified']).timetuple()))
    encryption_mode.labels(repository_id, repository).state(info['encryption']['mode'])
    
    stats = info['cache']['stats']
    chunks_count.labels(repository_id, repository).set(stats['total_chunks'])
    compressed_size_bytes.labels(repository_id, repository).set(stats['total_csize'])
    size_bytes.labels(repository_id, repository).set(stats['total_size'])
    unique_chunks_count.labels(repository_id, repository).set(stats['total_unique_chunks'])
    unique_compressed_size_bytes.labels(repository_id, repository).set(stats['unique_csize'])
    unique_size_bytes.labels(repository_id, repository).set(stats['unique_size'])

    last = info['archives'][0]
    latest_archive_info.labels(repository_id, repository).info({
        'id': last['id'],
        'name': last['name'],
        'comment': last['comment'],
        'hostname': last['hostname'],
        'command_line': ' '.join(str(x) for x in last['command_line']),
        'chunker_params': ','.join(str(x) for x in last['chunker_params']),
        'username': last['username'],
        'hostname': last['hostname']
    })
    latest_archive_duration_seconds.labels(repository_id, repository).set(last['duration'])
    latest_archive_start_timestamp_seconds.labels(repository_id, repository).set(mktime(parser.parse(last['start']).timetuple()))
    latest_archive_end_timestamp_seconds.labels(repository_id, repository).set(mktime(parser.parse(last['end']).timetuple()))
    latest_archive_compressed_size_bytes.labels(repository_id, repository).set(last['stats']['compressed_size'])
    latest_archive_deduplicated_size_bytes.labels(repository_id, repository).set(last['stats']['deduplicated_size'])
    latest_archive_nfiles_count.labels(repository_id, repository).set(last['stats']['nfiles'])
    latest_archive_original_size_bytes.labels(repository_id, repository).set(last['stats']['original_size'])
    latest_archive_limits_archive_size_ratio.labels(repository_id, repository).set(last['limits']['max_archive_size'])

if __name__ == '__main__':
    http_port = os.getenv('PROMETHEUS_EXPORTER_HTTP_PORT', 9401)
    rescan_interval = int(os.getenv('PROMETHEUS_EXPORTER_RESCAN_INTERVAL_SECONDS', 1800))
    repository = os.getenv('BORG_REPOSITORY', '/var/lib/borg/repo')
    allow_initial_scan_failure = bool(os.getenv('PROMETHEUS_EXPORTER_ALLOW_INITIAL_SCAN_FAILURE', False))
    exit_on_failure = bool(os.getenv('PROMETHEUS_EXPORTER_EXIT_ON_FAILURE', False))
    
    print("http port: {}".format(http_port))
    print("repository: {}".format(repository))
    print("rescan interval: {}s".format(rescan_interval))

    print("performing inital repository scan")
    try:
        scan_repository(repository)
        print("inital repository finished successfully")
    except Exception as e:
        if not allow_initial_scan_failure:
            raise e
        else:
            print("failure during initial scan, but PROMETHEUS_EXPORTER_ALLOW_INITIAL_SCAN_FAILURE is set, so ignoring. Message was: {}".format(str(e)))

    print("starting http server")
    http_server = start_http_server(http_port)
    print("http server up.")

    try:
        while True:
            print("next rescan scheduled for {}".format((datetime.now() + timedelta(seconds = rescan_interval)).strftime('%Y-%m-%d %H:%M:%S %z')))
            sleep(rescan_interval)
            print("re-scanning borg repository")
            try:
                scan_repository(repository)
                print("rescan finished successfully")
            except subprocess.CalledProcessError as e:
                print("rescan failed with returncode={} and stderr: {}".format(e.returncode, e.stderr))
                scan_returncode.labels(repository).set(e.returncode)
                if exit_on_failure:
                    raise e
            except BorgRepositoryLockedError:
                print("repository is currently locked. will try again later")
    except KeyboardInterrupt:
        print("interrupted and stopped.")
