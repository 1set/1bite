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

# Print a selected public key. Existing Ed25519, ECDSA and RSA defaults are
# preserved in that order; a new default is created only when this is invoked.
function sshkey {
  (( $# <= 1 )) || { print -u2 'usage: sshkey [private-key-or-public-key]'; return 1; }
  local private_key public_key selected_key='' candidate key_directory temporary
  if (( $# )); then
    if [[ $1 == *.pub ]]; then
      public_key=$1
      private_key=${1%.pub}
    else
      private_key=$1
      public_key="$1.pub"
    fi
  else
    for candidate in "$HOME/.ssh/id_ed25519" "$HOME/.ssh/id_ecdsa" "$HOME/.ssh/id_rsa"; do
      if [[ -e $candidate || -e "$candidate.pub" ]]; then
        selected_key=$candidate
        break
      fi
    done
    private_key=${selected_key:-$HOME/.ssh/id_ed25519}
    public_key="$private_key.pub"
  fi

  if [[ -f $public_key && -r $public_key ]]; then
    command cat -- "$public_key"
    return
  fi
  [[ ! -e $public_key ]] || { print -u2 "public key is not a readable file: $public_key"; return 1; }

  if [[ -f $private_key && -r $private_key ]]; then
    temporary=$(command mktemp "$public_key.1bite.XXXXXX") || return
    if ! command ssh-keygen -y -f "$private_key" >"$temporary"; then
      command rm -f -- "$temporary"
      return 1
    fi
    command chmod 644 "$temporary" || { command rm -f -- "$temporary"; return 1; }
    if [[ -e $public_key ]]; then
      command rm -f -- "$temporary"
    else
      command mv -- "$temporary" "$public_key" || { command rm -f -- "$temporary"; return 1; }
    fi
  elif [[ -e $private_key ]]; then
    print -u2 "private key is not a readable file: $private_key"
    return 1
  else
    key_directory=${private_key:h}
    if [[ ! -d $key_directory ]]; then
      [[ ! -e $key_directory ]] || { print -u2 "SSH key directory is not a directory: $key_directory"; return 1; }
      command mkdir -m 700 -p -- "$key_directory" || return
    fi
    print -u2 "Creating a passphrase-free Ed25519 key: $private_key"
    command ssh-keygen -q -t ed25519 -a 64 -N '' -f "$private_key" || return
  fi
  [[ -f $public_key && -r $public_key ]] || { print -u2 "public key was not created: $public_key"; return 1; }
  command cat -- "$public_key"
}

function pubkey {
  local public_key
  public_key=$(sshkey "$@") || return
  [[ -n $public_key ]] || { print -u2 'public key is empty'; return 1; }
  printf '%s\n' "$public_key" | command pbcopy || return
  print -r -- 'Public key copied to the clipboard.'
}
