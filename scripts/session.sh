#!/bin/bash
# Bootstrap-safe logging: no Python, Homebrew or credentials required.
STEP_INDEX=0
COMPLETED_STEPS=0
STEP_TOTAL=0
CURRENT_STEP=not-started
STEP_ACTION=checked
RUN_DIR=${RUN_DIR:-}
UI_COLOR=false
UI_EMOJI=false
HAS_WARNINGS=false

ui_init() {
  local interactive=false locale_name=${LC_ALL:-${LC_CTYPE:-${LANG:-}}}
  UI_COLOR=false
  UI_EMOJI=false
  if [[ -t 1 && ${TERM:-dumb} != dumb && -z ${CI:-}${GITHUB_ACTIONS:-} ]]; then interactive=true; fi
  case "${ONE_BITE_COLOR:-auto}" in
    auto) UI_COLOR=$interactive ;;
    always) UI_COLOR=true ;;
    never) ;;
    *)
      echo 'ERROR: ONE_BITE_COLOR must be auto, always or never.' >&2
      return 2
      ;;
  esac
  if [[ -n ${NO_COLOR:-} || ${TERM:-dumb} == dumb ]]; then UI_COLOR=false; fi
  case "${ONE_BITE_ICONS:-auto}" in
    auto)
      case "$locale_name" in *UTF-8* | *utf-8* | *UTF8* | *utf8*) UI_EMOJI=$interactive ;; esac
      ;;
    emoji) UI_EMOJI=true ;;
    ascii) ;;
    *)
      echo 'ERROR: ONE_BITE_ICONS must be auto, emoji or ascii.' >&2
      return 2
      ;;
  esac
}

ui_print() {
  local kind=$1 message=$2 color=36 icon='ℹ️ ' start='' reset=''
  case "$kind" in
    progress) icon='⏳ ' ;;
    ok)
      color=32
      icon='✅ '
      ;;
    skip)
      color=34
      icon='⏭️ '
      ;;
    keep)
      color=34
      icon='📌 '
      ;;
    warn)
      color=33
      icon='⚠️ '
      ;;
    error)
      color=31
      icon='❌ '
      ;;
  esac
  if [[ "$UI_COLOR" == true ]]; then
    start=$(printf '\033[%sm' "$color")
    reset=$'\033[0m'
  fi
  if [[ "$UI_EMOJI" != true ]]; then icon=''; fi
  printf '%s%s%s%s\n' "$start" "$icon" "$message" "$reset"
}

warn() {
  HAS_WARNINGS=true
  ui_print warn "[WARN] $*" >&2
  event "$CURRENT_STEP" warning notice
}

json_string() {
  local value=$1
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  value=${value//$'\n'/\\n}
  value=${value//$'\r'/\\r}
  value=${value//$'\t'/\\t}
  printf '"%s"' "$value"
}

event() {
  [[ -n "$RUN_DIR" ]] || return 0
  printf '%s\t%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "$1" "$2" "$3" >>"$RUN_DIR/events.tsv"
}

step_display() {
  # Manifest IDs remain stable in machine reports; app does not imply cask.
  case "$1" in
    cask:*) printf 'app:%s' "${1#cask:}" ;;
    *) printf '%s' "$1" ;;
  esac
}

step_run() {
  local percent=0 filled=0 bar='' i kind=ok label=OK
  CURRENT_STEP=$1
  shift
  STEP_INDEX=$((STEP_INDEX + 1))
  STEP_ACTION=checked
  if [[ "$STEP_TOTAL" -gt 0 ]]; then percent=$((COMPLETED_STEPS * 100 / STEP_TOTAL)); fi
  filled=$((percent / 5))
  for ((i = 0; i < 20; i++)); do
    if [[ "$i" -lt "$filled" ]]; then bar+='#'; else bar+='.'; fi
  done
  printf '\n'
  ui_print progress "[$STEP_INDEX/$STEP_TOTAL] [$bar] $percent% $(step_display "$CURRENT_STEP")"
  event "$CURRENT_STEP" started pending
  "$@"
  COMPLETED_STEPS=$((COMPLETED_STEPS + 1))
  event "$CURRENT_STEP" success "$STEP_ACTION"
  case "$STEP_ACTION" in
    skipped)
      kind=skip
      label=SKIP
      ;;
    preserved)
      kind=keep
      label=KEEP
      ;;
    warning)
      HAS_WARNINGS=true
      kind=warn
      label=WARN
      ;;
  esac
  ui_print "$kind" "[$label] $(step_display "$CURRENT_STEP") ($STEP_ACTION)"
  CURRENT_STEP=finished
}

