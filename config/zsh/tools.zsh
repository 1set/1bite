# Managed by 1bite: tools. Personal overrides belong after the source in .zshrc.
# Native AutoJump owns j; zoxide retains its separate z / zi commands and database.
if (( $+commands[autojump] )); then
  setup_autojump="${commands[autojump]:A:h:h}/share/autojump/autojump.zsh"
  if [[ -r "$setup_autojump" ]]; then
    # Preserve personal functions, aliases and commands, and load the hook only once.
    if (( ! $+functions[j] && ! $+aliases[j] && ! $+commands[j] )); then
      () {
        setopt localoptions noaliases
        source "$1"
      } "$setup_autojump"
    fi
  fi
  unset setup_autojump
fi
if command -v zoxide >/dev/null; then
  setup_zoxide_init=$(zoxide init zsh) || return
  # Current zoxide ends its interactive completion block with a false feature
  # check when compdef is unavailable. That is a valid initialization result,
  # so append a successful no-op without hiding generation or syntax failures.
  eval "$setup_zoxide_init"$'\n:' || return
  unset setup_zoxide_init
fi
if [[ -t 0 && -t 1 ]] && (( $+commands[fzf] )); then
  if setup_fzf_init=$(command fzf --zsh 2>/dev/null) && [[ -n $setup_fzf_init ]]; then
    eval "$setup_fzf_init" || return
  else
    # fzf before 0.48 ships the same integration as files instead of --zsh.
    setup_fzf_shell="${commands[fzf]:A:h:h}/shell"
    [[ -r "$setup_fzf_shell/completion.zsh" ]] && source "$setup_fzf_shell/completion.zsh"
    [[ -r "$setup_fzf_shell/key-bindings.zsh" ]] && source "$setup_fzf_shell/key-bindings.zsh"
  fi
  unset setup_fzf_init setup_fzf_shell
fi
