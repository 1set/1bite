#!/bin/bash
set -euo pipefail

BATTERY_TOOL_VERSION=0.0.7
BATTERY_SCHEMA_VERSION=1
MAX_RETAINED_EVENTS=256

OUTPUT_FORMAT=dashboard
FIELD_NAME=
CACHE_ENABLED=true
INSTALL_TOOL=false
UPDATE_TOOL=false

PMSET_BIN=${ONE_BITE_BATTERY_PMSET_BIN:-/usr/bin/pmset}
SYSTEM_PROFILER_BIN=${ONE_BITE_BATTERY_SYSTEM_PROFILER_BIN:-/usr/sbin/system_profiler}
IOREG_BIN=${ONE_BITE_BATTERY_IOREG_BIN:-/usr/sbin/ioreg}
DATE_BIN=${ONE_BITE_BATTERY_DATE_BIN:-/bin/date}
SCRIPT_PATH=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")

usage() {
  cat <<'HELP'
Usage: 1bite-battery [--summary|--json|--tsv|--shell|--field NAME] [--no-cache]

Read-only macOS battery diagnostics. The default output is a human dashboard.
  --summary     Print one startup-safe line without history or cache access.
  --json        Print stable JSON schema version 1.
  --tsv         Print normalized, versioned TSV rows.
  --shell       Print source-safe shell assignments.
  --field NAME  Print one allowlisted scalar field.
  --no-cache    Do not read or write sanitized battery history.
  --help        Show this help.

One Bite uses the internal --install-tool [--update] operation to install this
script as ~/.local/bin/1bite-battery. It is separate from the main installer.
HELP
}

die_usage() {
  printf '1bite-battery: %s\n' "$*" >&2
  usage >&2
  exit 2
}

set_output_format() {
  [[ "$OUTPUT_FORMAT" == dashboard ]] || die_usage 'choose only one output format'
  OUTPUT_FORMAT=$1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json)
      set_output_format json
      shift
      ;;
    --summary)
      set_output_format summary
      CACHE_ENABLED=false
      shift
      ;;
    --tsv)
      set_output_format tsv
      shift
      ;;
    --shell)
      set_output_format shell
      shift
      ;;
    --field)
      [[ $# -ge 2 && -n "$2" ]] || die_usage '--field requires a name'
      set_output_format field
      FIELD_NAME=$2
      shift 2
      ;;
    --format)
      [[ $# -ge 2 ]] || die_usage '--format requires dashboard, summary, json, tsv, or shell'
      case "$2" in dashboard | summary | json | tsv | shell) ;; *) die_usage "unknown format: $2" ;; esac
      set_output_format "$2"
      if [[ "$2" == summary ]]; then CACHE_ENABLED=false; fi
      shift 2
      ;;
    --no-cache)
      CACHE_ENABLED=false
      shift
      ;;
    --install-tool)
      [[ "$INSTALL_TOOL" == false ]] || die_usage '--install-tool was provided twice'
      INSTALL_TOOL=true
      shift
      ;;
    --update)
      UPDATE_TOOL=true
      shift
      ;;
    --help | -h)
      usage
      exit 0
      ;;
    *) die_usage "unknown argument: $1" ;;
  esac
done

[[ "$UPDATE_TOOL" == false || "$INSTALL_TOOL" == true ]] || die_usage '--update is valid only with --install-tool'
if [[ "$INSTALL_TOOL" == true && "$OUTPUT_FORMAT" != dashboard ]]; then
  die_usage '--install-tool cannot be combined with an output format'
fi
BATTERY_FIELD_NAMES=' schema_version collected_at status complete battery.present battery.charge_percent battery.power_source battery.state battery.cycle_count battery.maximum_capacity_percent battery.maximum_capacity_mah battery.design_capacity_mah battery.health battery.voltage_mv battery.current_ma history.retained_event_count history.interval_count '
if [[ "$OUTPUT_FORMAT" == field ]]; then
  case "$BATTERY_FIELD_NAMES" in
    *" $FIELD_NAME "*) ;;
    *)
      printf '1bite-battery: unknown field: %s\n' "$FIELD_NAME" >&2
      exit 2
      ;;
  esac
fi

umask 077
WARNINGS=

add_warning() {
  case " $WARNINGS " in
    *" $1 "*) ;;
    *) WARNINGS="${WARNINGS:+$WARNINGS }$1" ;;
  esac
}

path_has_symlink() {
  local path=$1 current='' part
  local old_ifs=$IFS
  local -a parts
  if [[ "$path" != /* ]]; then path="$PWD/$path"; fi
  IFS=/ read -r -a parts <<<"${path#/}"
  IFS=$old_ifs
  current=/
  for part in "${parts[@]}"; do
    [[ -n "$part" ]] || continue
    if [[ "$current" == / ]]; then current="/$part"; else current="$current/$part"; fi
    if [[ -L "$current" ]]; then
      return 0
    fi
  done
  return 1
}

normalize_unsigned() {
  local value=$1 maximum=$2
  case "$value" in '' | *[!0-9]*) return 1 ;; esac
  while [[ ${#value} -gt 1 && ${value:0:1} == 0 ]]; do value=${value:1}; done
  if [[ ${#value} -gt ${#maximum} ]]; then return 1; fi
  if [[ ${#value} -eq ${#maximum} && "$value" > "$maximum" ]]; then return 1; fi
  printf '%s\n' "$value"
}

decimal_subtract() {
  local larger=$1 smaller=$2 result='' borrow=0 index left right digit
  index=$((${#larger} - 1))
  while [[ $index -ge 0 ]]; do
    left=${larger:index:1}
    if [[ $index -lt $((${#larger} - ${#smaller})) ]]; then
      right=0
    else
      right=${smaller:index-(${#larger} - ${#smaller}):1}
    fi
    digit=$((left - right - borrow))
    if [[ $digit -lt 0 ]]; then
      digit=$((digit + 10))
      borrow=1
    else
      borrow=0
    fi
    result="$digit$result"
    index=$((index - 1))
  done
  while [[ ${#result} -gt 1 && ${result:0:1} == 0 ]]; do result=${result:1}; done
  printf '%s\n' "$result"
}

utc_iso_epoch() {
  LC_ALL=C awk -v value="$1" '
    function leap(year) { return (year % 4 == 0 && year % 100 != 0) || year % 400 == 0 }
    function dim(year, month) {
      if (month == 2) return 28 + leap(year)
      if (month == 4 || month == 6 || month == 9 || month == 11) return 30
      return 31
    }
    BEGIN {
      if (length(value) != 20 || substr(value,5,1) != "-" || substr(value,8,1) != "-" ||
          substr(value,11,1) != "T" || substr(value,14,1) != ":" || substr(value,17,1) != ":" ||
          substr(value,20,1) != "Z" || substr(value,1,4) !~ /^[0-9][0-9][0-9][0-9]$/ ||
          substr(value,6,2) !~ /^[0-9][0-9]$/ || substr(value,9,2) !~ /^[0-9][0-9]$/ ||
          substr(value,12,2) !~ /^[0-9][0-9]$/ || substr(value,15,2) !~ /^[0-9][0-9]$/ ||
          substr(value,18,2) !~ /^[0-9][0-9]$/) exit 1
      year=substr(value,1,4)+0; month=substr(value,6,2)+0; day=substr(value,9,2)+0
      hour=substr(value,12,2)+0; minute=substr(value,15,2)+0; second=substr(value,18,2)+0
      if (year < 1970 || month < 1 || month > 12 || day < 1 || day > dim(year,month) ||
          hour > 23 || minute > 59 || second > 59) exit 1
      days=0
      for (cursor=1970; cursor<year; cursor++) days += 365 + leap(cursor)
      for (cursor=1; cursor<month; cursor++) days += dim(year,cursor)
      days += day-1
      printf "%.0f\n", days*86400 + hour*3600 + minute*60 + second
    }
  '
}

normalize_current_ma() {
  local value=$1 magnitude
  case "$value" in
    -*)
      magnitude=${value#-}
      magnitude=$(normalize_unsigned "$magnitude" 20000) || return 1
      if [[ "$magnitude" == 0 ]]; then printf '0\n'; else printf -- '-%s\n' "$magnitude"; fi
      return
      ;;
    '' | *[!0-9]*) return 1 ;;
  esac
  while [[ ${#value} -gt 1 && ${value:0:1} == 0 ]]; do value=${value:1}; done
  if [[ ${#value} -le 5 ]]; then
    value=$(normalize_unsigned "$value" 20000) || return 1
    printf '%s\n' "$value"
    return
  fi
  if [[ ${#value} -eq 10 && ("$value" == 42949* || "$value" == 42948*) ]]; then
    if [[ "x$value" > x4294947295 && "x$value" < x4294967296 ]]; then
      magnitude=$(decimal_subtract 4294967296 "$value")
      magnitude=$(normalize_unsigned "$magnitude" 20000) || return 1
      printf -- '-%s\n' "$magnitude"
      return
    fi
  fi
  if [[ ${#value} -eq 20 && ("x$value" > x18446744073709531615 || "$value" == 18446744073709531615) && ("x$value" < x18446744073709551616) ]]; then
    magnitude=$(decimal_subtract 18446744073709551616 "$value")
    magnitude=$(normalize_unsigned "$magnitude" 20000) || return 1
    printf -- '-%s\n' "$magnitude"
    return
  fi
  return 1
}

sha256_file() {
  if [[ -x /usr/bin/shasum ]]; then
    /usr/bin/shasum -a 256 "$1" | /usr/bin/awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | /usr/bin/awk '{print $1}'
  else
    printf '1bite-battery: system shasum is required for managed installation.\n' >&2
    return 1
  fi
}

safe_absolute_path() {
  [[ "$1" == /* ]] || return 1
  case "$1" in
    */./* | */../* | */. | */..) return 1 ;;
  esac
  return 0
}

file_mode() {
  if [[ "$(/usr/bin/uname -s)" == Darwin ]]; then
    /usr/bin/stat -f '%Lp' "$1"
  else
    /usr/bin/stat -c '%a' "$1"
  fi
}

file_link_count() {
  if [[ "$(/usr/bin/uname -s)" == Darwin ]]; then
    /usr/bin/stat -f '%l' "$1"
  else
    /usr/bin/stat -c '%h' "$1"
  fi
}

directory_identity() {
  if [[ "$(/usr/bin/uname -s)" == Darwin ]]; then
    /usr/bin/stat -f '%d:%i' "$1"
  else
    /usr/bin/stat -c '%d:%i' "$1"
  fi
}

directory_matches() {
  local path=$1 expected_identity=$2 expected_real=$3 actual_real
  [[ -d "$path" && ! -L "$path" ]] || return 1
  path_has_symlink "$path" && return 1
  [[ "$(directory_identity "$path")" == "$expected_identity" ]] || return 1
  actual_real=$(cd "$path" && pwd -P) || return 1
  [[ "$actual_real" == "$expected_real" ]]
}

private_regular_file() {
  [[ -f "$1" && ! -L "$1" ]] || return 1
  [[ "$(file_mode "$1")" == 600 && "$(file_link_count "$1")" == 1 ]]
}

ensure_private_battery_dir() {
  local state_base=${XDG_STATE_HOME:-$HOME/.local/state}
  PRIVATE_ROOT="$state_base/1bite/battery"
  PRIVATE_DIR_READY=false
  if ! safe_absolute_path "$state_base"; then
    add_warning state_path_unsafe
    return 0
  fi
  if path_has_symlink "$state_base" || path_has_symlink "${state_base%/}/1bite" || path_has_symlink "$PRIVATE_ROOT"; then
    add_warning state_path_symlink
    return 0
  fi
  if ! mkdir -p "$PRIVATE_ROOT" 2>/dev/null; then
    add_warning state_path_unsafe
    return 0
  fi
  if path_has_symlink "$PRIVATE_ROOT" || [[ ! -d "$PRIVATE_ROOT" ]]; then
    add_warning state_path_unsafe
    return 0
  fi
  if ! chmod 700 "$PRIVATE_ROOT" 2>/dev/null; then
    add_warning state_path_unsafe
    return 0
  fi
  PRIVATE_ROOT_IDENTITY=$(directory_identity "$PRIVATE_ROOT") || {
    add_warning state_path_unsafe
    return 0
  }
  PRIVATE_ROOT_REAL=$(cd "$PRIVATE_ROOT" && pwd -P) || {
    add_warning state_path_unsafe
    return 0
  }
  PRIVATE_DIR_READY=true
}

acquire_tool_lock() {
  local lock_file="$PRIVATE_ROOT/tool.lock" lock_status
  directory_matches "$PRIVATE_ROOT" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" || {
    printf '1bite-battery: private state directory changed before locking.\n' >&2
    exit 1
  }
  if [[ ! -e "$lock_file" && ! -L "$lock_file" ]]; then
    (
      set -o noclobber
      : >"$lock_file"
    ) 2>/dev/null || true
  fi
  if ! private_regular_file "$lock_file"; then
    printf '1bite-battery: preserving an unsafe or non-regular tool lock.\n' >&2
    exit 1
  fi
  exec 8>>"$lock_file"
  directory_matches "$PRIVATE_ROOT" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" || {
    exec 8>&-
    printf '1bite-battery: private state directory changed while locking.\n' >&2
    exit 1
  }
  set +e
  if [[ -x /usr/bin/lockf ]]; then
    /usr/bin/lockf -s -t 0 8
    lock_status=$?
  elif command -v flock >/dev/null 2>&1; then
    flock -n -E 75 8
    lock_status=$?
  else
    lock_status=69
  fi
  set -e
  if [[ $lock_status -eq 75 ]]; then
    printf '1bite-battery: another battery-tool install or update is running.\n' >&2
    exit 75
  elif [[ $lock_status -ne 0 ]]; then
    printf '1bite-battery: the battery-tool lock helper failed (%s).\n' "$lock_status" >&2
    exit "$lock_status"
  fi
}