finish_session() {
  local code=$1 status=failed component separator=
  trap - EXIT
  [[ "$code" -ne 0 ]] || status=success
  if [[ "$code" -ne 0 ]]; then
    event "$CURRENT_STEP" failed "$code"
  fi
  {
    printf '{"schema_version":1,"status":'
    json_string "$status"
    printf ',"exit_code":%s,"mode":' "$code"
    json_string "$MODE"
    printf ',"update":%s,"last_step":' "$UPDATE"
    json_string "$CURRENT_STEP"
    printf ',"script_version":'
    json_string "$(cat "$ROOT/VERSION")"
    printf ',"desktop_mode":'
    json_string "${DESKTOP_MODE:-download}"
    printf ',"with_claude":%s' "${WITH_CLAUDE:-false}"
    printf ',"with_docker":%s' "${WITH_DOCKER:-false}"
    printf ',"manual_steps":['
    for component in ${MANUAL_STEPS:-}; do
      printf '%s' "$separator"
      json_string "$component"
      separator=,
    done
    printf ']'
    printf ',"started_at":'
    json_string "$STARTED_AT"
    printf ',"finished_at":'
    json_string "$(date -u +%FT%TZ)"
    printf ',"completed_steps":%s,"total_steps":%s}\n' "$COMPLETED_STEPS" "$STEP_TOTAL"
  } >"$RUN_DIR/result.json.tmp"
  mv "$RUN_DIR/result.json.tmp" "$RUN_DIR/result.json"
  if [[ "$code" -ne 0 ]]; then
    printf '\n'
    ui_print error "[FAILED] $(step_display "$CURRENT_STEP"), exit $code. Correct the cause and rerun the same command."
  fi
  printf '\n'
  if [[ "$MODE" == install && ("$code" == 0 || -n "${MANUAL_STEPS:-}") ]]; then
    if ! python3 "$ROOT/scripts/manual.py" --run-dir "$RUN_DIR" --config-dir "$CONFIG_DIR"; then
      warn 'Unable to write detailed manual instructions. See docs/installation.md and the installer paths above.'
    fi
    if [[ -n "${MANUAL_STEPS:-}" ]]; then HAS_WARNINGS=true; fi
  fi
  if [[ "$code" == 0 ]]; then
    if [[ "$HAS_WARNINGS" == true ]]; then
      ui_print warn "[DONE] Result: $status (with setup warnings). Completed: $COMPLETED_STEPS/$STEP_TOTAL. Logs: $RUN_DIR"
    else
      ui_print ok "[DONE] Result: $status. Completed: $COMPLETED_STEPS/$STEP_TOTAL. Logs: $RUN_DIR"
    fi
  else
    ui_print error "[FAILED] Result: $status. Completed: $COMPLETED_STEPS/$STEP_TOTAL. Logs: $RUN_DIR"
  fi
  exit "$code"
}

