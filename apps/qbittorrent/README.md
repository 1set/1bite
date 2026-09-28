# qBittorrent: a standalone download service for Mac

This is an optional One Bite app. The main `1bite` installer **never starts it automatically**, and this directory can be copied and used on its own. It requires a running Docker Desktop or compatible local Docker Engine, Docker Compose V2, and Python 3. It does not build an image or install Python packages.

## Start once, then use the lifecycle commands

Run these commands from this directory:

```bash
./qbt.sh start
# On first run, enter the administrator password twice without echo.
# The username is admin. Later runs preserve the account and Web UI settings.
```

Use `bash qbt.sh start` if an extracted ZIP did not preserve the executable bit. Do not use `sudo`.

| Command | Behavior |
| --- | --- |
| `./qbt.sh start` | Initialize on first use, start with the pinned image, apply Compose settings, and wait for the Web UI |
| `./qbt.sh stop` | Stop gracefully, waiting up to 60 seconds while preserving the container, jobs, configuration, and downloads |
| `./qbt.sh restart` | Stop and start again; recreate the container if it was removed |
| `./qbt.sh status` | Show containers, Web UI binding, actual data directory, and pinned image digest |
| `./qbt.sh logs` | Print the latest 100 container log lines and return to the terminal |
| `./qbt.sh check` | Check that the container is running and the Web UI responds; it does not test the password or inbound BitTorrent access |
| `./qbt.sh update` | Explicitly pull the official `latest` image; stop, back up configuration, and switch only when the digest changes |
| `./qbt.sh init` | Initialize local settings without starting the service |
| `./qbt.sh --help` | Show all options |

The password is never placed in the script, Compose environment, command arguments, or Git. Initial setup stores only a random salt and a PBKDF2-HMAC-SHA512 hash with 100,000 iterations and a 64-byte output. qBittorrent owns the account after initialization. Every new Mac requires its own password; there is no shared default.

Automation can use `--password-stdin` to read one line from a protected file or password manager. Do not put the password in command text, shell history, CI logs, or a shared directory.

## Web UI and LAN access

The default Web UI port is **1024**. Set a different value with `--port` during the first run.

| Purpose | Address or port |
| --- | --- |
| Web UI on this Mac | `http://127.0.0.1:1024` |
| Another device on the LAN | `http://<this-Mac-LAN-IPv4>:1024` |
| Web UI binding | `0.0.0.0:1024` by default, published on all Mac IPv4 interfaces |
| BitTorrent traffic | TCP and UDP 6881, independent of the Web UI port |
| Container restart policy | `unless-stopped`; Docker restores a previously running service but honors a manual stop |

Find the Mac's LAN IPv4 address under **System Settings > Network > current connection > Details > TCP/IP**. You can reserve that address through the router's DHCP settings. Other clients must be able to reach the Mac, and Docker and macOS firewall rules must allow the port. Guest Wi-Fi client isolation may block access.

```bash
# First run with a fixed port and interface address
./qbt.sh start --port 8024 --bind 192.168.1.20

# First run restricted to this Mac
./qbt.sh start --bind 127.0.0.1
```

The configuration keeps administrator login, CSRF protection, and Host Header validation enabled. A server-domain value of `*` permits access by LAN IP or hostname. It does not allow passwordless localhost or subnet access, privileged mode, host networking, or a Docker socket mount. The Web UI uses HTTP and is intended for a trusted LAN. Never forward its administration port to the public Internet.

Map TCP and UDP 6881 separately if inbound BitTorrent connectivity is required. Outbound peer connections can normally work without inbound forwarding, but this launcher does not promise external reachability.

Docker Desktop and the Mac must remain running. Downloads can pause while the Mac sleeps. The launcher does not change sleep, login-item, or firewall settings.

## Data locations on the Mac

The default layout is:

```text
~/Downloads/qBittorrent/                         -> /downloads
  complete/       completed files
  incomplete/     active data moved after completion

~/Library/Application Support/1bite/qbittorrent/
  settings.json   paths, ports, Docker context, and image digest
  config/                                       -> /config
    qBittorrent/  application settings, password hash, jobs, and resume data
  backups/        configuration backups created before an image switch
  operation.lock  operation mutex; the kernel releases it when the process exits
```

`/downloads/complete` is the **container path** to use in qBittorrent settings. Its Finder location is `~/Downloads/qBittorrent/complete`. Do not enter a `/Users/...` path in the Web UI because the container cannot see unmapped Mac directories. State and downloads remain separate. The container uses the current user UID and GID so downloaded files remain directly accessible on the Mac.

Prefer a local disk or a reliably attached external disk. Do not place active downloads, job state, or password hashes in Dropbox, iCloud, or Git. The source directory may be synchronized; runtime data does not move with it.

Select an external disk only during first-time setup:

```bash
./qbt.sh start --downloads '/Volumes/Media/qBittorrent'
```