publish_record() {
  local path=$1 header=$2 version=$3 digest=$4 expected_sha=$5 temporary displaced='' record_sha
  if ! temporary=$(mktemp "${path%/*}/.${path##*/}.XXXXXX"); then return 1; fi
  if ! printf '%s\nversion\t%s\nsha256\t%s\n' "$header" "$version" "$digest" >"$temporary" ||
    ! chmod 600 "$temporary" || ! private_regular_file "$temporary"; then
    rm -f "$temporary"
    return 1
  fi
  if ! record_sha=$(sha256_file "$temporary"); then
    rm -f "$temporary"
    return 1
  fi
  directory_matches "${path%/*}" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" || {
    rm -f "$temporary"
    return 1
  }
  if [[ -n "$expected_sha" ]]; then
    if ! private_regular_file "$path" || [[ "$(sha256_file "$path")" != "$expected_sha" ]]; then
      rm -f "$temporary"
      return 1
    fi
    if ! displaced=$(mktemp "${path}.previous.XXXXXX") || ! rm -f "$displaced"; then
      rm -f "$temporary"
      return 1
    fi
    if ! mv -f "$path" "$displaced" || ! private_regular_file "$displaced" ||
      [[ "$(sha256_file "$displaced")" != "$expected_sha" ]]; then
      if [[ -e "$displaced" || -L "$displaced" ]]; then mv -n "$displaced" "$path" || true; fi
      rm -f "$temporary"
      return 1
    fi
    if ! directory_matches "${path%/*}" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL"; then
      mv -n "$displaced" "$path" || true
      rm -f "$temporary"
      return 1
    fi
  elif [[ -e "$path" || -L "$path" ]]; then
    rm -f "$temporary"
    return 1
  fi
  if ! mv -n "$temporary" "$path"; then
    if [[ -n "$displaced" && (-e "$displaced" || -L "$displaced") ]]; then mv -n "$displaced" "$path" || true; fi
    rm -f "$temporary"
    return 1
  fi
  if ! directory_matches "${path%/*}" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL"; then return 1; fi
  if [[ -e "$temporary" || -L "$temporary" ]]; then
    rm -f "$temporary"
    if [[ -n "$displaced" && (-e "$displaced" || -L "$displaced") ]]; then mv -n "$displaced" "$path" || true; fi
    return 1
  fi
  if ! private_regular_file "$path" || [[ "$(sha256_file "$path")" != "$record_sha" ]]; then
    if [[ -f "$path" && ! -L "$path" && "$(file_link_count "$path")" == 1 && "$(sha256_file "$path")" == "$record_sha" ]]; then
      rm -f "$path"
    fi
    if [[ -n "$displaced" && (-e "$displaced" || -L "$displaced") ]]; then mv -n "$displaced" "$path" || true; fi
    return 1
  fi
  if [[ -n "$displaced" ]] && ! rm -f "$displaced"; then return 1; fi
  return 0
}

read_receipt() {
  local receipt=$1 header key1 value1 extra1 key2 value2 extra2 trailing=''
  RECEIPT_VALID=false
  RECEIPT_VERSION=
  RECEIPT_SHA=
  RECEIPT_FILE_SHA=
  directory_matches "${receipt%/*}" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" || return 0
  private_regular_file "$receipt" || return 0
  {
    IFS= read -r header || return 0
    IFS=$'\t' read -r key1 value1 extra1 || return 0
    IFS=$'\t' read -r key2 value2 extra2 || return 0
    if IFS= read -r trailing || [[ -n "$trailing" ]]; then return 0; fi
  } <"$receipt"
  [[ "$header" == $'one-bite-battery-tool\t1' && "$key1" == version && "$key2" == sha256 && -z "$extra1" && -z "$extra2" ]] || return 0
  RECEIPT_VERSION=$value1
  RECEIPT_SHA=$value2
  [[ "$RECEIPT_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$RECEIPT_SHA" =~ ^[0-9a-f]{64}$ ]] || return 0
  RECEIPT_FILE_SHA=$(sha256_file "$receipt")
  RECEIPT_VALID=true
}

write_pending() {
  if ! publish_record "$1" $'one-bite-battery-tool-pending\t1' "$BATTERY_TOOL_VERSION" "$2" ''; then
    printf '1bite-battery: preserving an existing pending ownership record.\n' >&2
    return 1
  fi
}

restore_pending() {
  local pending=$1 version=$2 digest=$3
  directory_matches "${pending%/*}" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" || return 1
  [[ ! -e "$pending" && ! -L "$pending" ]] || return 1
  publish_record "$pending" $'one-bite-battery-tool-pending\t1' "$version" "$digest" ''
}

read_pending() {
  local pending=$1 header key1 value1 extra1 key2 value2 extra2 trailing=''
  PENDING_VALID=false
  PENDING_VERSION=
  PENDING_SHA=
  PENDING_FILE_SHA=
  directory_matches "${pending%/*}" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" || return 0
  private_regular_file "$pending" || return 0
  {
    IFS= read -r header || return 0
    IFS=$'\t' read -r key1 value1 extra1 || return 0
    IFS=$'\t' read -r key2 value2 extra2 || return 0
    if IFS= read -r trailing || [[ -n "$trailing" ]]; then return 0; fi
  } <"$pending"
  [[ "$header" == $'one-bite-battery-tool-pending\t1' && "$key1" == version && "$key2" == sha256 && -z "$extra1" && -z "$extra2" ]] || return 0
  PENDING_VERSION=$value1
  PENDING_SHA=$value2
  [[ "$PENDING_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$PENDING_SHA" =~ ^[0-9a-f]{64}$ ]] || return 0
  PENDING_FILE_SHA=$(sha256_file "$pending")
  PENDING_VALID=true
}

remove_owned_record() {
  local path=$1 expected_sha=$2 displaced
  directory_matches "${path%/*}" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" || return 1
  private_regular_file "$path" || return 1
  [[ "$(sha256_file "$path")" == "$expected_sha" ]] || return 1
  if ! displaced=$(mktemp "${path}.removed.XXXXXX") || ! rm -f "$displaced"; then return 1; fi
  if ! mv -f "$path" "$displaced"; then return 1; fi
  if ! directory_matches "${path%/*}" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL"; then
    mv -n "$displaced" "$path" || true
    return 1
  fi
  if ! private_regular_file "$displaced" || [[ "$(sha256_file "$displaced")" != "$expected_sha" ]]; then
    mv -n "$displaced" "$path" || true
    return 1
  fi
  directory_matches "${path%/*}" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" || {
    mv -n "$displaced" "$path" || true
    return 1
  }
  rm -f "$displaced" || return 1
  return 0
}

