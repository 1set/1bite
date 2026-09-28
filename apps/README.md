# Optional Docker apps

This directory is for useful services that can run locally with Docker. It is separate from the main One Bite installer: `./1bite` never starts, updates, or removes these apps. Each implemented app has its own launcher, private state directory, update procedure, recovery notes, and smoke test.

## Ready to run

| App | Use | Status |
| --- | --- | --- |
| [qBittorrent](qbittorrent/README.md) | Local download service with a LAN-accessible web interface | Includes an audited lifecycle wrapper, pinned initial image, persistent data layout, update backup, and end-to-end smoke test |

## Roadmap

These are ideas for future launchers, not features shipped by the current release.

| Priority | App | Useful for | What a future launcher must handle |
| --- | --- | --- | --- |
| Next | [Uptime Kuma](https://github.com/louislam/uptime-kuma) | Monitoring local services and publishing status pages | Persistent data, loopback/LAN binding, backup and restore, and a safe design that does not mount the Docker socket by default |
| Next | [Stirling-PDF](https://github.com/Stirling-Tools/Stirling-PDF) | Browser-based local PDF operations | Image pinning, resource limits, private file handling, and temporary-file cleanup |
| Next | [IT-Tools](https://github.com/CorentinTh/it-tools) | Local developer, encoding, network, and text utilities | Local-only binding by default, image pinning, and a lightweight health check |
| Next | [Forgejo](https://forgejo.org/docs/latest/admin/installation/docker/) | A private local Git forge | Database choice, SSH/HTTP ports, repositories outside the checkout, upgrades, and backups |
| Evaluate | [Paperless-ngx](https://docs.paperless-ngx.com/setup/#docker) | Searchable local document archive and OCR | Import/export paths, OCR languages, database and broker lifecycle, private documents, and full disaster recovery |
| Evaluate | [Immich](https://immich.app/docs/install/docker-compose/) | Private photo and video backup | Large external libraries, database backups, machine-learning images, hardware resources, mobile onboarding, and upstream's strict upgrade path |
| Evaluate | [FreshRSS](https://github.com/FreshRSS/FreshRSS/tree/edge/Docker) | Private RSS reader | Account initialization, database choice, OPML backup, scheduled refresh, and LAN-only defaults |
| Evaluate | [SearXNG](https://docs.searxng.org/admin/installation-docker.html) | Private metasearch for a trusted local network | Secret generation, rate limits, engine drift, outbound privacy, and no public exposure by default |
| Evaluate | [n8n](https://docs.n8n.io/hosting/installation/docker/) | Local workflow automation | Encryption keys, credentials, database backup, webhook exposure, queue mode, and upgrade migrations |

Password vaults, home-automation controllers, and Docker management dashboards are deliberately deferred. They either hold unusually sensitive data, depend on host networking/device discovery, or commonly require Docker socket access. Jellyfin is also deferred because upstream does not support its container on macOS and identifies hardware acceleration and library scanning problems there. A one-click launcher needs a stronger threat model and recovery story before it belongs here.

### Planned installer integration

The main installer may later gain an **explicit** app catalog/list mode and per-app delegation. It must never start a service during the default Mac setup. A normal repeated app command should converge configuration and restart only when required; it must not pull a moving image. Image changes remain an explicit `update` action that compares resolved digests, backs up private state, switches atomically where possible, verifies health, and retains rollback data. This is a roadmap contract, not a command available in this release.

An app moves into **Ready to run** only after its launcher meets the same baseline as qBittorrent:

- supports `init`, `start`, `stop`, `restart`, `status`, `logs`, `check`, and an explicit `update` flow;
- pins its initial image by digest and supports Apple Silicon;
- stores configuration and user data outside the source checkout;
- makes `init` and `start` safe to repeat, preserves unknown user settings, and does not pull or reset state on an ordinary rerun;
- makes `update` compare the current and candidate image digests, preserve the running service after a pull failure, back up before a switch, verify the new service, and document rollback;
- avoids embedded credentials, privileged mode, host networking, and Docker socket access unless the feature strictly requires it and the risk is documented;
- preserves data across reruns, backs up state before a schema-changing update, and documents rollback;
- includes a smoke test that uses isolated temporary state and removes only its own resources.

Candidate scripts are intentionally absent until those requirements are implemented and tested. Use each upstream project's official Docker instructions if you want to evaluate it now.
