# Managed by 1bite: general utilities. Personal overrides belong after the source in .zshrc.
function gpre { git status && git add --all && git diff --staged -w "$@"; }
function gps1 {
  local branch
  branch=$(git symbolic-ref --quiet --short HEAD) || return
  git push --set-upstream origin "$branch" "$@"
}

function mkcd { [[ $# == 1 && -n $1 ]] || { print -u2 "usage: mkcd <directory>"; return 1; }; mkdir -p -- "$1" && cd -- "$1"; }
function mcd { mkcd "$@"; }

# Directory stack, Oh My Zsh compatible; redefined here so it also works without OMZ.
unalias d 2>/dev/null || true
function d {
  if [[ -n $1 ]]; then
    dirs "$@"
  else
    dirs -v | head -n 10
  fi
}

# Files and directories
function cdf {
  if [[ -d $1 ]]; then
    cd -- "$1"
  else
    cd -- "$(dirname "$1")"
  fi
}
function o {
  if [[ $# -lt 1 ]]; then
    open .
  else
    open "$1"
  fi
}
function dl {
  case $# in
    2) curl --fail --location --output "$2" -- "$1" ;;
    1) curl --fail --location --remote-name -- "$1" ;;
    *) echo "usage: dl <url> [output]" >&2; return 1 ;;
  esac
}
function mktgz {
  if [[ -z $1 ]]; then echo "missing source target" >&2; return 1; fi
  tar cvzf "${1%%/}.tgz" "${1%%/}/"
}
function mkzip {
  if [[ -z $1 ]]; then echo "missing source target" >&2; return 1; fi
  zip -r -8 "${1%%/}.zip" "$1"
}
function tfind {
  if [[ -z $1 ]]; then echo "missing target keyword" >&2; return 1; fi
  echo "Searching for '$*'"
  rg --ignore-case --fixed-strings --glob '*.txt' --glob '*.md' -- "$*" .
}
function ff {
  setopt localoptions pipefail
  local target=${1:-.}
  [[ -d $target ]] || { print -u2 "not a directory: $target"; return 1; }
  command du -k -d 1 -- "$target" 2>/dev/null | command sort -n | command awk '
    function human(k) {
      if (k >= 1073741824) return sprintf("%.1fT", k / 1073741824)
      if (k >= 1048576) return sprintf("%.1fG", k / 1048576)
      if (k >= 1024) return sprintf("%.1fM", k / 1024)
      return sprintf("%dK", k)
    }
    { size=$1; sub(/^[^[:space:]]+[[:space:]]+/, ""); printf "%8s  %s\n", human(size), $0 }
  '
}
alias trim="awk '{\$1=\$1;print}'"
alias lsp="find . -type f -not -path '*/\.git/*' | sed 's/^\.\///g' | sort"
alias lsmax="find . -type f -not -path '*/\.git/*' -print0 | xargs -0r stat -f '%z %N' | sort -nr | head -10"
alias lslast="find . -type f -not -path '*/\.git/*' -print0 | xargs -0r stat -f '%Sm %N' -t '%Y-%m-%d %T' | sort -nr | head -10"

# Viewing (jq, bat, glow)
function jv { jq <"$1" -C . | less -R; }
function jp { jq -M . "$1"; }
function jsonview { printf '%s\n' "$*" | jq -C -r .; }
alias ccat='bat --paging=never'
alias mcat='glow'
alias readme='glow README.md'

# Clipboard and clock; now uses local time, utcnow uses UTC.
alias ppwd='pwd | pbcopy ; pbpaste'
alias pd='basename "$PWD" | pbcopy ; pbpaste'
alias pc=pbcopy
alias pp=pbpaste
alias l2l='pbpaste | paste -sd " " - | pbcopy'
alias now='date "+%Y-%m-%d %H:%M:%S %Z" | pbcopy ; pbpaste'
alias utcnow='TZ=UTC date "+%Y-%m-%d %H:%M:%S %Z" | pbcopy ; pbpaste'
function pcat {
  if [[ -z $1 ]]; then echo "missing source target" >&2; return 1; fi
  cat -- "$@" | pbcopy
}

# Hashes and encoding
function sha1 { shasum -a 1 "$@"; }
function sha224 { shasum -a 224 "$@"; }
function sha256 { shasum -a 256 "$@"; }
function sha384 { shasum -a 384 "$@"; }
function sha512 { shasum -a 512 "$@"; }
function sha512224 { shasum -a 512224 "$@"; }
function sha512256 { shasum -a 512256 "$@"; }
alias b64e='base64'
alias b64d='base64 -d'