verify_managed_tool_state() {
  local target=$1 receipt=$2 pending=$3 expected_version=$4 expected_sha=$5
  local bin_dir=$6 expected_bin_identity=$7 expected_bin_real=$8 first_receipt_sha first_target_sha final_target_sha link_count
  directory_matches "$PRIVATE_ROOT" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" || return 1
  directory_matches "$bin_dir" "$expected_bin_identity" "$expected_bin_real" || return 1
  [[ ! -e "$pending" && ! -L "$pending" ]] || return 1
  read_receipt "$receipt"
  [[ "$RECEIPT_VALID" == true && "$RECEIPT_VERSION" == "$expected_version" && "$RECEIPT_SHA" == "$expected_sha" ]] || return 1
  first_receipt_sha=$RECEIPT_FILE_SHA
  first_target_sha=$(sha256_file "$target") || return 1
  [[ "$first_target_sha" == "$expected_sha" ]] || return 1
  /bin/bash -n "$target" >/dev/null 2>&1 || return 1
  link_count=$(file_link_count "$target") || return 1
  directory_matches "$PRIVATE_ROOT" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" || return 1
  directory_matches "$bin_dir" "$expected_bin_identity" "$expected_bin_real" || return 1
  read_receipt "$receipt"
  [[ "$RECEIPT_VALID" == true && "$RECEIPT_VERSION" == "$expected_version" && "$RECEIPT_SHA" == "$expected_sha" &&
    "$RECEIPT_FILE_SHA" == "$first_receipt_sha" ]] || return 1
  final_target_sha=$(sha256_file "$target") || return 1
  [[ "$final_target_sha" == "$expected_sha" && "$link_count" == 1 &&
    -d "$PRIVATE_ROOT" && ! -L "$PRIVATE_ROOT" && -d "$bin_dir" && ! -L "$bin_dir" &&
    ! -e "$pending" && ! -L "$pending" && -f "$receipt" && ! -L "$receipt" &&
    -f "$target" && ! -L "$target" && -x "$target" ]]
}

