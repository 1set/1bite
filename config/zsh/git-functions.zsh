# Managed by 1bite: Git functions. Personal overrides belong after the source in .zshrc.
# Git helpers with validation; these replace the plain gci/gcia aliases.
unalias gci gcia 2>/dev/null || true
function gci {
  if [[ -z $1 ]]; then echo "missing commit message" >&2; return 1; fi
  git commit -a -m "$*"
}
function gcia {
  if [[ -z $1 ]]; then echo "missing commit message" >&2; return 1; fi
  git commit --amend -a -m "$*"
}
alias dif='git diff --no-index'
alias gmd='git checkout master && git pull && git remote prune origin'
function git_corb {
  if [[ -z $1 ]]; then
    echo "missing remote branch name for 'git checkout remote branch'" >&2
    return 1
  fi
  git checkout -b "$1" origin/"$1"
}
function git_ignore {
  local name=.gitignore
  if [[ -z $1 ]]; then
    local curdir="$(pwd)"
    echo "/${curdir##*/}" >>"$name"
  else
    echo "$1" >>"$name"
  fi
  git add "$name"
}
function git_readme {
  local name=README.md
  if [[ -z $1 ]]; then
    local curdir="$(pwd)"
    echo "# ${curdir##*/}" >>"$name"
  else
    echo "$1" >>"$name"
  fi
  git add "$name"
}
