#!/usr/bin/env python

from prometheus_client import start_http_server, Gauge
from time import sleep, mktime
from dateutil import parser

import sys
import os
import json
import subprocess

HTTP_PORT = 9401
BACKUP_DIRECTORY = '/srv/backup'
INTERVAL = 30 * 60 # seconds

total_chunks        = Gauge('borg_repository_total_chunks', 'Number of chunks', ['name'])
total_csize         = Gauge('borg_repository_total_csize', 'Total compressed and encrypted size of all chunks multiplied with their reference counts', ['name'])
total_size          = Gauge('borg_repository_total_size', 'Total uncompressed size of all chunks multiplied with their reference counts', ['name'])
total_unique_chunks = Gauge('borg_repository_total_unique_chunks', 'Number of unique chunks', ['name'])
unique_csize        = Gauge('borg_repository_unique_csize', 'Compressed and encrypted size of all chunks', ['name'])
unique_size         = Gauge('borg_repository_unique_size', 'Uncompressed size of all chunks', ['name'])
last_modified       = Gauge('borg_repository_last_modified', 'Last modified UNIX timestamp', ['name'])


if __name__ == '__main__':
    if len(sys.argv) == 2:
        BACKUP_DIRECTORY = sys.argv[1]
    elif len(sys.argv) > 2:
        sys.exit("Invalid number of arguments. Usage: ./prometheus-borgbackup-exporter [backup-directory]")

    print("Backup directory is: {}".format(BACKUP_DIRECTORY))

    # Serve metrics over HTTP.
    print("Starting prometheus-orgbackup-exporter on port",
            "{}...".format(HTTP_PORT), end='')
    start_http_server(HTTP_PORT)
    print(" OK.")

    while True:
        print('=' * 72)
        entries = []
        try:
            print("> Scanning {} for borg repositories...".format(BACKUP_DIRECTORY), end='')
            entries = os.scandir(BACKUP_DIRECTORY)
            print(" OK")
        except Exception as e:
            print(" Error: {}".format(e))

        for entry in entries:
            if not entry.is_dir():
                print(">> Ignoring {} since it is not a directory.".format(entry.name))
            elif entry.name[0] == '.':
                print(">> Ignoring {} since it is a dot directory.".format(entry.name))
            else:
                repository_name = entry.name
                repository_path = entry.path

                try:
                    print(">> Querying borg for {}...".format(repository_name), end='')
                    env = os.environ
                    env["BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK"] = "yes"
                    raw_borg_json = subprocess.check_output(['borg', 'info', '--json', repository_path], env=env)
                    info = json.loads(raw_borg_json)

                    stats = info['cache']['stats']
                    total_chunks.labels(repository_name).set(stats['total_chunks'])
                    total_csize.labels(repository_name).set(stats['total_csize'])
                    total_size.labels(repository_name).set(stats['total_size'])
                    total_unique_chunks.labels(repository_name).set(stats['total_unique_chunks'])
                    unique_csize.labels(repository_name).set(stats['unique_csize'])
                    unique_size.labels(repository_name).set(stats['unique_size'])
                    last_modified.labels(repository_name).set(
                            mktime(parser.parse(info['repository']['last_modified']).timetuple()))


                    print(" OK")
                except Exception as e:
                    print(" Error: {}".format(e))

        print("> Waiting for next iteration - sleeping for {} seconds.".format(INTERVAL))
        sleep(INTERVAL)