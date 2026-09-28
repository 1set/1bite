# Managed by 1bite: media helpers. Personal overrides belong after the source in .zshrc.
# Media conversion helpers use tools already declared by the installer.
function ffmpeg2wav {
  (( $# )) || { print -u2 'usage: ffmpeg2wav <media> [...]'; return 1; }
  local file target
  for file in "$@"; do
    [[ -f $file ]] || { print -u2 "not a file: $file"; return 1; }
    target="${file:r}.wav"
    command ffmpeg -nostdin -hide_banner -loglevel warning -n -i "$file" \
      -acodec pcm_s16le -ac 1 -ar 16000 -f wav "$target" || return
  done
}
function video2wav { ffmpeg2wav "$@"; }
function ffmpeg2pcm {
  (( $# )) || { print -u2 'usage: ffmpeg2pcm <media> [...]'; return 1; }
  local file target
  for file in "$@"; do
    [[ -f $file ]] || { print -u2 "not a file: $file"; return 1; }
    target="${file:r}.pcm"
    command ffmpeg -nostdin -hide_banner -loglevel warning -n -i "$file" \
      -acodec pcm_s16le -ac 1 -ar 16000 -f s16le "$target" || return
  done
}
function pcm2wav {
  (( $# )) || { print -u2 'usage: pcm2wav <16-bit-16k-mono-pcm> [...]'; return 1; }
  local file target
  for file in "$@"; do
    [[ -f $file ]] || { print -u2 "not a file: $file"; return 1; }
    target="${file:r}.wav"
    command ffmpeg -nostdin -hide_banner -loglevel warning -n -f s16le -ar 16000 -ac 1 \
      -i "$file" "$target" || return
  done
}
function heic2jpg {
  (( $# )) || { print -u2 'usage: heic2jpg <image.heic> [...]'; return 1; }
  local file
  for file in "$@"; do
    [[ -f $file && ${file:e:l} == heic ]] || { print -u2 "not a HEIC file: $file"; return 1; }
    command sips -s format jpeg "$file" --out "${file:r}.jpg" >/dev/null || return
  done
}
function png2jpg {
  (( $# )) || { print -u2 'usage: png2jpg <image.png> [...]'; return 1; }
  local file
  for file in "$@"; do
    [[ -f $file && ${file:e:l} == png ]] || { print -u2 "not a PNG file: $file"; return 1; }
    command magick "$file" -background white -alpha remove -alpha off -quality 96 "${file:r}.jpg" || return
  done
}
function webp2png {
  (( $# )) || { print -u2 'usage: webp2png <image.webp> [...]'; return 1; }
  local file
  for file in "$@"; do
    [[ -f $file && ${file:e:l} == webp ]] || { print -u2 "not a WebP file: $file"; return 1; }
    command magick "$file" "${file:r}.png" || return
  done
}
function svg2png {
  (( $# )) || { print -u2 'usage: svg2png <image.svg> [...]'; return 1; }
  local file
  for file in "$@"; do
    [[ -f $file && ${file:e:l} == svg ]] || { print -u2 "not an SVG file: $file"; return 1; }
    command magick -background none "$file" "${file:r}.png" || return
  done
}
function transpng {
  (( $# )) || { print -u2 'usage: transpng <image> [...]'; return 1; }
  local file
  for file in "$@"; do
    [[ -f $file ]] || { print -u2 "not a file: $file"; return 1; }
    command magick "$file" -fuzz 10% -transparent white "${file:r}-trans.png" || return
  done
}
function img_trans {
  local size=${1:-500}
  [[ $size == <1-> ]] || { print -u2 'usage: img_trans [positive-size]'; return 1; }
  command magick -size "${size}x${size}" xc:transparent "PNG32:trans-${size}.png"
}
function img_pure_jpg {
  local size=${1:-500} color=${2:-white}
  [[ $size == <1-> ]] || { print -u2 'usage: img_pure_jpg [positive-size] [color]'; return 1; }
  command magick -size "${size}x${size}" "xc:${color}" -quality 100 "pure-${size}.jpg"
}
function img_pure_png {
  local size=${1:-500} color=${2:-white}
  [[ $size == <1-> ]] || { print -u2 'usage: img_pure_png [positive-size] [color]'; return 1; }
  command magick -size "${size}x${size}" "xc:${color}" "PNG32:pure-${size}.png"
}

function new_bash {
  local target=${1:-test.sh}
  [[ ! -e $target ]] || { print -u2 "refusing to overwrite: $target"; return 1; }
  cat >"$target" <<'ONE_BITE_BASH_TEMPLATE'
#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
cd "$SCRIPT_DIR"
ONE_BITE_BASH_TEMPLATE
  chmod u+x "$target"
}