install_tool() {
  local bin_dir="$HOME/.local/bin" target="$HOME/.local/bin/1bite-battery"
  local receipt pending receipt_exists=false pending_exists=false current_sha target_sha='' temporary temporary_sha source_sha_after backup='' backup_incomplete='' backup_name timestamp target_healthy=false displaced='' bin_identity bin_real recovered=false recovery_sha='' recovery_version='' recovery_file_sha='' success_version=''
  if ! safe_absolute_path "$HOME"; then
    printf '1bite-battery: HOME is not a safe absolute path; nothing was installed.\n' >&2
    exit 1
  fi
  ensure_private_battery_dir
  if [[ "$PRIVATE_DIR_READY" != true ]]; then
    printf '1bite-battery: private state directory is unsafe; nothing was installed.\n' >&2
    exit 1
  fi
  acquire_tool_lock
  receipt="$PRIVATE_ROOT/tool-receipt-v1.tsv"
  pending="$PRIVATE_ROOT/tool-pending-v1.tsv"
  if path_has_symlink "$bin_dir" || [[ -L "$target" || -L "$receipt" || -L "$pending" ]]; then
    printf '1bite-battery: refusing to follow a symlink in the managed tool path.\n' >&2
    exit 1
  fi
  mkdir -p "$bin_dir"
  if [[ ! -d "$bin_dir" || -L "$bin_dir" ]] || path_has_symlink "$bin_dir"; then
    printf '1bite-battery: ~/.local/bin is not a safe directory.\n' >&2
    exit 1
  fi
  bin_identity=$(directory_identity "$bin_dir")
  bin_real=$(cd "$bin_dir" && pwd -P)
  current_sha=$(sha256_file "$SCRIPT_PATH")
  if [[ -e "$receipt" ]]; then receipt_exists=true; fi
  if [[ -e "$pending" ]]; then pending_exists=true; fi
  read_receipt "$receipt"
  read_pending "$pending"
  if [[ "$receipt_exists" == true && "$RECEIPT_VALID" != true ]]; then
    printf '1bite-battery: preserving the existing unknown or damaged receipt; nothing was installed.\n' >&2
    exit 1
  fi
  if [[ "$pending_exists" == true && "$PENDING_VALID" != true ]]; then
    printf '1bite-battery: preserving the existing unknown or damaged pending ownership record; nothing was installed.\n' >&2
    exit 1
  fi
  if [[ -e "$target" ]]; then
    [[ -f "$target" && ! -L "$target" && "$(file_link_count "$target")" == 1 ]] || {
      printf '1bite-battery: preserving the existing non-regular %s.\n' "$target" >&2
      exit 1
    }
    target_sha=$(sha256_file "$target")
    if /bin/bash -n "$target" >/dev/null 2>&1 && [[ -x "$target" ]]; then target_healthy=true; fi
  fi
  if [[ "$PENDING_VALID" == true ]]; then
    if [[ -n "$target_sha" && "$target_sha" == "$PENDING_SHA" && "$target_healthy" == true ]]; then
      recovery_sha=$PENDING_SHA
      recovery_version=$PENDING_VERSION
      recovery_file_sha=$PENDING_FILE_SHA
      if ! publish_record "$receipt" $'one-bite-battery-tool\t1' "$PENDING_VERSION" "$PENDING_SHA" "$RECEIPT_FILE_SHA"; then
        printf '1bite-battery: the ownership receipt changed during recovery; it was preserved.\n' >&2
        exit 1
      fi
      read_receipt "$receipt"
      if ! directory_matches "$PRIVATE_ROOT" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" ||
        ! directory_matches "$bin_dir" "$bin_identity" "$bin_real" ||
        [[ "$RECEIPT_VALID" != true || "$RECEIPT_VERSION" != "$recovery_version" || "$RECEIPT_SHA" != "$recovery_sha" ||
          -L "$target" || ! -f "$target" || ! -x "$target" || "$(file_link_count "$target")" != 1 || "$(sha256_file "$target")" != "$recovery_sha" ]] ||
        ! /bin/bash -n "$target" >/dev/null 2>&1; then
        printf '1bite-battery: managed paths changed during ownership recovery; the pending record was retained.\n' >&2
        exit 1
      fi
      if ! remove_owned_record "$pending" "$recovery_file_sha"; then
        printf '1bite-battery: the pending ownership record changed during recovery; it was preserved.\n' >&2
        exit 1
      fi
      read_receipt "$receipt"
      if ! directory_matches "$PRIVATE_ROOT" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" ||
        ! directory_matches "$bin_dir" "$bin_identity" "$bin_real" ||
        [[ "$RECEIPT_VALID" != true || "$RECEIPT_VERSION" != "$recovery_version" || "$RECEIPT_SHA" != "$recovery_sha" ||
          -e "$pending" || -L "$pending" || -L "$target" || ! -f "$target" || ! -x "$target" ||
          "$(file_link_count "$target")" != 1 || "$(sha256_file "$target")" != "$recovery_sha" ]] ||
        ! /bin/bash -n "$target" >/dev/null 2>&1; then
        restore_pending "$pending" "$recovery_version" "$recovery_sha" || true
        printf '1bite-battery: managed paths changed while finishing ownership recovery; success was not recorded.\n' >&2
        exit 1
      fi
      PENDING_VALID=false
      recovered=true
    elif [[ -z "$target_sha" ]]; then
      if ! remove_owned_record "$pending" "$PENDING_FILE_SHA"; then
        printf '1bite-battery: the pending ownership record changed; it was preserved.\n' >&2
        exit 1
      fi
      PENDING_VALID=false
    elif [[ "$RECEIPT_VALID" == true && "$target_sha" == "$RECEIPT_SHA" && "$UPDATE_TOOL" == true ]]; then
      if ! remove_owned_record "$pending" "$PENDING_FILE_SHA"; then
        printf '1bite-battery: the pending ownership record changed; it was preserved.\n' >&2
        exit 1
      fi
      PENDING_VALID=false
    else
      printf '1bite-battery: an interrupted battery-tool operation needs the same --update scope or manual review.\n' >&2
      exit 1
    fi
  fi
  if [[ -n "$target_sha" ]]; then
    if [[ "$target_sha" == "$current_sha" && "$target_healthy" == true ]]; then
      if ! directory_matches "$bin_dir" "$bin_identity" "$bin_real" ||
        [[ -L "$target" || ! -f "$target" || ! -x "$target" || "$(file_link_count "$target")" != 1 || "$(sha256_file "$target")" != "$current_sha" ]] ||
        ! /bin/bash -n "$target" >/dev/null 2>&1; then
        if [[ "$recovered" == true ]] && directory_matches "$PRIVATE_ROOT" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" &&
          [[ ! -e "$pending" && ! -L "$pending" ]]; then
          write_pending "$pending" "$current_sha" || true
        fi
        printf '1bite-battery: managed target changed during ownership recovery; success was not recorded.\n' >&2
        exit 1
      fi
      if [[ "$RECEIPT_VALID" == true && "$target_sha" == "$RECEIPT_SHA" ]]; then
        success_version=$RECEIPT_VERSION
        if ! verify_managed_tool_state "$target" "$receipt" "$pending" "$success_version" "$current_sha" "$bin_dir" "$bin_identity" "$bin_real"; then
          if [[ "$recovered" == true ]] && directory_matches "$PRIVATE_ROOT" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" &&
            [[ ! -e "$pending" && ! -L "$pending" ]]; then
            restore_pending "$pending" "$recovery_version" "$recovery_sha" || true
          fi
          printf '1bite-battery: final managed-tool verification failed; success was not reported.\n' >&2
          exit 1
        fi
        if [[ "$recovered" == true ]]; then printf 'Recovered ownership for a completely published One Bite battery tool.\n'; fi
        printf 'One Bite battery tool is already current: %s\n' "$target"
      else
        printf '1bite-battery: preserving the existing unowned %s.\n' "$target" >&2
        exit 1
      fi
      return 0
    fi
    if [[ "$RECEIPT_VALID" != true || "$target_sha" != "$RECEIPT_SHA" ]]; then
      printf '1bite-battery: preserving the existing unowned or modified %s.\n' "$target" >&2
      exit 1
    fi
    if [[ "$UPDATE_TOOL" != true ]]; then
      if [[ "$target_healthy" == true ]]; then
        success_version=$RECEIPT_VERSION
        if ! verify_managed_tool_state "$target" "$receipt" "$pending" "$success_version" "$target_sha" "$bin_dir" "$bin_identity" "$bin_real"; then
          if [[ "$recovered" == true ]] && directory_matches "$PRIVATE_ROOT" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" &&
            [[ ! -e "$pending" && ! -L "$pending" ]]; then
            restore_pending "$pending" "$recovery_version" "$recovery_sha" || true
          fi
          printf '1bite-battery: final managed-tool verification failed; success was not reported.\n' >&2
          exit 1
        fi
        printf 'Preserving managed battery tool %s (%s). Run with --update to replace it.\n' "$target" "$RECEIPT_VERSION"
        return 0
      fi
      printf '1bite-battery: the managed battery tool is damaged; rerun with --update to replace it.\n' >&2
      exit 1
    fi
    timestamp=$("$DATE_BIN" -u '+%Y%m%dT%H%M%SZ')
    if [[ ! "$timestamp" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] ||
      ! directory_matches "$PRIVATE_ROOT" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL"; then
      printf '1bite-battery: backup timestamp or private state path is invalid; nothing was replaced.\n' >&2
      exit 1
    fi
    backup_incomplete=$(mktemp "$PRIVATE_ROOT/.1bite-battery.backup-$timestamp.XXXXXX")
    if ! cp -p "$target" "$backup_incomplete" || ! chmod 600 "$backup_incomplete" ||
      [[ "$(sha256_file "$backup_incomplete")" != "$target_sha" ]]; then
      rm -f "$backup_incomplete"
      printf '1bite-battery: could not create a verified backup; nothing was replaced.\n' >&2
      exit 1
    fi
    backup_name=${backup_incomplete##*/}
    backup="$PRIVATE_ROOT/${backup_name#.}"
    if ! directory_matches "$PRIVATE_ROOT" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL"; then
      printf '1bite-battery: private state directory changed during backup; nothing was replaced.\n' >&2
      exit 1
    fi
    if ! mv -n "$backup_incomplete" "$backup"; then
      rm -f "$backup_incomplete"
      printf '1bite-battery: could not publish the verified backup; nothing was replaced.\n' >&2
      exit 1
    fi
    if [[ -e "$backup_incomplete" || ! -f "$backup" || "$(sha256_file "$backup")" != "$target_sha" ]]; then
      rm -f "$backup_incomplete"
      printf '1bite-battery: could not publish the verified backup; nothing was replaced.\n' >&2
      exit 1
    fi
    [[ ! -L "$target" && -f "$target" && "$(file_link_count "$target")" == 1 && "$(sha256_file "$target")" == "$target_sha" ]] || {
      printf '1bite-battery: installed command changed during update; nothing was replaced.\n' >&2
      exit 1
    }
  fi
  write_pending "$pending" "$current_sha"
  read_pending "$pending"
  if [[ "$PENDING_VALID" != true || "$PENDING_SHA" != "$current_sha" || "$PENDING_VERSION" != "$BATTERY_TOOL_VERSION" ]]; then
    printf '1bite-battery: pending ownership verification failed; nothing was replaced.\n' >&2
    exit 1
  fi
  temporary=$(mktemp "$bin_dir/.1bite-battery.XXXXXX")
  cat "$SCRIPT_PATH" >"$temporary"
  chmod 755 "$temporary"
  /bin/bash -n "$temporary"
  temporary_sha=$(sha256_file "$temporary")
  source_sha_after=$(sha256_file "$SCRIPT_PATH")
  if [[ "$temporary_sha" != "$current_sha" || "$source_sha_after" != "$current_sha" ]]; then
    rm -f "$temporary"
    printf '1bite-battery: source bytes changed during installation; nothing was replaced.\n' >&2
    exit 1
  fi
  if ! directory_matches "$bin_dir" "$bin_identity" "$bin_real"; then
    printf '1bite-battery: ~/.local/bin changed during installation; nothing was published.\n' >&2
    exit 1
  fi
  if [[ -n "$target_sha" ]]; then
    displaced=$(mktemp "$bin_dir/.1bite-battery.previous.XXXXXX")
    rm -f "$displaced"
    if [[ -L "$target" || ! -f "$target" || "$(file_link_count "$target")" != 1 || "$(sha256_file "$target")" != "$target_sha" ]] ||
      ! mv -f "$target" "$displaced" || ! directory_matches "$bin_dir" "$bin_identity" "$bin_real" ||
      [[ -L "$displaced" || ! -f "$displaced" ]] ||
      [[ "$(sha256_file "$displaced")" != "$target_sha" ]]; then
      if [[ -e "$displaced" || -L "$displaced" ]]; then mv -n "$displaced" "$target" || true; fi
      rm -f "$temporary"
      remove_owned_record "$pending" "$PENDING_FILE_SHA" || true
      printf '1bite-battery: installed command changed during publication; it was preserved.\n' >&2
      exit 1
    fi
  elif [[ -e "$target" || -L "$target" ]]; then
    rm -f "$temporary"
    remove_owned_record "$pending" "$PENDING_FILE_SHA" || true
    printf '1bite-battery: a new unowned target appeared during installation; it was preserved.\n' >&2
    exit 1
  fi
  if ! mv -n "$temporary" "$target"; then
    if directory_matches "$bin_dir" "$bin_identity" "$bin_real" &&
      [[ -n "$displaced" && (-e "$displaced" || -L "$displaced") ]]; then
      mv -n "$displaced" "$target" || true
    fi
    printf '1bite-battery: target publication failed; no ownership receipt was written.\n' >&2
    exit 1
  fi
  if ! directory_matches "$bin_dir" "$bin_identity" "$bin_real"; then
    printf '1bite-battery: ~/.local/bin changed during publication; no ownership receipt was written.\n' >&2
    exit 1
  fi
  if [[ -e "$temporary" || -L "$temporary" ]]; then
    rm -f "$temporary"
    if [[ -n "$displaced" && (-e "$displaced" || -L "$displaced") ]]; then mv -n "$displaced" "$target" || true; fi
    remove_owned_record "$pending" "$PENDING_FILE_SHA" || true
    printf '1bite-battery: a target appeared during publication; it was preserved.\n' >&2
    exit 1
  fi
  if ! directory_matches "$bin_dir" "$bin_identity" "$bin_real" ||
    [[ -L "$target" || ! -f "$target" || ! -x "$target" || "$(file_link_count "$target")" != 1 || "$(sha256_file "$target")" != "$current_sha" ]] ||
    ! /bin/bash -n "$target" >/dev/null 2>&1; then
    printf '1bite-battery: installed command verification failed; no ownership receipt was written.\n' >&2
    exit 1
  fi
  if ! directory_matches "$bin_dir" "$bin_identity" "$bin_real"; then
    printf '1bite-battery: ~/.local/bin changed before receipt publication; no ownership receipt was written.\n' >&2
    exit 1
  fi
  if ! publish_record "$receipt" $'one-bite-battery-tool\t1' "$BATTERY_TOOL_VERSION" "$current_sha" "$RECEIPT_FILE_SHA"; then
    printf '1bite-battery: the receipt changed during publication; the new target remains recoverable from its pending record.\n' >&2
    exit 1
  fi
  if ! directory_matches "$PRIVATE_ROOT" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" ||
    ! directory_matches "$bin_dir" "$bin_identity" "$bin_real" ||
    [[ -L "$target" || ! -f "$target" || ! -x "$target" || "$(file_link_count "$target")" != 1 || "$(sha256_file "$target")" != "$current_sha" ]] ||
    ! /bin/bash -n "$target" >/dev/null 2>&1; then
    printf '1bite-battery: managed directories changed after receipt publication; the pending record was retained.\n' >&2
    exit 1
  fi
  if ! remove_owned_record "$pending" "$PENDING_FILE_SHA"; then
    printf '1bite-battery: the pending record changed after publication; it was preserved for review.\n' >&2
    exit 1
  fi
  if ! directory_matches "$PRIVATE_ROOT" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" ||
    ! directory_matches "$bin_dir" "$bin_identity" "$bin_real"; then
    if directory_matches "$PRIVATE_ROOT" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL"; then write_pending "$pending" "$current_sha" || true; fi
    printf '1bite-battery: managed directories changed before final verification.\n' >&2
    exit 1
  fi
  read_receipt "$receipt"
  if [[ "$RECEIPT_VALID" != true || "$RECEIPT_VERSION" != "$BATTERY_TOOL_VERSION" || "$RECEIPT_SHA" != "$current_sha" ||
    -e "$pending" || -L "$pending" || -L "$target" || ! -f "$target" || ! -x "$target" ||
    "$(file_link_count "$target")" != 1 || "$(sha256_file "$target")" != "$current_sha" ]] ||
    ! /bin/bash -n "$target" >/dev/null 2>&1; then
    write_pending "$pending" "$current_sha" || true
    printf '1bite-battery: final managed-tool verification failed.\n' >&2
    exit 1
  fi
  if [[ -n "$displaced" ]] && directory_matches "$bin_dir" "$bin_identity" "$bin_real"; then rm -f "$displaced"; fi
  if ! verify_managed_tool_state "$target" "$receipt" "$pending" "$BATTERY_TOOL_VERSION" "$current_sha" "$bin_dir" "$bin_identity" "$bin_real"; then
    if directory_matches "$PRIVATE_ROOT" "$PRIVATE_ROOT_IDENTITY" "$PRIVATE_ROOT_REAL" && [[ ! -e "$pending" && ! -L "$pending" ]]; then
      write_pending "$pending" "$current_sha" || true
    fi
    printf '1bite-battery: final managed-tool verification failed; success was not reported.\n' >&2
    exit 1
  fi
  printf 'Installed One Bite battery tool: %s\n' "$target"
}

if [[ "$INSTALL_TOOL" == true ]]; then
  install_tool
  exit 0
fi

WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/1bite-battery.XXXXXX")
[[ -d "$WORK_DIR" && ! -L "$WORK_DIR" ]] || {
  printf '1bite-battery: could not create a private work directory.\n' >&2
  exit 1
}
chmod 700 "$WORK_DIR"
trap 'rm -rf "$WORK_DIR"' EXIT HUP INT TERM

BATTERY_PRESENT=
CHARGE_PERCENT=
POWER_SOURCE=unknown
CHARGE_STATE=unknown
CYCLE_COUNT=
MAX_CAPACITY_PERCENT=
MAX_CAPACITY_MAH=
DESIGN_CAPACITY_MAH=
HEALTH=unknown
VOLTAGE_MV=
CURRENT_MA=
PMSET_AVAILABLE=false
HISTORY_AVAILABLE=false

collect_pmset_battery() {
  local command_status key value
  : >"$WORK_DIR/live.tsv"
  if [[ ! -x "$PMSET_BIN" ]]; then
    add_warning pmset_batt_unavailable
    return 0
  fi
  set +e
  LC_ALL=C "$PMSET_BIN" -g batt 2>/dev/null | awk '
    BEGIN { source="unknown"; present=""; percent=""; state="unknown" }
    /Now drawing from/ {
      line=tolower($0)
      if (index(line, "battery power")) source="battery"
      else if (index(line, "ac power")) source="ac"
    }
    /InternalBattery/ {
      present="true"
      line=tolower($0)
      if (index(line, "present: false")) present="false"
      if (match($0, /[0-9][0-9]*[[:space:]]*%/)) {
        value=substr($0, RSTART, RLENGTH)
        gsub(/[^0-9]/, "", value)
        numeric=value+0
        if (numeric >= 0 && numeric <= 100) percent=sprintf("%d", numeric)
      }
      if (index(line, "; not charging;") || index(line, "; not charging ")) state="not_charging"
      else if (index(line, "; discharging;") || index(line, "; discharging ")) state="discharging"
      else if (index(line, "; finishing charge;") || index(line, "; finishing charge ")) state="charging"
      else if (index(line, "; charging;") || index(line, "; charging ")) state="charging"
      else if (index(line, "; charged;") || index(line, "; charged ")) state="charged"
    }
    END {
      if (present == "" && source == "ac") present="false"
      print "present\t" present
      print "power_source\t" source
      print "charge_percent\t" percent
      print "charge_state\t" state
    }
  ' >"$WORK_DIR/live.tsv"
  command_status=${PIPESTATUS[0]}
  set -e
  if [[ $command_status -ne 0 ]]; then
    add_warning pmset_batt_unavailable
    return 0
  fi
  PMSET_AVAILABLE=true
  while IFS=$'\t' read -r key value; do
    case "$key" in
      present) BATTERY_PRESENT=$value ;;
      power_source) POWER_SOURCE=$value ;;
      charge_percent) CHARGE_PERCENT=$value ;;
      charge_state) CHARGE_STATE=$value ;;
    esac
  done <"$WORK_DIR/live.tsv"
  if [[ "$BATTERY_PRESENT" == true && (-z "$CHARGE_PERCENT" || "$POWER_SOURCE" == unknown || "$CHARGE_STATE" == unknown) ]]; then
    add_warning pmset_batt_incomplete
  elif [[ -z "$BATTERY_PRESENT" || ("$BATTERY_PRESENT" != true && "$POWER_SOURCE" == unknown) ]]; then
    add_warning pmset_batt_incomplete
  fi
}