record_environment() {
  local os_version=unknown model=unknown memory=unknown
  if [[ $(uname -s) == Darwin ]]; then
    os_version=$(sw_vers -productVersion)
    model=$(sysctl -n hw.model)
    memory=$(sysctl -n hw.memsize)
  fi
  {
    printf '{"schema_version":1,"os":'
    json_string "$(uname -s)"
    printf ',"os_version":'
    json_string "$os_version"
    printf ',"architecture":'
    json_string "$(uname -m)"
    printf ',"hardware_model":'
    json_string "$model"
    printf ',"memory_bytes":'
    json_string "$memory"
    printf ',"proxy_configured":'
    if [[ -n "${HTTPS_PROXY:-}${https_proxy:-}${HTTP_PROXY:-}${http_proxy:-}${ALL_PROXY:-}${all_proxy:-}" ]]; then
      printf true
    else
      printf false
    fi
    printf '}\n'
  } >"$RUN_DIR/environment.json"
  # Only project-owned public inputs, never personal configuration contents.
  (
    cd "$ROOT"
    while IFS= read -r input; do
      case "$input" in 1bite | VERSION | config/* | scripts/*.sh | scripts/*.py | scripts/*.awk) shasum -a 256 "$input" ;; esac
    done <config/repository-files.txt
  ) >"$RUN_DIR/inputs.sha256"
  printf 'timestamp\tstep\tstatus\taction\n' >"$RUN_DIR/events.tsv"
  printf 'component\tsha256\n' >"$RUN_DIR/downloads.tsv"
  ui_print info '[INFO] Environment recorded (OS/architecture/model/memory/proxy presence only).'
}

network_check() {
  local component kind url code transport failed=0
  printf 'component\thttp_status\ttransport_exit\n' >"$RUN_DIR/network.tsv"
  while IFS=$'\t' read -r -u 3 component kind url; do
    [[ "$kind" == connectivity ]] || continue
    if [[ "$component" == ghcr && "${WITH_DOCKER:-false}" != true ]]; then continue; fi
    if [[ "$component" == anthropic && "${WITH_CLAUDE:-false}" != true ]]; then continue; fi
    transport=0
    code=$(curl --config "$ROOT/config/download.curlrc" --silent --output /dev/null --location --connect-timeout 8 --max-time 20 --write-out '%{http_code}' "$url") || transport=$?
    printf '%s\t%s\t%s\n' "$component" "$code" "$transport" >>"$RUN_DIR/network.tsv"
    # Authentication/rate-limit responses prove reachability, but not download access.
    if [[ "$transport" -ne 0 || "$code" == 000 || "$code" -ge 500 ]]; then
      failed=1
      warn "Network $component: HTTP $code, transport $transport"
    elif [[ "$code" -ge 400 && "$code" != 401 ]]; then
      STEP_ACTION=warning
      warn "Network $component: HTTP $code, transport $transport; reachable, but download access is not confirmed."
    else
      ui_print info "[INFO] Network $component: HTTP $code, transport $transport"
    fi
  done 3<"$ROOT/config/sources.tsv"
  if [[ "$failed" != 0 ]]; then
    STEP_ACTION=warning
    warn 'Some network checks failed; individual downloads will retry and report definitive failures.'
    [[ "$MODE" != diagnose ]] || return 1
  fi
}

# Read-only probes can start shell helpers that outlive their parent. Close the
# session descriptor for the entire probe tree so such helpers cannot retain an
# installation lock after verification has completed.
without_session_lock() (
  exec 9>&-
  /usr/bin/env ONE_BITE_LOCKED=0 "$@"
)

session_lock_processes() {
  local lock_file=$1 lsof_command='' output=''
  if [[ -x /usr/sbin/lsof ]]; then
    lsof_command=/usr/sbin/lsof
  elif command -v lsof >/dev/null 2>&1; then
    lsof_command=$(command -v lsof)
  else
    echo 'Process details unavailable: lsof is not installed.' >&2
    return 0
  fi
  output=$("$lsof_command" -nP -Fpc "$lock_file" 2>/dev/null || :)
  if [[ -z "$output" ]]; then
    echo 'No process details were available for the open lock file.' >&2
    return 0
  fi
  echo 'Processes with the lock file open:' >&2
  printf '%s\n' "$output" | awk '
    /^p/ {
      if (pid != "") printf "  PID %s: %s\n", pid, command
      pid=substr($0, 2)
      command="unknown"
      next
    }
    /^c/ { command=substr($0, 2) }
    END { if (pid != "") printf "  PID %s: %s\n", pid, command }
  ' >&2
}

session_try_lock() {
  if [[ $(uname -s) == Darwin ]]; then
    /usr/bin/lockf -s -t 0 9
  else
    # Portable test hosts; macOS bootstrap uses its system lockf, not Homebrew.
    flock -n -E 75 9
  fi
}

session_lock_failure() {
  local lock_file=$1 code=$2 session_root=${1%/session.lock}
  if [[ "$code" == 75 ]]; then
    echo 'Lock status: held. Another One Bite process still has the session lock open.' >&2
    echo 'This may be an active installer or a descendant left by an interrupted or older run.' >&2
  else
    echo "Lock status: error. The system lock helper exited $code; this does not prove another installation is running." >&2
  fi
  echo "Lock: $lock_file" >&2
  session_lock_processes "$lock_file"
  printf 'Inspect again: ./1bite --lock-status --log-dir %q\n' "$session_root" >&2
}

session_lock_status() (
  local session_root=$1 lock_file code
  if [[ ! -e "$session_root" ]]; then
    echo 'Lock status: available. The state directory does not exist yet.'
    echo "Lock: $session_root/session.lock"
    return 0
  fi
  [[ -d "$session_root" ]] || {
    echo "Lock status: error. The log root is not a directory: $session_root" >&2
    return 73
  }
  session_root=$(cd "$session_root" && pwd -P) || return 73
  lock_file="$session_root/session.lock"
  [[ ! -L "$lock_file" ]] || {
    echo "Lock status: error. Refusing a symbolic-link lock file: $lock_file" >&2
    return 73
  }
  if [[ ! -e "$lock_file" ]]; then
    echo 'Lock status: available. No session has created the persistent lock file yet.'
    echo "Lock: $lock_file"
    return 0
  fi
  if ! exec 9>>"$lock_file"; then
    echo "Lock status: error. Unable to open the lock file: $lock_file" >&2
    return 73
  fi
  if session_try_lock; then
    exec 9>&-
    echo 'Lock status: available. The persistent file exists, but no process holds its kernel lock.'
    echo "Lock: $lock_file"
    return 0
  else
    code=$?
  fi
  exec 9>&-
  session_lock_failure "$lock_file" "$code"
  [[ "$code" == 75 ]] && return 75
  return "$code"
)

# A persistent inode with a kernel lock has no mkdir/PID publication or stale-
# recovery window. Descriptor 9 is inherited by mutating shell installers and
# explicitly passed to mutating native installers launched from Python. The
# complete read-only verification tree closes it through without_session_lock.
# Never unlink session.lock.
run_session() (
  local session_root=$1 code
  local statuses=()
  ui_init
  umask 077
  mkdir -p "$session_root"
  session_root=$(cd "$session_root" && pwd -P)
  [[ ! -L "$session_root/session.lock" ]] || {
    echo "Lock status: error. Refusing a symbolic-link lock file: $session_root/session.lock" >&2
    return 73
  }
  exec 9>>"$session_root/session.lock"
  if session_try_lock; then
    :
  else
    code=$?
    exec 9>&-
    session_lock_failure "$session_root/session.lock" "$code"
    [[ "$code" == 75 ]] && return 75
    return "$code"
  fi
  export ONE_BITE_LOCKED=1
  RUN_DIR=$(mktemp -d "$session_root/$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
  export RUN_DIR
  STARTED_AT=$(date -u +%FT%TZ)
  # tee streams raw bytes directly to the original stdout, including prompts without
  # newlines. Only the log branch strips our decoration; wait for both writers.
  set +e
  (
    set -e
    HAS_WARNINGS=false
    trap 'finish_session $?' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    record_environment
    ui_print info "[INFO] One Bite $(cat "$ROOT/VERSION") | mode=$MODE | update=$UPDATE | desktop=${DESKTOP_MODE:-download}"
    execute_mode
  ) 2>&1 | tee /dev/fd/4 | awk -f "$ROOT/scripts/plain-log.awk" >"$RUN_DIR/run.log"
  statuses=("${PIPESTATUS[@]}")
  code=${statuses[0]}
  if [[ ("$code" == 0 || "$code" == 141) && ("${statuses[1]}" != 0 || "${statuses[2]}" != 0) ]]; then
    code=74
    (
      CURRENT_STEP=logging
      finish_session 74
    )
  fi
  set -e
  return "$code"
) 4>&1
