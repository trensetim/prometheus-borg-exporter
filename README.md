# prometheus-borg-exporter

a simple borg backup exporter for prometheus.

See the [example docker-compose.yaml](docker-compose.yaml) for how to use.

## Exported metrics

| metric name                                              | type   | description |
| ------------                                             | ------ | ----------- |
| borg_repository_successful_scan_timestamp_seconds        | gauge  | UNIX timestamp of the last successful scan of the repository |
| borg_repository_scan_timestamp_seconds                   | gauge  | UNIX timestamp of the last scan of the repository, successful or not |
| borg_repository_scan_returncode                          | gauge  | Return code (exitcode) of the borg info subprocess used for scanning the repository. Zero if successfully scanned. |
| borg_repository_scan_info                                | gauge  | Information about the last scan of the repository. Even if scan failed. |
| borg_repository_locked                                   | gauge  | Whether the repository is currently locked (1=yes, 0=no) |
| borg_repository_chunks_count                             | gauge  | Number of chunks |
| borg_repository_compressed_size_bytes                    | gauge  | Total compressed and encrypted size of all chunks multiplied with their reference counts in bytes |
| borg_repository_size_bytes                               | gauge  | Total uncompressed size of all chunks multiplied with their reference counts |
| borg_repository_unique_chunks_count                      | gauge  | Number of unique chunks |
| borg_repository_unique_compressed_size_bytes             | gauge  | Compressed and encrypted size of all chunks in bytes |
| borg_repository_unique_size_bytes                        | gauge  | Uncompressed size of all chunks |
| borg_repository_last_modified_timestamp_seconds          | gauge  | Last modified UNIX timestamp |
| borg_repository_encryption_mode                          | enum   | Encryption mode of the repository: 'none', 'repokey', 'keyfile', 'authenticated', 'keyfile-blake2', 'repokey-blake2', 'authenticated-blake2' |
| borg_repository_latest_archive_info                      | info   | Information about the latest/last archive/backup stored in the repository: {id,name,comment,hostname,command_line,chunker_params,username,hostname} |
| borg_repository_latest_archive_duration_seconds          | gauge  | Seconds it took to create the latest archive |
| borg_repository_latest_archive_start_timestamp_seconds   | gauge  | UNIX timestamp when the creation of the latest archive was initiated |
| borg_repository_latest_archive_end_timestamp_seconds     | gauge  | UNIX timestamp when the creation of the latest archive was completed |
| borg_repository_latest_archive_compressed_size_bytes     | gauge  | Size after compression in bytes |
| borg_repository_latest_archive_deduplicated_size_bytes   | gauge  | Deduplicated size (against the current repository, not when the archive was created) in bytes |
| borg_repository_latest_archive_nfiles_count              | gauge  | Number of regular files in the archive |
| borg_repository_latest_archive_original_size_bytes       | gauge  | Size of files and metadata before compression in bytes |
| borg_repository_latest_archive_limits_archive_size_ratio | gauge  | Float between 0 and 1 describing how large this archive is relative to the maximum size allowed by Borg |

All metrics come with the labels `repository_name` with the name (aka path) of the repository.
All metrics (except possible non-successful-scan metrics `borg_repository_scan_timestamp_seconds`, `scan_returncode`, `borg_repository_scan_info`, `borg_repository_locked`) come with the label `repository_id` too.

## Configuration

The configuration is done by environment variables.
For boolean configuration options, the values are case-sensitive, python-style `True` or `False`!

| environmental variable                      | default | description |
| ------------                                | ------- | ----------- |
| PROMETHEUS_EXPORTER_HTTP_PORT               | 9401    | HTTP port number of the prometheus exporter |
| PROMETHEUS_EXPORTER_RESCAN_INTERVAL_SECONDS | 1800    | How often to run `borg info` on the repository, default is 30 minutes |
| BORG_REPOSITORY                             | `/var/lib/borg/repo`    | The path to the repository |
| BORG_REPOSITORY_NAME                        | `null`  | If set, becomes the `repository_name` label in the exported metrics. Defaults to `BORG_REPOSITORY` |
| BORG_RSH                                    | < unset >    | See [the borg documentation](https://borgbackup.readthedocs.io/en/stable/usage/general.html) for any env variable you may want to set |
| BORG_RELOCATED_REPO_ACCESS_IS_OK            | `True`  | See [the borg documentation](https://borgbackup.readthedocs.io/en/stable/usage/general.html) |
| BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK  | `True`  | See [the borg documentation](https://borgbackup.readthedocs.io/en/stable/usage/general.html) |
| BORG_BYPASS_LOCK                            | `True`  | See [the borg documentation on --bypass-lock](https://borgbackup.readthedocs.io/en/stable/usage/general.html#common-options) |
| PROMETHEUS_EXPORTER_ALLOW_INITIAL_SCAN_FAILURE | `False` | set to `True` if you want to allow the initial repository scan to fail (maybe if the repo is expected to possibly be locked on startup) |
| PROMETHEUS_EXPORTER_EXIT_ON_FAILURE         | `False`  | set to `True` if you want the exporter to exit on any failure (except `repository is locked`) AFTER the initial scan |
| PROMETHEUS_EXPORTER_DEBUG                   | `False`  | set to `True` if you want more logging |

## Hints

When accessing a remote repository via `ssh` in a running docker container, you probably want to mount your `id_rsa` and `known_hosts` to within `/home/prometheus-borg-exporter/.ssh`.

## Authors and acknowledgment
Special thanks to [this repository and its author](https://code.recycled.cloud/RecycledCloud/prometheus-borgbackup-exporter) for laying the groundwork.
