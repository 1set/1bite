# Managed by 1bite. Personal overrides belong after the source in .zshrc.
source "${${(%):-%N}:A:h}/env.zsh"
[[ -o interactive ]] || return 0

setup_shell_directory="${${(%):-%N}:A:h}"
for setup_shell_module in framework options tools development utilities media git-functions terminal; do
  setup_shell_path="$setup_shell_directory/zsh/$setup_shell_module.zsh"
  [[ -r "$setup_shell_path" ]] || { print -u2 "1bite: missing Zsh module: $setup_shell_path"; return 1; }
  source "$setup_shell_path" || return
done
unset setup_shell_directory setup_shell_module setup_shell_path
