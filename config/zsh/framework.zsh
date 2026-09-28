# Managed by 1bite: framework. Personal overrides belong after the source in .zshrc.
# An already loaded Oh My Zsh/theme keeps control of the prompt.
if (( ! $+functions[omz] )) && [[ -r "${ZSH:-$HOME/.oh-my-zsh}/oh-my-zsh.sh" ]]; then
  export ZSH="${ZSH:-$HOME/.oh-my-zsh}"
  if (( ! ${+ZSH_THEME} )); then
    if [[ -r "${ZSH_CUSTOM:-$ZSH/custom}/themes/powerlevel10k/powerlevel10k.zsh-theme" ]]; then
      ZSH_THEME=powerlevel10k/powerlevel10k
    else
      ZSH_THEME=robbyrussell
    fi
  fi
  (( ${+plugins} )) || plugins=(git)
  zstyle ':omz:update' mode disabled
  source "$ZSH/oh-my-zsh.sh"
fi
