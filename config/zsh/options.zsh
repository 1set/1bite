# Managed by 1bite: options. Personal overrides belong after the source in .zshrc.
bindkey -e
bindkey '^[[1;5D' backward-word
bindkey '^[[1;5C' forward-word
bindkey '^[[1;3D' backward-word
bindkey '^[[1;3C' forward-word
bindkey '^[b' backward-word
bindkey '^[f' forward-word
bindkey '^A' beginning-of-line
bindkey '^E' end-of-line
bindkey '^[[H' beginning-of-line
bindkey '^[[F' end-of-line
bindkey '^[[3~' delete-char
bindkey '^W' backward-kill-word
bindkey '^[^?' backward-kill-word

HISTFILE="$HOME/.zsh_history"
HISTSIZE=50000
SAVEHIST=50000
setopt append_history hist_ignore_dups share_history
