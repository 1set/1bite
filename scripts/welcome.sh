#!/bin/bash
# Bootstrap-safe terminal branding. Keep this usable before Homebrew or Python.

welcome_color() {
  local red=$1 green=$2 blue=$3
  if [[ "${UI_COLOR:-false}" == true ]]; then
    printf '\033[38;2;%s;%s;%sm' "$red" "$green" "$blue"
  fi
}

welcome_reset() {
  if [[ "${UI_COLOR:-false}" == true ]]; then printf '\033[0m'; fi
}

welcome_bold() {
  if [[ "${UI_COLOR:-false}" == true ]]; then printf '\033[1m'; fi
}

welcome_should_show() {
  case "${ONE_BITE_BANNER:-auto}" in
    auto) [[ -t 1 && ${TERM:-dumb} != dumb && -z ${CI:-}${GITHUB_ACTIONS:-} ]] ;;
    always) return 0 ;;
    never) return 1 ;;
    *)
      echo 'ERROR: ONE_BITE_BANNER must be auto, always or never.' >&2
      return 2
      ;;
  esac
}

welcome_system_value() {
  local kind=$1 value=unknown brew_command='' memory_bytes=0 formulae=0 casks=0
  case "$kind" in
    os)
      if [[ $(uname -s) == Darwin ]]; then
        value="macOS $(sw_vers -productVersion 2>/dev/null || printf unknown)"
      else
        value="$(uname -s) $(uname -r)"
      fi
      ;;
    model)
      if [[ $(uname -s) == Darwin ]]; then
        value=$(sysctl -n hw.model 2>/dev/null || printf unknown)
      else
        value=$(uname -m)
      fi
      ;;
    chip)
      if [[ $(uname -s) == Darwin ]]; then
        value=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || printf unknown)
      else
        value=$(uname -m)
      fi
      ;;
    memory)
      if [[ $(uname -s) == Darwin ]]; then
        memory_bytes=$(sysctl -n hw.memsize 2>/dev/null || printf 0)
        if [[ "$memory_bytes" =~ ^[0-9]+$ && "$memory_bytes" -gt 0 ]]; then
          value="$(((memory_bytes + 536870912) / 1073741824)) GiB"
        fi
      elif command -v getconf >/dev/null 2>&1; then
        memory_bytes=$(($(getconf _PHYS_PAGES 2>/dev/null || printf 0) * $(getconf PAGE_SIZE 2>/dev/null || printf 0)))
        if [[ "$memory_bytes" -gt 0 ]]; then value="$(((memory_bytes + 536870912) / 1073741824)) GiB"; fi
      fi
      ;;
    shell) value=${SHELL##*/} ;;
    terminal) value=${TERM_PROGRAM:-${TERM:-unknown}} ;;
    homebrew)
      if command -v brew >/dev/null 2>&1; then
        brew_command=$(command -v brew)
      elif [[ -x /opt/homebrew/bin/brew ]]; then
        brew_command=/opt/homebrew/bin/brew
      elif [[ -x /usr/local/bin/brew ]]; then
        brew_command=/usr/local/bin/brew
      fi
      if [[ -n "$brew_command" ]]; then
        formulae=$("$brew_command" list --formula 2>/dev/null | wc -l | tr -d ' ')
        casks=$("$brew_command" list --cask 2>/dev/null | wc -l | tr -d ' ')
        value="$formulae formulae, $casks casks"
      else
        value='not installed yet'
      fi
      ;;
    fetch)
      value=none
      if command -v neofetch >/dev/null 2>&1; then value=neofetch; fi
      if command -v fastfetch >/dev/null 2>&1; then
        if [[ "$value" == none ]]; then value=fastfetch; else value="$value + fastfetch"; fi
      fi
      ;;
  esac
  value=${value//$'\n'/ }
  value=${value//$'\r'/ }
  printf '%s' "${value:-unknown}"
}

welcome_info_line() {
  local label=$1 value=$2 accent reset
  accent=$(welcome_color 255 205 70)
  reset=$(welcome_reset)
  printf '%s%s:%s %s' "$accent" "$label" "$reset" "$value"
}

welcome_art_line() {
  local art=$1 red=$2 green=$3 blue=$4 info=${5:-} width=${6:-24} padding color reset
  color=$(welcome_color "$red" "$green" "$blue")
  reset=$(welcome_reset)
  padding=$((width - ${#art}))
  if [[ "$padding" -lt 1 ]]; then padding=1; fi
  printf '%s%s%s%*s' "$color" "$art" "$reset" "$padding" ''
  if [[ -n "$info" ]]; then printf '%s' "$info"; fi
  printf '\n'
}

welcome_wordmark_line() {
  local left=$1 right=$2 row=$3 padding left_color right_color reset
  reset=$(welcome_reset)
  case "$row" in
    1)
      left_color=$(welcome_color 255 188 73)
      right_color=$(welcome_color 255 61 132)
      ;;
    2)
      left_color=$(welcome_color 255 133 82)
      right_color=$(welcome_color 235 35 177)
      ;;
    3)
      left_color=$(welcome_color 255 81 112)
      right_color=$(welcome_color 193 48 218)
      ;;
    4)
      left_color=$(welcome_color 239 42 164)
      right_color=$(welcome_color 132 69 244)
      ;;
    5)
      left_color=$(welcome_color 187 52 218)
      right_color=$(welcome_color 72 112 252)
      ;;
    *)
      left_color=$(welcome_color 116 76 242)
      right_color=$(welcome_color 43 187 247)
      ;;
  esac
  padding=$((25 - ${#left}))
  if [[ "$padding" -lt 2 ]]; then padding=2; fi
  printf '%s%s%s%*s%s%s%s\n' "$left_color" "$left" "$reset" "$padding" '' "$right_color" "$right" "$reset"
}

welcome_wordmark() {
  welcome_wordmark_line '   ▄▄▄▄' '▄▄▄' 1
  welcome_wordmark_line ' ▄█▀▀████▄' '██▀▀█▄    █▄' 2
  welcome_wordmark_line ' ██    ██ ▄' '██ ▄█▀ ▀▀▄██▄' 3
  welcome_wordmark_line ' ██    ██ ████▄ ▄█▀█▄' '██▀▀█▄ ██ ██ ▄█▀█▄' 4
  welcome_wordmark_line ' ██    ██ ██ ██ ██▄█▀' '██  ▄█ ██ ██ ██▄█▀' 5
  welcome_wordmark_line '  ▀████▀ ▄██ ▀█▄▀█▄▄▄' '██████▀▄██▄██▄▀█▄▄▄' 6
}

welcome_compact() {
  local reset subtitle
  reset=$(welcome_reset)
  subtitle="$(welcome_bold)$(welcome_color 255 78 151)One Bite${reset}  ·  First bite for a ready Mac  ·  v$(cat "$ROOT/VERSION")"
  printf '\n'
  welcome_wordmark
  welcome_art_line '  ░▒▓▒░' 255 78 151 "$subtitle" 11
  printf '\n'
}

welcome_full() {
  local reset title
  reset=$(welcome_reset)
  title="$(welcome_bold)$(welcome_color 255 78 151)One Bite${reset}  ·  First bite for a ready Mac  ·  v$(cat "$ROOT/VERSION")"
  printf '\n'
  welcome_wordmark
  printf '\n'
  welcome_art_line '    ░▄▓▄' 255 178 71 "$title" 14
  welcome_art_line '     ▀▓░' 255 106 88 "$(welcome_info_line 'macOS' "$(welcome_system_value os)")" 14
  welcome_art_line '  ░▓▓▓▓▒' 255 45 128 "$(welcome_info_line 'Model' "$(welcome_system_value model)")" 14
  welcome_art_line ' ▒▓▓▓▓  ░' 224 32 185 "$(welcome_info_line 'Chip' "$(welcome_system_value chip)")" 14
  welcome_art_line ' ▓▓▓▓▓ ░' 151 60 235 "$(welcome_info_line 'Memory' "$(welcome_system_value memory)")" 14
  welcome_art_line '  ▀▓▓▓▒' 78 106 250 "$(welcome_info_line 'Shell' "$(welcome_system_value shell)")" 14
  welcome_art_line '' 39 150 255 "$(welcome_info_line 'Terminal' "$(welcome_system_value terminal)")" 14
  welcome_art_line '' 29 196 239 "$(welcome_info_line 'Homebrew' "$(welcome_system_value homebrew)")" 14
  welcome_art_line '' 28 215 211 "$(welcome_info_line 'Fetch tools' "$(welcome_system_value fetch)")" 14
  printf '\n'
  printf 'Run %s for this card at any time.\n' "$(welcome_color 66 214 255)./1bite --welcome${reset}"
  printf 'Run %s or %s for their native system views.\n\n' \
    "$(welcome_color 255 78 151)neofetch${reset}" "$(welcome_color 39 184 255)fastfetch${reset}"
}