Mount the physical volume first. The launcher rejects an unmounted `/Volumes/<name>` path instead of silently creating a same-named directory on the internal disk. If needed, allow the directory under **Docker Desktop Settings > Resources > File sharing**. Quote paths containing spaces. Symlinked paths are not supported. Later starts fail if the selected directory disappears rather than substituting an empty location.

## Reruns, changes, updates, and recovery

Every command reads the private `settings.json`; the source directory does not determine the data location. `start` does not pull `latest` or reset the password, download path, or jobs. The initial image is an official multi-architecture digest reviewed on 2026-09-12. ARM Docker uses `linux/arm64`, and x86 Docker uses `linux/amd64`. qBittorrent passes this platform explicitly, so a shell-wide `DOCKER_DEFAULT_PLATFORM` does not override the selected runtime architecture.

Operations sharing one state directory are mutually exclusive. Failures return a nonzero status and can be retried after the problem is fixed. The first run records the active local Docker context and later commands use it explicitly. Remote contexts are rejected so Mac paths cannot be mounted on another host. Do not operate on the same state with a separate Compose invocation. An interrupted first setup may resume if no container was created; an existing container with missing app configuration requires recovery instead of a silent credential reset.

**Change ports or binding:** stop the service, edit `web_port`, `bt_port`, or `bind` in the state directory's `settings.json`, then start it. The host port, container port, and `WEBUI_PORT` remain equal to avoid CSRF port failures. The BitTorrent port is used for TCP, UDP, and `TORRENTING_PORT`. Supplying different first-run options after settings exist is rejected to prevent an accidental migration.

**Move downloads:** stop the service, copy the whole download directory including `complete` and `incomplete`, verify the copy, edit the absolute `downloads` path in `settings.json`, then start and verify the jobs in the Web UI. The container path remains `/downloads`. Keep the original data until recovery is confirmed; the launcher does not copy or delete it.

**Update:** a pull failure leaves the running container untouched. An unchanged digest performs no switch. For a new digest, the launcher stops the service so resume data reaches disk, backs up the entire configuration and old settings under `backups/<timestamp>/`, records the new digest, and starts it. Downloads remain separate. A backup failure stops the update; the service may already be stopped and can be started or updated again after repair. Upstream migrations can still require manual recovery, so keep an independent backup of valuable data.

**Roll back:** stop the service, rename and retain the current configuration, restore both `config` and `settings.json` from the same timestamped backup, and start. The old digest is pulled automatically. Do not combine an old image with a newer configuration. Backups exclude downloaded files, and older job state may require a recheck in the Web UI.

**Back up or migrate to another Mac:** stop first, then back up both the state and download directories. On the new Mac, review absolute paths, UID/GID, Docker context, and architecture in `settings.json`. Initializing a fresh state and restoring app configuration while stopped is often clearer. Treat backups as private account data.

Neither `stop` nor the launcher deletes downloads. Choosing qBittorrent's **delete files** option in the Web UI does delete files in the mapped directory. Removing the script or container is not a backup.

## Verification and sources

```bash
python3 smoke-test.py
```

The smoke test uses a random password, temporary directories, an isolated Compose project, and temporary ports. It downloads a self-hosted 64 KiB torrent, verifies the mapped Mac file, rejects anonymous API access, changes the password, and confirms that repeated start, stop, restart, container recreation, update lookup, account state, and jobs are preserved. It removes only its own temporary containers and data.

The test's web seed uses a container loopback address and temporarily disables SSRF mitigation for the isolated test service; the setting is restored immediately after completion. Production configuration keeps qBittorrent's default SSRF protection. The test does not use public torrents, download third-party content, or test router port forwarding. Linux ARM/amd64 CI cannot replace testing Docker file sharing and LAN firewall behavior on the target Mac.

| Source | Purpose |
| --- | --- |
| [Requested Docker Hub image](https://hub.docker.com/r/linuxserver/qbittorrent) | LinuxServer image overview |
| [LinuxServer documentation](https://docs.linuxserver.io/images/docker-qbittorrent/) | Official registry, ARM64 support, PUID/PGID, ports, mounts, and update guidance |
| [qBittorrent password implementation](https://github.com/qbittorrent/qBittorrent/blob/master/src/base/utils/password.cpp) | PBKDF2 format and parameters |
| [qBittorrent preferences implementation](https://github.com/qbittorrent/qBittorrent/blob/master/src/base/preferences.cpp) | Web UI configuration keys |
| [qBittorrent Web API](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-5.0)) | Login, settings, and job verification; recent releases may return 204 and use port-scoped session cookies |
| [Docker Compose services](https://docs.docker.com/reference/compose-file/services/) | Bind mounts, restart policy, ports, and graceful stop behavior |

Maintenance entry points are `IMAGE` and `PIN` in `qbt.py`, plus `compose.yaml` and `smoke-test.py`. Run the real-image test again after changing the initial digest, password format, mounts, or port contract. The `update` command changes only private local settings; it does not modify the repository's initial digest.