collect_system_profiler() {
  local command_status key value normalized
  : >"$WORK_DIR/profiler.tsv"
  if [[ ! -x "$SYSTEM_PROFILER_BIN" ]]; then
    add_warning system_profiler_unavailable
    return 0
  fi
  set +e
  LC_ALL=C "$SYSTEM_PROFILER_BIN" -detailLevel mini -timeout 15 SPPowerDataType 2>/dev/null | awk -F: '
    function trim(value) {
      sub(/^[[:space:]]+/, "", value)
      sub(/[[:space:]]+$/, "", value)
      return value
    }
    {
      raw=$0
      stripped=raw
      sub(/^[[:space:]]+/, "", stripped)
      leading=raw
      sub(/[^[:space:]].*$/, "", leading)
      indent=length(leading)
      if (stripped == "Battery Information:") {
        in_battery=1
        battery_indent=indent
        next
      }
      if (in_battery && stripped != "" && indent <= battery_indent && stripped ~ /:$/) in_battery=0
      if (!in_battery) next
      key=trim($1)
      value=substr($0, index($0, ":")+1)
      value=trim(value)
      if (key == "Cycle Count" && value ~ /^[0-9]+$/) print "cycle_count\t" value
      else if (key == "Maximum Capacity" && value ~ /^[0-9]+[[:space:]]*%$/) {
        gsub(/[^0-9]/, "", value)
        print "maximum_capacity_percent\t" value
      }
      else if (key == "Condition") {
        lower=tolower(value)
        if (lower == "normal") normalized="normal"
        else if (index(lower, "service recommended")) normalized="service_recommended"
        else if (index(lower, "replace soon")) normalized="replace_soon"
        else if (index(lower, "replace now")) normalized="replace_now"
        else normalized="unknown"
        print "health\t" normalized
      }
    }
  ' >"$WORK_DIR/profiler.tsv"
  command_status=${PIPESTATUS[0]}
  set -e
  if [[ $command_status -ne 0 ]]; then
    add_warning system_profiler_unavailable
    return 0
  fi
  while IFS=$'\t' read -r key value; do
    case "$key" in
      cycle_count)
        normalized=$(normalize_unsigned "$value" 100000) || normalized=
        if [[ -n "$normalized" ]]; then CYCLE_COUNT=$normalized; fi
        ;;
      maximum_capacity_percent)
        normalized=$(normalize_unsigned "$value" 100) || normalized=
        if [[ -n "$normalized" ]]; then MAX_CAPACITY_PERCENT=$normalized; fi
        ;;
      health) HEALTH=$value ;;
    esac
  done <"$WORK_DIR/profiler.tsv"
  return 0
}

collect_ioreg() {
  local command_status key value normalized raw_current=
  : >"$WORK_DIR/ioreg.tsv"
  if [[ ! -x "$IOREG_BIN" ]]; then
    add_warning ioreg_unavailable
    return 0
  fi
  set +e
  LC_ALL=C "$IOREG_BIN" -r -c AppleSmartBattery 2>/dev/null | awk '
    {
      line=$0
      sub(/^[[:space:]|]+/, "", line)
      split(line, halves, " = ")
      key=halves[1]
      gsub(/^"|"$/, "", key)
      value=substr(line, index(line, " = ")+3)
      if (key == "CycleCount" || key == "AppleRawMaxCapacity" || key == "DesignCapacity" ||
          key == "Voltage" || key == "Amperage" || key == "InstantAmperage") {
        if (value ~ /^-?[0-9]+$/) print key "\t" value
      } else if (key == "BatteryInstalled" && (value == "Yes" || value == "No")) {
        print key "\t" value
      }
    }
  ' >"$WORK_DIR/ioreg.tsv"
  command_status=${PIPESTATUS[0]}
  set -e
  if [[ $command_status -ne 0 ]]; then
    add_warning ioreg_unavailable
    return 0
  fi
  while IFS=$'\t' read -r key value; do
    case "$key" in
      CycleCount)
        if [[ -z "$CYCLE_COUNT" ]]; then
          normalized=$(normalize_unsigned "$value" 100000) || normalized=
          if [[ -n "$normalized" ]]; then CYCLE_COUNT=$normalized; fi
        fi
        ;;
      AppleRawMaxCapacity)
        normalized=$(normalize_unsigned "$value" 100000) || normalized=
        if [[ -n "$normalized" ]]; then MAX_CAPACITY_MAH=$normalized; fi
        ;;
      DesignCapacity)
        normalized=$(normalize_unsigned "$value" 100000) || normalized=
        if [[ -n "$normalized" ]]; then DESIGN_CAPACITY_MAH=$normalized; fi
        ;;
      Voltage)
        normalized=$(normalize_unsigned "$value" 100000) || normalized=
        if [[ -n "$normalized" ]]; then VOLTAGE_MV=$normalized; fi
        ;;
      InstantAmperage) raw_current=$value ;;
      Amperage) [[ -n "$raw_current" ]] || raw_current=$value ;;
      BatteryInstalled)
        if [[ "$PMSET_AVAILABLE" != true ]]; then
          if [[ "$value" == Yes ]]; then BATTERY_PRESENT=true; else BATTERY_PRESENT=false; fi
        fi
        ;;
    esac
  done <"$WORK_DIR/ioreg.tsv"
  if [[ -n "$raw_current" ]]; then
    normalized=$(normalize_current_ma "$raw_current") || normalized=
    if [[ -n "$normalized" ]]; then CURRENT_MA=$normalized; fi
  fi
  return 0
}

collect_pmset_battery
if [[ "$BATTERY_PRESENT" == true ]]; then
  collect_system_profiler
  collect_ioreg
fi

if ! read -r COLLECTED_EPOCH COLLECTED_AT < <("$DATE_BIN" -u '+%s %Y-%m-%dT%H:%M:%SZ'); then
  printf '1bite-battery: system date could not provide a collection time.\n' >&2
  exit 1
fi
COLLECTED_EPOCH=$(normalize_unsigned "$COLLECTED_EPOCH" 99999999999) || {
  printf '1bite-battery: system date returned an invalid epoch.\n' >&2
  exit 1
}
COLLECTED_AT_EPOCH=$(utc_iso_epoch "$COLLECTED_AT") || {
  printf '1bite-battery: system date returned an invalid UTC timestamp.\n' >&2
  exit 1
}
if [[ "$COLLECTED_AT_EPOCH" != "$COLLECTED_EPOCH" ]]; then
  printf '1bite-battery: system date returned inconsistent timestamp values.\n' >&2
  exit 1
fi

CACHE_READABLE=false
CACHE_WRITABLE=false
CACHE_FILE=
PRIVATE_DIR_READY=false

