# Obsidian and the vault starter

One Bite installs Obsidian through the official Homebrew cask. It also installs a reviewed starter at `~/.config/1bite/obsidian-vault` and an `ob` command in `~/.local/bin`.

Create a vault in a new directory and open it:

```bash
ob ~/Documents/Notes/ProjectName --open
```

The destination must not already exist. Creation happens in a private adjacent staging directory followed by an atomic rename. A failure leaves no partial vault, and a rerun never overwrites a vault or personal changes. Without `--open`, the command prints a shell-safe `open -a Obsidian ...` command. Launch Obsidian once from Applications if macOS has not yet registered it.

## Included settings

The starter carries the portable vault choices from the reviewed reference configuration:

- show line numbers and use normal Markdown line-break behavior;
- create new notes in the current folder;
- keep attachments under `_attachments`;
- update internal links after a file is renamed or moved;
- enable the selected core navigation, graph, backlink, Canvas, properties, preview, daily-note, template, command-palette, bookmark, outline, word-count, recovery, Sync, and Bases features;
- use `_templates` as the template folder, with ISO dates and 24-hour times;
- select Tokyo Night and enable the `wide` CSS snippet.

The starter contains empty `_attachments` and `_templates` folders. It does not copy note content or opinionated note bodies.

Tokyo Night 1.1.7 is bundled with its MIT license so the selected appearance works immediately. Obsidian can update the installed theme through its normal Appearance settings. The small `wide` snippet increases the editor line width while readable line length is enabled.

The Sync core plugin is visible, but the starter contains no Obsidian account, remote vault, subscription, encryption key, or credentials. Sign in and choose a remote vault yourself if you use Obsidian Sync.

## Ownership and privacy

Each created vault is an ordinary folder that belongs to its user. Later One Bite configuration or update runs change only the managed starter used for future vaults. They never scan, merge, or replace an existing vault.

The starter excludes `.obsidian/workspace.json` and `.obsidian/workspaces.json`, which can reveal open files and local window state. It also excludes private notes, recent-file state, community plugins and their data, identity, organization names, and machine-specific paths. Its `.gitignore` keeps workspace state, Finder metadata, and Obsidian trash out of a vault repository.

To adopt a future starter change in an existing vault, compare the relevant `.obsidian` files and merge the setting deliberately after backing up that vault. Do not replace the whole configuration folder.

Obsidian stores vault settings in `.obsidian`, and any normal folder can be opened as a vault. See the official guides for [configuration folders](https://help.obsidian.md/configuration-folder), [managing vaults](https://help.obsidian.md/manage-vaults), [templates](https://help.obsidian.md/plugins/templates), and [data storage](https://help.obsidian.md/data-storage).
