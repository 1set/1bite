#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck source=1bite
source "$ROOT/1bite"
activate_paths
configure_downloads
check_git_configuration

while IFS= read -r -u 3 package; do
  [[ -n "$package" ]] || continue
  installed_formula_ref "$package" >/dev/null
  probe_formula "$package"
done 3<"$ROOT/config/formulae.txt"

while IFS=$'\t' read -r -u 3 package app; do
  [[ -n "$package" ]] || continue
  if [[ "$package" == claude-desktop && "$WITH_CLAUDE" != true ]]; then continue; fi
  if [[ "${ONE_BITE_ALLOW_PREPARED_DESKTOPS:-}" == 1 ]] && manual_desktop "$package" && ! app_healthy "$app"; then
    python3 "$ROOT/scripts/desktop.py" "$package" --verify-prepared
    echo "Prepared for manual installation: $app (not installed or not yet healthy)."
    continue
  fi
  app_healthy "$app"
  /usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$(app_path "$app")/Contents/Info.plist"
done 3<"$ROOT/config/casks.tsv"

while IFS=$'\t' read -r -u 3 package filename; do
  [[ -n "$package" ]] || continue
  font_cask_healthy "$package" "$filename"
done 3<"$ROOT/config/font-casks.tsv"

for executable in git git-lfs gh go node npm python3 uv rg duf fd bat fzf autojump zoxide jq yq tmux tree delta tig lazygit wget htop shellcheck shfmt ffmpeg magick fastfetch neofetch glow pop gum crush ob claude codex; do
  if [[ "$executable" == claude && "$WITH_CLAUDE" != true ]]; then continue; fi
  command -v "$executable"
done
git --version
git lfs version
gh --version
go version
go env GOPATH >/dev/null
go env GOBIN >/dev/null
node --version
npm --version
python3 --version
uv --version
if [[ "$WITH_CLAUDE" == true ]]; then claude --version; fi
codex --version
ob --help >/dev/null
if agent_healthy kiro-cli; then
  kiro-cli --version
  zsh -lic 'command -v kiro-cli'
elif [[ "${ONE_BITE_ALLOW_PREPARED_DESKTOPS:-}" == 1 ]]; then
  echo 'Kiro CLI app is installed; complete official onboarding to expose its terminal commands.'
else
  fail 'Complete Kiro CLI official onboarding, then rerun verification.'
fi
if [[ "$DESKTOP_MODE" == managed ]]; then
  python3 "$ROOT/scripts/kiro-shell.py" --verify --app "$(app_path 'Kiro CLI.app')"
  zsh -lic '(( $+functions[fig_preexec] && $+functions[fig_precmd] ))'
fi
if app_healthy Docker.app; then
  docker --version
  /Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose version
  /Applications/Docker.app/Contents/Resources/cli-plugins/docker-buildx version
  zsh -lic 'command -v docker'
fi
python3 "$ROOT/scripts/configure.py" --verify --config-dir "$CONFIG_DIR"
verify_editor
zsh -n "$HOME/.config/1bite/env.zsh"
zsh -n "$HOME/.config/1bite/shell.zsh"
export POWERLEVEL9K_DISABLE_CONFIGURATION_WIZARD=true
zsh -lic 'if [[ ${ZSH_THEME:-} == powerlevel10k/powerlevel10k ]]; then (( $+functions[p10k] )); fi'
if [[ "$WITH_CLAUDE" == true ]]; then zsh -lic 'command -v claude'; fi
# shellcheck disable=SC2016  # Expand these variables inside the clean login Zsh.
env -u DOCKER_DEFAULT_PLATFORM zsh -lic 'command -v codex && command -v go && command -v code && [[ -n $GOPATH ]] && [[ $DOCKER_DEFAULT_PLATFORM == linux/amd64 ]] || exit
if [[ -n ${GOBIN:-} ]]; then
  (( ${path[(Ie)$GOBIN]} )) || exit
else
  for setup_go in ${(s/:/)GOPATH}; do (( ${path[(Ie)$setup_go/bin]} )) || exit; done
fi'
python3 "$ROOT/scripts/runtime-smoke.py"
python3 "$ROOT/scripts/inventory.py"
echo 'Selected installation/preparation scope verified. Manual desktop installs and first launch remain separate.'
echo 'Docker engine readiness is checked separately by --docker-smoke.'