cache_valid() {
  awk -F '\t' -v max_events="$MAX_RETAINED_EVENTS" '
    function uint(value) { return value ~ /^(0|[1-9][0-9]*)$/ }
    function sint(value) { return value ~ /^(0|[1-9][0-9]*|-[1-9][0-9]*)$/ }
    function leap(year) { return (year % 4 == 0 && year % 100 != 0) || year % 400 == 0 }
    function dim(year, month) {
      if (month == 2) return 28 + leap(year)
      if (month == 4 || month == 6 || month == 9 || month == 11) return 30
      return 31
    }
    function iso_epoch(value, year, month, day, hour, minute, second, zone_hour, zone_minute, sign, days, cursor, offset) {
      if (length(value) != 20 && length(value) != 25) return -1
      if (substr(value,5,1) != "-" || substr(value,8,1) != "-" || substr(value,11,1) != "T" ||
          substr(value,14,1) != ":" || substr(value,17,1) != ":") return -1
      if (substr(value,1,4) !~ /^[0-9][0-9][0-9][0-9]$/ ||
          substr(value,6,2) !~ /^[0-9][0-9]$/ || substr(value,9,2) !~ /^[0-9][0-9]$/ ||
          substr(value,12,2) !~ /^[0-9][0-9]$/ || substr(value,15,2) !~ /^[0-9][0-9]$/ ||
          substr(value,18,2) !~ /^[0-9][0-9]$/) return -1
      year=substr(value,1,4)+0; month=substr(value,6,2)+0; day=substr(value,9,2)+0
      hour=substr(value,12,2)+0; minute=substr(value,15,2)+0; second=substr(value,18,2)+0
      if (year < 1970 || month < 1 || month > 12 || day < 1 || day > dim(year,month) ||
          hour > 23 || minute > 59 || second > 59) return -1
      offset=0
      if (length(value) == 20) {
        if (substr(value,20,1) != "Z") return -1
      } else {
        if ((substr(value,20,1) != "+" && substr(value,20,1) != "-") || substr(value,23,1) != ":" ||
            substr(value,21,2) !~ /^[0-9][0-9]$/ || substr(value,24,2) !~ /^[0-9][0-9]$/) return -1
        zone_hour=substr(value,21,2)+0; zone_minute=substr(value,24,2)+0
        if (zone_hour > 14 || zone_minute > 59 || (zone_hour == 14 && zone_minute != 0)) return -1
        sign=(substr(value,20,1) == "-") ? -1 : 1
        offset=(zone_hour*60+zone_minute)*60*sign
      }
      days=0
      for (cursor=1970; cursor<year; cursor++) days += 365 + leap(cursor)
      for (cursor=1; cursor<month; cursor++) days += dim(year,cursor)
      days += day-1
      return days*86400 + hour*3600 + minute*60 + second - offset
    }
    NR == 1 { if ($0 != "one-bite-battery-history\t1") exit 1; next }
    $1 == "event" {
      if (NF != 6 || !uint($2) || $4 !~ /^(ac|battery)$/ ||
          !uint($5) || $5+0 > 100 || !uint($6) || $6+0 > 999999 ||
          iso_epoch($3) != $2+0 || event_count >= max_events) exit 1
      if (event_count > 0 && ($2+0 < previous_epoch || ($2+0 == previous_epoch && $6+0 < previous_ordinal) ||
          $4 == previous_source)) exit 1
      previous_epoch=$2+0; previous_ordinal=$6+0; previous_source=$4
      event_count++
      next
    }
    $1 == "interval" {
      if (NF != 12 || !uint($2) || $3 !~ /^(ac|battery)$/ ||
          !uint($4) || !uint($6) || $6+0 > 100 ||
          !uint($7) || !uint($9) || $9+0 > 100 ||
          !sint($10) || !uint($11) || $12 !~ /^(true|false)$/ ||
          $2+0 != interval_count || iso_epoch($5) != $4+0 || iso_epoch($8) != $7+0 ||
          $7+0 < $4+0 || $10+0 != $9+0-$6+0 || $11+0 != $7+0-$4+0 || seen_open) exit 1
      if ($12 == "false") seen_open=1
      interval_count++
      next
    }
    { exit 1 }
    END {
      if (NR < 1 || (interval_count != event_count && interval_count != event_count-1)) exit 1
    }
  ' "$1" >/dev/null
}

prepare_cache() {
  local first_line=
  [[ "$CACHE_ENABLED" == true && "$BATTERY_PRESENT" == true ]] || return 0
  ensure_private_battery_dir
  if [[ "$PRIVATE_DIR_READY" != true ]]; then return 0; fi
  CACHE_FILE="$PRIVATE_ROOT/history-v1.tsv"
  if [[ -L "$CACHE_FILE" ]]; then
    add_warning cache_symlink
    return 0
  fi
  CACHE_WRITABLE=true
  if [[ ! -e "$CACHE_FILE" ]]; then return 0; fi
  if [[ ! -f "$CACHE_FILE" ]]; then
    add_warning cache_unsafe
    CACHE_WRITABLE=false
    return 0
  fi
  IFS= read -r first_line <"$CACHE_FILE" || true
  if [[ "$first_line" != $'one-bite-battery-history\t1' ]]; then
    add_warning cache_unknown
    CACHE_WRITABLE=false
    return 0
  fi
  set +e
  cache_valid "$CACHE_FILE"
  local valid_status=$?
  set -e
  if [[ $valid_status -eq 0 ]]; then
    CACHE_READABLE=true
  else
    add_warning cache_corrupt
  fi
}

