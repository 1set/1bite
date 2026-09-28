# Troubleshooting and recovery

| Symptom | Action |
| --- | --- |
| Command Line Tools are missing | Complete the macOS installer prompt, then rerun the same command. |
| `The following taps are not trusted` | Homebrew 6 requires explicit trust for third-party taps. This does not mean the official Go install failed. One Bite neither trusts nor removes unrelated taps and trusts only the four selected Charm formulae. Trust another formula only when you choose to use it. |
| `curl: (92) HTTP/2 ... PROTOCOL_ERROR` | Rerun the installer. The managed download policy uses HTTP/1.1 while keeping HTTPS certificate checks. Add `http1.1` to your own file if you override `HOMEBREW_CURLRC`. |
| Stuck at `Would install` or a download for a long time | Inspect `network.tsv` for HTTP 000 or curl status 28 and read the later `run.log`. Homebrew may hide progress in logged mode. Stop with Ctrl+C, repair terminal network/proxy access, and rerun without clearing healthy tools or caches. |
| DNS, TLS, or download failure | Read `network.tsv` and the specific download error, repair network/proxy access, and rerun. Never disable TLS verification. |
| Insufficient sudo permission | Use a normal administrator account, complete the macOS authorization, and rerun without launching One Bite itself through sudo. |
| Formula is recorded but its command does not work | A rerun attempts repair. If it still fails, review that package's output and official Homebrew documentation. |
| Git or Git LFS reports `gitconfig: Permission denied` | Git cannot read configuration. Inspect the file and parent permissions as described below, then rerun. |
| Existing AI configuration is invalid | Repair the relevant JSON or TOML. The installer will not overwrite it. |
| An externally managed app is damaged | Repair it with its original installer; One Bite does not delete unknown apps. |
| Exit status 75 | Another process owns the session lock. Wait for it and do not delete `session.lock`. |
| `result.json` is absent | The previous run did not finish normally. Read events and run logs, then rerun; do not count it as success. |
| Docker engine is not running | Open Docker.app, complete first-run setup, wait for the engine, then run the smoke check. |
| A Docker build selects the wrong architecture | New shells default `DOCKER_DEFAULT_PLATFORM=linux/amd64`. Override it for one command, for example `DOCKER_DEFAULT_PLATFORM=linux/arm64 docker build ...`, or set a project-specific value before loading One Bite's environment. |
| iTerm2 reports duplicate Dynamic Profile GUIDs | Update One Bite and run `./1bite --configure-only`. The managed profile receives its current unique GUID while unrelated profile files are preserved. Reopen iTerm2 after the update. |
| New iTerm2 windows still use another profile | Run `./1bite --configure-only`, quit and reopen iTerm2, and confirm **Profiles > One Bite** exists. One Bite makes it the default once; if you later selected another default, reruns preserve your choice. |
| Powerlevel10k offers to download Meslo again | Open a new window with **Profiles > One Bite**. Existing windows retain their old font. Confirm the profile's Text font is MesloLGS Nerd Font, reopen iTerm2, then run `p10k configure` again without accepting a duplicate font download. |
| Ctrl+R does not open fzf history search | Open a new interactive terminal, run `type fzf-history-widget`, then `bindkey '^R'`. Rerun `./1bite --configure-only` if the widget is missing. One Bite supports both current `fzf --zsh` and older Homebrew shell integration files; personal bindings after the loader may intentionally override Ctrl+R. |

## Git configuration access

If Git LFS was installed and a later step reports `fatal: unable to access '/opt/homebrew/etc/gitconfig': Permission denied`, Git is failing to read system configuration. One Bite initializes LFS in the user scope; it does not run Homebrew's suggested `git lfs install --system`. A successful `git --version` does not prove the configuration is readable.

Current releases check Git from PATH, Homebrew's `bin/git` and `opt/git/bin/git`, and an explicit `HOMEBREW_GIT_PATH` before Homebrew installs, reinstalls, upgrades, or refreshes. The same check runs around Git and LFS setup and during verification. It preserves the original error and status, names the Git executable, and never prints configuration values, changes permissions, or bypasses system configuration. A configuration permission failure does not trigger a pointless Git reinstall. See the [Git configuration scopes](https://git-scm.com/docs/git-config).

`/opt/homebrew/etc/gitconfig` is persistent Homebrew configuration, not an extraction temporary file. Moving it into a temporary directory cannot repair access and can lose settings. The installer's `umask 022` gives new installer files normal permissions but cannot repair an existing root-owned file.

Inspect metadata without disclosing configuration contents:

```bash
ls -lde /opt/homebrew /opt/homebrew/etc /opt/homebrew/etc/gitconfig
```

If it is a regular file owned by the current user and only the owner read bit is missing, run `chmod u+r /opt/homebrew/etc/gitconfig`. If another account owns it, it is a symlink, an ACL denies access, or a parent directory cannot be traversed, an administrator must repair that exact object according to its real owner. Do not recursively chmod or chown Homebrew, run `sudo ./1bite`, or disable system configuration. Reinstalling Git or LFS does not necessarily fix an existing configuration file.

For a one-time incorrect owner on a regular file in a Homebrew tree managed by the current user, and only after confirming that no service manages the file, repair this file alone:

```bash
sudo chown "$(id -un)" /opt/homebrew/etc/gitconfig
ls -lde /opt/homebrew/etc/gitconfig
/opt/homebrew/bin/git config --list >/dev/null
./1bite
```

The read check discards output and preserves private values. Upgrading One Bite alone cannot change the file's permissions.

If the file becomes root-owned again, identify the writer instead of repeatedly changing ownership. A short trace shows metadata and lock-file operations without reading the file:

```bash
sudo fs_usage -w -f filesys -t 60 |
  awk 'index($0, "/opt/homebrew/etc/gitconfig") { print; fflush() }'
```

Run one controlled permission repair in another terminal, without running the installer. Look for creation of `gitconfig.lock`, chmod, and rename. Ordinary stat/open activity does not identify a writer, and the number after an `fs_usage` process name is a thread ID rather than necessarily a PID. A 60-second trace cannot exclude a periodic writer.

If a confirmed privileged process rewrites the file through Git as `root:admin` mode 600, and this Mac's administrators should read the system Git configuration, retain root ownership and grant only group read access after confirming membership:

```bash
/usr/sbin/dseditgroup -o checkmember -m "$(id -un)" admin
# Continue only after the command confirms membership.
sudo chmod g+r /opt/homebrew/etc/gitconfig
ls -lde /opt/homebrew/etc/gitconfig
/opt/homebrew/bin/git config --list >/dev/null
```

Mode 640 allows root to write, the admin group to read, and no other access. [Git's configuration writer](https://github.com/git/git/blob/master/config.c) copies the old permission bits to a lock file before atomic replacement, so a root writer can preserve mode 640. Observe the next real write and confirm ownership, mode, and Git readability. If the writer resets mode 600 or changes the group, repair that program's permission policy instead of installing an automatic chmod loop or disabling an unidentified service.

One Bite never automatically broadens system or private configuration permissions.

## Resume after interruption

Wait for all child processes from the earlier run, then rerun with the same options and log directory. Exit status 75 means the kernel lock is still held. `session.lock` intentionally remains after a normal run because its inode is persistent; its existence alone does not mean the session is locked.

A rerun checks real health, repairs an owned partial CLI install, and verifies or recovers a managed desktop-app replacement transaction. A complete, verified DMG may be reused. A run without `result.json` is incomplete. Personal configuration and damaged software from an unknown source are preserved. Network, storage, permissions, or an upstream installer's own lock can still require manual repair.
