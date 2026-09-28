# Managed by 1bite: terminal. Personal overrides belong after the source in .zshrc.
# Editor and paths
function cn {
  if (( $# )); then code -n "$@"; else code -n .; fi
}
alias cdiff='code -n --diff'
alias rp=realpath

# tmux: retain local ts=list and tn=new conventions alongside OMZ shortcuts.
alias t=tmux
alias ts='tmux ls'
alias ta='tmux attach -t'
alias tk='tmux kill-session -t'
function tn {
  if [[ -z $1 ]]; then
    tmux new-session
  else
    tmux new-session -s "$1"
  fi
}
for ((setup_tmux_index = 0; setup_tmux_index <= 16; setup_tmux_index++)); do
  alias ta$setup_tmux_index="tmux attach -t $setup_tmux_index"
done
unset setup_tmux_index
alias tl='tmux list-sessions'
alias tksv='tmux kill-server'
function tad {
  if [[ -z $1 || $1 == -* ]]; then tmux attach -d "$@"; else tmux attach -d -t "$@"; fi
}
function to {
  if [[ -z $1 || $1 == -* ]]; then tmux new-session -A "$@"; else tmux new-session -A -s "$@"; fi
}
function tkss {
  if [[ -z $1 || $1 == -* ]]; then tmux kill-session "$@"; else tmux kill-session -t "$@"; fi
}
function tmuxconf {
  local setup_tmux_config=${ZSH_TMUX_CONFIG:-}
  if [[ -z $setup_tmux_config ]]; then
    if [[ -f "$HOME/.tmux.conf" ]]; then
      setup_tmux_config="$HOME/.tmux.conf"
    elif [[ -f "${XDG_CONFIG_HOME:-$HOME/.config}/tmux/tmux.conf" ]]; then
      setup_tmux_config="${XDG_CONFIG_HOME:-$HOME/.config}/tmux/tmux.conf"
    else
      setup_tmux_config="$HOME/.tmux.conf"
    fi
  fi
  local -a setup_editor
  setup_editor=(${(z)${EDITOR:-vi}})
  "${(@Q)setup_editor}" "$setup_tmux_config"
}
function tds {
  local setup_tmux_hash setup_tmux_name
  if (( $+commands[md5] )); then
    setup_tmux_hash=$(printf '%s' "$PWD" | command md5 -q) || return
  else
    setup_tmux_hash=$(printf '%s' "$PWD" | command md5sum) || return
  fi
  setup_tmux_name="${PWD:t}"
  setup_tmux_name="${setup_tmux_name//[.:]/_}"
  tmux new-session -A -s "${setup_tmux_name:-root}-${setup_tmux_hash[1,6]}" "$@"
}

# Docker cleanup
if (( $+commands[docker] || $+functions[docker] )); then
  unalias dkclear 2>/dev/null || true
  function dkclear {
    docker system prune -f
  }
fi

# Misc
alias reload='. ~/.zshrc'
alias cls='clear'
alias e='exit'
alias ns=nslookup
alias weather='curl wttr.in'
alias webserver='python3 -m http.server'
function fingerprint {
  if [[ -z $1 ]]; then
    echo "missing target ssh key" >&2
    return 1
  fi
  ssh-keygen -E md5 -lf "$1" && ssh-keygen -E sha256 -lf "$1"
}