parse_history_stream() {
  awk '
    function leap(year) { return (year % 4 == 0 && year % 100 != 0) || year % 400 == 0 }
    function dim(year, month) {
      if (month == 2) return 28 + leap(year)
      if (month == 4 || month == 6 || month == 9 || month == 11) return 30
      return 31
    }
    function epoch_for(stamp, zone, values, date_values, time_values, year, month, day, hour, minute, second, zone_hour, zone_minute, days, cursor, offset, sign) {
      split(stamp, values, " ")
      split(values[1], date_values, "-")
      split(values[2], time_values, ":")
      year=date_values[1]+0; month=date_values[2]+0; day=date_values[3]+0
      hour=time_values[1]+0; minute=time_values[2]+0; second=time_values[3]+0
      if (year < 1970 || month < 1 || month > 12 || day < 1 || day > dim(year, month) ||
          hour < 0 || hour > 23 || minute < 0 || minute > 59 || second < 0 || second > 59) return -1
      zone_hour=substr(zone,2,2)+0; zone_minute=substr(zone,4,2)+0
      if (zone_hour > 14 || zone_minute > 59 || (zone_hour == 14 && zone_minute != 0)) return -1
      days=0
      for (cursor=1970; cursor<year; cursor++) days += 365 + leap(cursor)
      for (cursor=1; cursor<month; cursor++) days += dim(year, cursor)
      days += day-1
      sign=(substr(zone,1,1) == "-") ? -1 : 1
      offset=(zone_hour*60 + zone_minute)*60*sign
      return days*86400 + hour*3600 + minute*60 + second - offset
    }
    {
      upper=toupper($0)
      candidate=(upper ~ /USING[[:space:]]+(AC|BATT|BATTERY)([[:space:]]|\()/ &&
        upper ~ /CHARGE[[:space:]]*:[[:space:]]*[0-9]/)
      if (!candidate) next
      candidates++
      if (length($0) < 26) next
      stamp=substr($0,1,19)
      zone=substr($0,21,5)
      if (substr(stamp,5,1) != "-" || substr(stamp,8,1) != "-" || substr(stamp,11,1) != " " ||
          substr(stamp,14,1) != ":" || substr(stamp,17,1) != ":") next
      if ((substr(zone,1,1) != "+" && substr(zone,1,1) != "-") || substr(zone,2) !~ /^[0-9][0-9][0-9][0-9]$/) next
      if (upper ~ /USING[[:space:]]+AC([[:space:]]|\()/) source="ac"
      else if (upper ~ /USING[[:space:]]+(BATT|BATTERY)([[:space:]]|\()/) source="battery"
      else next
      if (!match(upper, /CHARGE[[:space:]]*:[[:space:]]*[0-9][0-9]*/)) next
      charge=substr(upper, RSTART, RLENGTH)
      sub(/^.*:/, "", charge)
      gsub(/[[:space:]]/, "", charge)
      if (charge ~ /^[0-9][0-9]*$/) raw=charge; else next
      percent=raw+0
      if (percent < 0 || percent > 100) next
      epoch=epoch_for(stamp, zone)
      if (epoch < 0) next
      if (epoch == previous_epoch) ordinal++
      else { previous_epoch=epoch; ordinal=0 }
      iso=substr(stamp,1,10) "T" substr(stamp,12) substr(zone,1,3) ":" substr(zone,4,2)
      printf "event\t%.0f\t%s\t%s\t%d\t%d\n", epoch, iso, source, percent, ordinal
      parsed++
    }
    END {
      if (candidates > parsed && parsed > 0) exit 43
      if (NR > 0 && parsed == 0) exit 42
    }
  '
}

collect_history() {
  local -a pipeline_status
  : >"$WORK_DIR/fresh-events.tsv"
  if [[ ! -x "$PMSET_BIN" ]]; then
    add_warning history_unavailable
    return 0
  fi
  set +e
  LC_ALL=C "$PMSET_BIN" -g log 2>/dev/null | parse_history_stream >"$WORK_DIR/fresh-events.tsv"
  pipeline_status=("${PIPESTATUS[@]}")
  set -e
  if [[ ${pipeline_status[0]} -ne 0 ]]; then
    add_warning history_unavailable
    : >"$WORK_DIR/fresh-events.tsv"
    return 0
  fi
  if [[ ${pipeline_status[1]:-1} -ne 0 ]]; then
    if [[ ${pipeline_status[1]} -eq 43 ]]; then
      add_warning history_parse_partial
    else
      add_warning history_parse_failed
    fi
    : >"$WORK_DIR/fresh-events.tsv"
    return 0
  fi
  HISTORY_AVAILABLE=true
}

if [[ "$OUTPUT_FORMAT" != summary ]]; then prepare_cache; fi
: >"$WORK_DIR/combined-events.tsv"
if [[ "$BATTERY_PRESENT" == true && "$OUTPUT_FORMAT" != summary ]]; then
  if [[ "$CACHE_READABLE" == true ]]; then
    awk -F '\t' '$1 == "event" { print }' "$CACHE_FILE" >>"$WORK_DIR/combined-events.tsv"
  fi
  collect_history
  cat "$WORK_DIR/fresh-events.tsv" >>"$WORK_DIR/combined-events.tsv"
  if [[ -n "$CHARGE_PERCENT" && ("$POWER_SOURCE" == ac || "$POWER_SOURCE" == battery) ]]; then
    printf 'event\t%s\t%s\t%s\t%s\t999999\n' "$COLLECTED_EPOCH" "$COLLECTED_AT" "$POWER_SOURCE" "$CHARGE_PERCENT" >>"$WORK_DIR/combined-events.tsv"
  fi
fi

TAB=$'\t'
LC_ALL=C sort -t "$TAB" -k2,2n -k6,6n -k3,3 -k4,4 "$WORK_DIR/combined-events.tsv" | awk -F '\t' -v now="$COLLECTED_EPOCH" '
  $1 == "event" && $2+0 <= now+0 {
    key=$2 FS $3 FS $4 FS $5 FS $6
    if (seen[key]++) next
    if ($4 != previous_source) {
      print
      previous_source=$4
    }
  }
' | tail -n "$MAX_RETAINED_EVENTS" >"$WORK_DIR/events.tsv"

awk -F '\t' -v end_epoch="$COLLECTED_EPOCH" -v end_iso="$COLLECTED_AT" -v end_percent="${CHARGE_PERCENT:-}" '
  function emit_interval(source, start_epoch, start_iso, start_percent, finish_epoch, finish_iso, finish_percent, complete, duration, delta) {
    duration=finish_epoch-start_epoch
    if (duration < 0) return
    delta=finish_percent-start_percent
    printf "interval\t%d\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%d\t%d\t%s\n", count++, source,
      start_epoch, start_iso, start_percent, finish_epoch, finish_iso, finish_percent, delta, duration, complete
  }
  NR == 1 {
    previous_source=$4; previous_epoch=$2; previous_iso=$3; previous_percent=$5
    next
  }
  {
    emit_interval(previous_source, previous_epoch, previous_iso, previous_percent, $2, $3, $5, "true")
    previous_source=$4; previous_epoch=$2; previous_iso=$3; previous_percent=$5
  }
  END {
    if (NR > 0 && end_percent ~ /^[0-9]+$/ && end_epoch+0 >= previous_epoch+0)
      emit_interval(previous_source, previous_epoch, previous_iso, previous_percent, end_epoch, end_iso, end_percent, "false")
  }
' "$WORK_DIR/events.tsv" >"$WORK_DIR/intervals.tsv"

RETAINED_EVENT_COUNT=$(awk 'END { print NR+0 }' "$WORK_DIR/events.tsv")
INTERVAL_COUNT=$(awk 'END { print NR+0 }' "$WORK_DIR/intervals.tsv")

write_cache() {
  local temporary valid_status
  [[ "$CACHE_WRITABLE" == true ]] || return 0
  if path_has_symlink "$PRIVATE_ROOT" || [[ -L "$CACHE_FILE" ]]; then
    add_warning cache_symlink
    return 0
  fi
  if ! temporary=$(mktemp "$PRIVATE_ROOT/.history-v1.tsv.XXXXXX" 2>/dev/null); then
    add_warning cache_write_failed
    return 0
  fi
  if ! printf 'one-bite-battery-history\t1\n' >"$temporary" ||
    ! cat "$WORK_DIR/events.tsv" >>"$temporary" ||
    ! cat "$WORK_DIR/intervals.tsv" >>"$temporary" ||
    ! chmod 600 "$temporary"; then
    rm -f "$temporary"
    add_warning cache_write_failed
    return 0
  fi
  set +e
  cache_valid "$temporary"
  valid_status=$?
  set -e
  if [[ $valid_status -ne 0 ]]; then
    rm -f "$temporary"
    add_warning cache_write_invalid
    return 0
  fi
  if path_has_symlink "$PRIVATE_ROOT" || [[ -L "$CACHE_FILE" ]]; then
    rm -f "$temporary"
    add_warning cache_symlink
    return 0
  fi
  if ! mv -f "$temporary" "$CACHE_FILE"; then
    rm -f "$temporary"
    add_warning cache_write_failed
  fi
}

if [[ "$BATTERY_PRESENT" == true ]]; then write_cache; fi

if [[ "$PMSET_AVAILABLE" != true || -z "$BATTERY_PRESENT" || ("$BATTERY_PRESENT" != true && "$POWER_SOURCE" == unknown) ]]; then
  REPORT_STATUS=unavailable
elif [[ "$BATTERY_PRESENT" != true ]]; then
  REPORT_STATUS=no_battery
elif [[ -z "$CHARGE_PERCENT" || "$POWER_SOURCE" == unknown || "$CHARGE_STATE" == unknown || -z "$CYCLE_COUNT" || -z "$MAX_CAPACITY_PERCENT" || -z "$MAX_CAPACITY_MAH" || -z "$DESIGN_CAPACITY_MAH" || "$HEALTH" == unknown || -z "$VOLTAGE_MV" || -z "$CURRENT_MA" || "$HISTORY_AVAILABLE" != true ]]; then
  REPORT_STATUS=partial
  add_warning metrics_incomplete
else
  REPORT_STATUS=ok
fi
if [[ "$REPORT_STATUS" == ok || "$REPORT_STATUS" == no_battery ]]; then REPORT_COMPLETE=true; else REPORT_COMPLETE=false; fi

json_number() {
  if [[ -n "$1" ]]; then printf '%s' "$1"; else printf 'null'; fi
}

json_boolean_or_null() {
  if [[ -n "$1" ]]; then printf '%s' "$1"; else printf 'null'; fi
}

json_quote() {
  local value=$1
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  value=${value//$'\n'/\\n}
  value=${value//$'\r'/\\r}
  value=${value//$'\t'/\\t}
  printf '"%s"' "$value"
}

json_string_or_null() {
  if [[ -n "$1" ]]; then json_quote "$1"; else printf 'null'; fi
}

print_warning_json() {
  local warning first=true
  printf '['
  for warning in $WARNINGS; do
    if [[ "$first" == true ]]; then first=false; else printf ','; fi
    json_quote "$warning"
  done
  printf ']'
}

print_intervals_json() {
  local record index source start_at start_percent end_at end_percent delta duration complete first=true
  printf '['
  while IFS=$'\t' read -r record index source _ start_at start_percent _ end_at end_percent delta duration complete; do
    [[ "$record" == interval ]] || continue
    if [[ "$first" == true ]]; then first=false; else printf ','; fi
    printf '{"source":'
    json_quote "$source"
    printf ',"start_at":'
    json_quote "$start_at"
    printf ',"end_at":'
    json_quote "$end_at"
    printf ',"start_percent":%s,"end_percent":%s,"delta_percent":%s,"duration_seconds":%s,"complete":%s}' \
      "$start_percent" "$end_percent" "$delta" "$duration" "$complete"
  done <"$WORK_DIR/intervals.tsv"
  printf ']'
}

print_json() {
  printf '{'
  printf '"schema_version":%s,' "$BATTERY_SCHEMA_VERSION"
  printf '"collected_at":'
  json_quote "$COLLECTED_AT"
  printf ',"status":'
  json_quote "$REPORT_STATUS"
  printf ','
  printf '"complete":%s,' "$REPORT_COMPLETE"
  printf '"battery":{'
  printf '"present":'
  json_boolean_or_null "$BATTERY_PRESENT"
  printf ','
  printf '"charge_percent":'
  json_number "$CHARGE_PERCENT"
  printf ','
  printf '"power_source":'
  json_string_or_null "$POWER_SOURCE"
  printf ','
  printf '"state":'
  json_string_or_null "$CHARGE_STATE"
  printf ','
  printf '"cycle_count":'
  json_number "$CYCLE_COUNT"
  printf ','
  printf '"maximum_capacity_percent":'
  json_number "$MAX_CAPACITY_PERCENT"
  printf ','
  printf '"maximum_capacity_mah":'
  json_number "$MAX_CAPACITY_MAH"
  printf ','
  printf '"design_capacity_mah":'
  json_number "$DESIGN_CAPACITY_MAH"
  printf ','
  printf '"health":'
  json_quote "$HEALTH"
  printf ','
  printf '"voltage_mv":'
  json_number "$VOLTAGE_MV"
  printf ','
  printf '"current_ma":'
  json_number "$CURRENT_MA"
  printf '},'
  printf '"history":{"duration_basis":"wall_clock","may_include_sleep":true,"is_lifetime":false,"retained_event_count":%s,"interval_count":%s,"intervals":' "$RETAINED_EVENT_COUNT" "$INTERVAL_COUNT"
  print_intervals_json
  printf '},"warning_codes":'
  print_warning_json
  printf '}\n'
}

tsv_value() {
  if [[ -n "$1" ]]; then printf '%s' "$1"; else printf 'null'; fi
}

print_tsv_row() {
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$BATTERY_SCHEMA_VERSION" "$1" "$2" "$3" "$4" "$5"
}

print_tsv() {
  local record index source start_at start_percent end_at end_percent delta duration complete warning warning_index=0
  printf 'schema_version\tsection\tindex\tkey\tvalue\tunit\n'
  print_tsv_row meta - collected_at "$COLLECTED_AT" iso8601
  print_tsv_row meta - status "$REPORT_STATUS" enum
  print_tsv_row meta - complete "$REPORT_COMPLETE" boolean
  print_tsv_row battery - present "$(tsv_value "$BATTERY_PRESENT")" boolean
  print_tsv_row battery - charge_percent "$(tsv_value "$CHARGE_PERCENT")" percent
  print_tsv_row battery - power_source "$POWER_SOURCE" enum
  print_tsv_row battery - state "$CHARGE_STATE" enum
  print_tsv_row battery - cycle_count "$(tsv_value "$CYCLE_COUNT")" equivalent_full_cycles
  print_tsv_row battery - maximum_capacity_percent "$(tsv_value "$MAX_CAPACITY_PERCENT")" percent
  print_tsv_row battery - maximum_capacity_mah "$(tsv_value "$MAX_CAPACITY_MAH")" mAh
  print_tsv_row battery - design_capacity_mah "$(tsv_value "$DESIGN_CAPACITY_MAH")" mAh
  print_tsv_row battery - health "$HEALTH" enum
  print_tsv_row battery - voltage_mv "$(tsv_value "$VOLTAGE_MV")" mV
  print_tsv_row battery - current_ma "$(tsv_value "$CURRENT_MA")" mA
  print_tsv_row history - duration_basis wall_clock enum
  print_tsv_row history - may_include_sleep true boolean
  print_tsv_row history - is_lifetime false boolean
  print_tsv_row history - retained_event_count "$RETAINED_EVENT_COUNT" count
  print_tsv_row history - interval_count "$INTERVAL_COUNT" count
  while IFS=$'\t' read -r record index source _ start_at start_percent _ end_at end_percent delta duration complete; do
    [[ "$record" == interval ]] || continue
    print_tsv_row interval "$index" source "$source" enum
    print_tsv_row interval "$index" start_at "$start_at" iso8601
    print_tsv_row interval "$index" end_at "$end_at" iso8601
    print_tsv_row interval "$index" start_percent "$start_percent" percent
    print_tsv_row interval "$index" end_percent "$end_percent" percent
    print_tsv_row interval "$index" delta_percent "$delta" percentage_points
    print_tsv_row interval "$index" duration_seconds "$duration" seconds
    print_tsv_row interval "$index" complete "$complete" boolean
  done <"$WORK_DIR/intervals.tsv"
  for warning in $WARNINGS; do
    print_tsv_row warning "$warning_index" code "$warning" enum
    warning_index=$((warning_index + 1))
  done
}

shell_assignment() {
  local name=$1 value=$2
  value=${value//\'/\'"\'"\'}
  printf "%s='%s'\n" "$name" "$value"
}

print_shell() {
  local record index source start_at start_percent end_at end_percent delta duration complete prefix
  cat <<'SHELL_CLEANUP'
case ${ONE_BITE_BATTERY_INTERVAL_COUNT-} in
  [0-9]|[0-9][0-9]|[0-9][0-9][0-9]) one_bite_battery_previous_intervals=$((10#$ONE_BITE_BATTERY_INTERVAL_COUNT)) ;;
  *) one_bite_battery_previous_intervals=0 ;;
esac
if ((one_bite_battery_previous_intervals > 256)); then one_bite_battery_previous_intervals=256; fi
one_bite_battery_interval_index=0
while ((one_bite_battery_interval_index < one_bite_battery_previous_intervals)); do
  for one_bite_battery_interval_suffix in SOURCE START_AT END_AT START_PERCENT END_PERCENT DELTA_PERCENT DURATION_SECONDS COMPLETE; do
    unset "ONE_BITE_BATTERY_INTERVAL_${one_bite_battery_interval_index}_${one_bite_battery_interval_suffix}"
  done
  one_bite_battery_interval_index=$((one_bite_battery_interval_index + 1))
done
unset one_bite_battery_previous_intervals one_bite_battery_interval_index one_bite_battery_interval_suffix
SHELL_CLEANUP
  shell_assignment ONE_BITE_BATTERY_SCHEMA_VERSION "$BATTERY_SCHEMA_VERSION"
  shell_assignment ONE_BITE_BATTERY_COLLECTED_AT "$COLLECTED_AT"
  shell_assignment ONE_BITE_BATTERY_STATUS "$REPORT_STATUS"
  shell_assignment ONE_BITE_BATTERY_COMPLETE "$REPORT_COMPLETE"
  shell_assignment ONE_BITE_BATTERY_PRESENT "$BATTERY_PRESENT"
  shell_assignment ONE_BITE_BATTERY_CHARGE_PERCENT "$CHARGE_PERCENT"
  shell_assignment ONE_BITE_BATTERY_POWER_SOURCE "$POWER_SOURCE"
  shell_assignment ONE_BITE_BATTERY_STATE "$CHARGE_STATE"
  shell_assignment ONE_BITE_BATTERY_CYCLE_COUNT "$CYCLE_COUNT"
  shell_assignment ONE_BITE_BATTERY_MAXIMUM_CAPACITY_PERCENT "$MAX_CAPACITY_PERCENT"
  shell_assignment ONE_BITE_BATTERY_MAXIMUM_CAPACITY_MAH "$MAX_CAPACITY_MAH"
  shell_assignment ONE_BITE_BATTERY_DESIGN_CAPACITY_MAH "$DESIGN_CAPACITY_MAH"
  shell_assignment ONE_BITE_BATTERY_HEALTH "$HEALTH"
  shell_assignment ONE_BITE_BATTERY_VOLTAGE_MV "$VOLTAGE_MV"
  shell_assignment ONE_BITE_BATTERY_CURRENT_MA "$CURRENT_MA"
  shell_assignment ONE_BITE_BATTERY_DURATION_BASIS wall_clock
  shell_assignment ONE_BITE_BATTERY_MAY_INCLUDE_SLEEP true
  shell_assignment ONE_BITE_BATTERY_IS_LIFETIME false
  shell_assignment ONE_BITE_BATTERY_RETAINED_EVENT_COUNT "$RETAINED_EVENT_COUNT"
  shell_assignment ONE_BITE_BATTERY_INTERVAL_COUNT "$INTERVAL_COUNT"
  shell_assignment ONE_BITE_BATTERY_WARNING_CODES "$WARNINGS"
  while IFS=$'\t' read -r record index source _ start_at start_percent _ end_at end_percent delta duration complete; do
    [[ "$record" == interval ]] || continue
    prefix="ONE_BITE_BATTERY_INTERVAL_${index}"
    shell_assignment "${prefix}_SOURCE" "$source"
    shell_assignment "${prefix}_START_AT" "$start_at"
    shell_assignment "${prefix}_END_AT" "$end_at"
    shell_assignment "${prefix}_START_PERCENT" "$start_percent"
    shell_assignment "${prefix}_END_PERCENT" "$end_percent"
    shell_assignment "${prefix}_DELTA_PERCENT" "$delta"
    shell_assignment "${prefix}_DURATION_SECONDS" "$duration"
    shell_assignment "${prefix}_COMPLETE" "$complete"
  done <"$WORK_DIR/intervals.tsv"
}

field_value() {
  case "$FIELD_NAME" in
    schema_version) printf '%s' "$BATTERY_SCHEMA_VERSION" ;;
    collected_at) printf '%s' "$COLLECTED_AT" ;;
    status) printf '%s' "$REPORT_STATUS" ;;
    complete) printf '%s' "$REPORT_COMPLETE" ;;
    battery.present) printf '%s' "$BATTERY_PRESENT" ;;
    battery.charge_percent) printf '%s' "$CHARGE_PERCENT" ;;
    battery.power_source) printf '%s' "$POWER_SOURCE" ;;
    battery.state) printf '%s' "$CHARGE_STATE" ;;
    battery.cycle_count) printf '%s' "$CYCLE_COUNT" ;;
    battery.maximum_capacity_percent) printf '%s' "$MAX_CAPACITY_PERCENT" ;;
    battery.maximum_capacity_mah) printf '%s' "$MAX_CAPACITY_MAH" ;;
    battery.design_capacity_mah) printf '%s' "$DESIGN_CAPACITY_MAH" ;;
    battery.health) printf '%s' "$HEALTH" ;;
    battery.voltage_mv) printf '%s' "$VOLTAGE_MV" ;;
    battery.current_ma) printf '%s' "$CURRENT_MA" ;;
    history.retained_event_count) printf '%s' "$RETAINED_EVENT_COUNT" ;;
    history.interval_count) printf '%s' "$INTERVAL_COUNT" ;;
    *)
      printf '1bite-battery: unknown field: %s\n' "$FIELD_NAME" >&2
      exit 2
      ;;
  esac
}

