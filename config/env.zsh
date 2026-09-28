# Public environment only. Never put credentials or proxy values in this file.
typeset -U path
for setup_brew in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  if [[ -x "$setup_brew" ]]; then
    eval "$("$setup_brew" shellenv)"
    break
  fi
done
unset setup_brew
path=("$HOME/.local/bin" /Applications/Docker.app/Contents/Resources/bin $path)

# Produce portable x86-64 Linux images by default on Apple Silicon. A project
# or one-off command can set a different platform before loading this file.
export DOCKER_DEFAULT_PLATFORM="${DOCKER_DEFAULT_PLATFORM:-linux/amd64}"

# Export the effective Go workspace as well as its binary directory. Respect an
# existing shell override and Go's persisted `go env -w GOPATH/GOBIN` values.
if [[ -z ${GOPATH:-} ]]; then
  setup_go_path=''
  (( $+commands[go] )) && setup_go_path=$(command go env GOPATH 2>/dev/null)
  export GOPATH="${setup_go_path:-$HOME/go}"
  unset setup_go_path
else
  export GOPATH
fi
if [[ -n ${GOBIN:-} ]]; then
  export GOBIN
  path+=("$GOBIN")
else
  setup_go_bin=''
  # Go 1.27 may report the first GOPATH/bin as a derived GOBIN. Read GOENV so
  # only an explicit `go env -w GOBIN=...` overrides the documented GOPATH bins.
  if (( $+commands[go] )); then
    setup_go_env=$(command go env GOENV 2>/dev/null)
    if [[ -r $setup_go_env ]]; then
      while IFS= read -r setup_go_setting; do
        case $setup_go_setting in
          GOBIN=*) setup_go_bin=${setup_go_setting#GOBIN=} ;;
        esac
      done <"$setup_go_env"
    fi
    unset setup_go_env setup_go_setting
  fi
  if [[ -n $setup_go_bin ]]; then
    export GOBIN="$setup_go_bin"
    path+=("$setup_go_bin")
  else
    for setup_go in ${(s/:/)GOPATH}; do path+=("$setup_go/bin"); done
    unset setup_go
  fi
  unset setup_go_bin
fi
for setup_code in /Applications/'Visual Studio Code.app'/Contents/Resources/app/bin "$HOME/Applications/Visual Studio Code.app/Contents/Resources/app/bin"; do
  [[ -x "$setup_code/code" ]] && path+=("$setup_code")
done
unset setup_code
export PATH
