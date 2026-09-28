#!/bin/bash
# shellcheck disable=SC2034 # STEP_ACTION is consumed by 1bite's session logger.
# Functions are sourced by 1bite and the verifier; no work at source time.
omz_path() { printf '%s\n' "${ZSH:-$HOME/.oh-my-zsh}"; }

powerlevel10k_path() {
  local zsh_root custom
  zsh_root=$(omz_path)
  custom=${ZSH_CUSTOM:-$zsh_root/custom}
  printf '%s\n' "$custom/themes/powerlevel10k"
}

omz_healthy() {
  local directory=$1 file
  for file in oh-my-zsh.sh lib/git.zsh lib/cli.zsh themes/robbyrussell.zsh-theme plugins/git/git.plugin.zsh; do
    [[ -r "$directory/$file" ]] || return 1
  done
}

ensure_ohmyzsh() {
  local directory installer remote staging
  directory=$(omz_path)
  if omz_healthy "$directory"; then
    STEP_ACTION=skipped
    if [[ "$UPDATE" == true ]]; then
      remote=$(git -C "$directory" remote get-url origin)
      [[ "$remote" == https://github.com/ohmyzsh/ohmyzsh.git ]] || fail 'Update this Oh My Zsh fork with its original manager.'
      [[ -z $(git -C "$directory" status --porcelain) ]] || fail 'Oh My Zsh has local changes; preserve/resolve them before --update.'
      git -C "$directory" pull --ff-only
      STEP_ACTION=update-checked
    fi
  elif [[ -e "$directory" || -L "$directory" ]]; then
    fail 'Existing Oh My Zsh directory is incomplete. Repair the original installation; custom themes are preserved.'
  else
    installer=$(mktemp)
    download_installer ohmyzsh "$installer"
    mkdir -p "$(dirname "$directory")"
    staging=$(mktemp -d "$(dirname "$directory")/.1bite-omz-XXXXXX")
    # Keep a killed clone out of the final location; custom existing trees never
    # enter this path. Same-volume rename publishes only the complete checkout.
    ZSH="$staging/oh-my-zsh" KEEP_ZSHRC=yes CHSH=no RUNZSH=no /bin/sh "$installer" --unattended
    omz_healthy "$staging/oh-my-zsh" || fail 'Oh My Zsh staging checkout is incomplete.'
    [[ ! -e "$directory" && ! -L "$directory" ]] || fail 'Oh My Zsh appeared during installation; rerun to inspect it.'
    mv "$staging/oh-my-zsh" "$directory"
    rmdir "$staging"
    rm -f "$installer"
    STEP_ACTION=installed
  fi
  omz_healthy "$directory" || fail 'Oh My Zsh installation is incomplete.'
}

powerlevel10k_healthy() {
  local directory=$1
  [[ -r "$directory/powerlevel10k.zsh-theme" && -r "$directory/internal/p10k.zsh" ]]
}

ensure_powerlevel10k() {
  local directory remote current staging
  omz_healthy "$(omz_path)" || fail 'Install or repair Oh My Zsh before Powerlevel10k.'
  directory=$(powerlevel10k_path)
  remote=$(source_url powerlevel10k git)
  if powerlevel10k_healthy "$directory"; then
    STEP_ACTION=skipped
    if [[ "$UPDATE" == true ]]; then
      [[ ! -L "$directory" ]] || fail 'Powerlevel10k is a symlink; update it with its original dotfiles manager.'
      current=$(git -C "$directory" remote get-url origin)
      [[ "$current" == "$remote" ]] || fail 'Update this Powerlevel10k copy with its original manager.'
      [[ -z $(git -C "$directory" status --porcelain) ]] || fail 'Powerlevel10k has local changes; preserve/resolve them before --update.'
      git -C "$directory" pull --ff-only
      STEP_ACTION=update-checked
    fi
  elif [[ -e "$directory" || -L "$directory" ]]; then
    fail 'Existing Powerlevel10k path is incomplete. Repair it with its original manager; setup will not overwrite it.'
  else
    mkdir -p "$(dirname "$directory")"
    staging=$(mktemp -d "$(dirname "$directory")/.1bite-p10k-XXXXXX")
    git clone --depth=1 "$remote" "$staging/repository"
    powerlevel10k_healthy "$staging/repository" || fail 'Powerlevel10k staging checkout is incomplete.'
    [[ ! -e "$directory" && ! -L "$directory" ]] || fail 'Powerlevel10k appeared during installation; rerun to inspect it.'
    mv "$staging/repository" "$directory"
    rmdir "$staging"
    STEP_ACTION=installed
  fi
  powerlevel10k_healthy "$directory" || fail 'Powerlevel10k installation is incomplete.'
  if [[ ! -s "$HOME/.p10k.zsh" ]]; then MANUAL_STEPS="$MANUAL_STEPS powerlevel10k-configure"; fi
}

code_cli() {
  local app
  app=$(app_path 'Visual Studio Code.app')
  "$app/Contents/Resources/app/bin/code" "$@"
}

extension_installed() {
  local extension=$1 installed
  installed=$(code_cli --list-extensions) || fail 'Unable to enumerate VS Code extensions.'
  printf '%s\n' "$installed" | tr '[:upper:]' '[:lower:]' | grep -Fx "$extension" >/dev/null
}

ensure_extension() {
  local extension=$1
  if extension_installed "$extension"; then
    STEP_ACTION=skipped
    if [[ "$UPDATE" == true ]]; then
      code_cli --install-extension "$extension" --force
      STEP_ACTION=update-checked
    fi
  else
    code_cli --install-extension "$extension"
    STEP_ACTION=installed
  fi
  extension_installed "$extension" || fail "VS Code extension is missing: $extension"
}

install_extensions() {
  local extension
  while IFS= read -r -u 3 extension; do
    [[ -n "$extension" ]] || continue
    step_run "vscode:$extension" ensure_extension "$extension"
  done 3<"$ROOT/config/vscode-extensions.txt"
}

verify_editor() {
  local extension
  omz_healthy "$(omz_path)" || fail 'Oh My Zsh is missing/incomplete.'
  powerlevel10k_healthy "$(powerlevel10k_path)" || fail 'Powerlevel10k is missing/incomplete.'
  while IFS= read -r -u 3 extension; do
    [[ -n "$extension" ]] || continue
    extension_installed "$extension" || fail "VS Code extension is missing: $extension"
  done 3<"$ROOT/config/vscode-extensions.txt"
}