print_field() {
  local value
  value=$(field_value)
  if [[ -z "$value" ]]; then exit 3; fi
  printf '%s\n' "$value"
}

human_value() {
  if [[ -n "$1" ]]; then printf '%s' "$1"; else printf 'unavailable'; fi
}

format_duration() {
  local total=$1 days hours minutes
  days=$((total / 86400))
  hours=$(((total % 86400) / 3600))
  minutes=$(((total % 3600) / 60))
  if [[ $days -gt 0 ]]; then
    printf '%dd %dh %dm' "$days" "$hours" "$minutes"
  elif [[ $hours -gt 0 ]]; then
    printf '%dh %dm' "$hours" "$minutes"
  else
    printf '%dm' "$minutes"
  fi
}

print_dashboard() {
  local record index source start_at start_percent end_at end_percent delta duration complete shown=0
  printf 'One Bite Battery\n'
  printf '================\n'
  printf 'Status: %s\n' "$REPORT_STATUS"
  if [[ "$REPORT_STATUS" == unavailable ]]; then
    printf 'Battery data: unavailable\n'
  elif [[ "$BATTERY_PRESENT" != true ]]; then
    printf 'Battery: not present\n'
  else
    printf 'Charge: %s%% (%s, %s)\n' "$(human_value "$CHARGE_PERCENT")" "$POWER_SOURCE" "$CHARGE_STATE"
    printf 'Health: %s; maximum capacity %s%% (%s mAh of %s mAh design)\n' "$HEALTH" \
      "$(human_value "$MAX_CAPACITY_PERCENT")" "$(human_value "$MAX_CAPACITY_MAH")" "$(human_value "$DESIGN_CAPACITY_MAH")"
    printf 'Cycle count: %s equivalent full cycles\n' "$(human_value "$CYCLE_COUNT")"
    printf 'Electrical: %s mV, %s mA\n' "$(human_value "$VOLTAGE_MV")" "$(human_value "$CURRENT_MA")"
    printf '\nRecent power intervals (%s retained):\n' "$INTERVAL_COUNT"
    while IFS=$'\t' read -r record index source _ start_at start_percent _ end_at end_percent delta duration complete; do
      [[ "$record" == interval ]] || continue
      if [[ $((INTERVAL_COUNT - index)) -le 8 ]]; then
        printf '  %s  %3s%% -> %3s%%  %8s  %s -> %s%s\n' "$source" "$start_percent" "$end_percent" \
          "$(format_duration "$duration")" "$start_at" "$end_at" "$([[ "$complete" == false ]] && printf ' (open)')"
        shown=$((shown + 1))
      fi
    done <"$WORK_DIR/intervals.tsv"
    [[ $shown -gt 0 ]] || printf '  No usable transition history was found.\n'
  fi
  printf '\nNotes:\n'
  printf '  - Cycle count means equivalent full cycles, not the number of times power was connected.\n'
  printf '  - Durations are wall-clock time and may include sleep.\n'
  printf '  - The listed interval count covers retained recent observations, not lifetime charge/discharge totals.\n'
  printf '  - Only allowlisted battery fields are shown; device and account identifiers are never retained.\n'
  if [[ -n "$WARNINGS" ]]; then printf 'Warnings: %s\n' "$WARNINGS"; fi
}

print_summary() {
  local charge='unavailable' source='power source unavailable' state='state unavailable'
  local maximum='unavailable' cycles='unavailable'
  if [[ "$REPORT_STATUS" == unavailable ]]; then
    printf 'Battery: unavailable; setup will continue.\n'
    return
  fi
  if [[ "$BATTERY_PRESENT" != true ]]; then
    printf 'Battery: not present.\n'
    return
  fi
  if [[ -n "$CHARGE_PERCENT" ]]; then charge="$CHARGE_PERCENT%"; fi
  case "$POWER_SOURCE" in
    ac) source='AC power' ;;
    battery) source='battery power' ;;
  esac
  case "$CHARGE_STATE" in
    charging) state=charging ;;
    charged) state=charged ;;
    discharging) state=discharging ;;
    not_charging) state='not charging' ;;
  esac
  if [[ -n "$MAX_CAPACITY_PERCENT" ]]; then maximum="$MAX_CAPACITY_PERCENT%"; fi
  if [[ -n "$CYCLE_COUNT" ]]; then cycles="$CYCLE_COUNT equivalent full cycles"; fi
  printf 'Battery: charge %s; %s, %s; maximum capacity %s; cycle count %s.\n' \
    "$charge" "$source" "$state" "$maximum" "$cycles"
}

case "$OUTPUT_FORMAT" in
  dashboard) print_dashboard ;;
  summary) print_summary ;;
  json) print_json ;;
  tsv) print_tsv ;;
  shell) print_shell ;;
  field) print_field ;;
esac

if [[ "$REPORT_STATUS" == unavailable ]]; then exit 1; fi
