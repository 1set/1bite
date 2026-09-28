#!/bin/bash
set -euo pipefail
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
docker info >/dev/null
work_dir=$(mktemp -d)
image_name="1bite-smoke:$(date +%s)-$$"
cleanup() {
  docker image rm "$image_name" >/dev/null 2>&1 || true
  rm -rf "$work_dir"
}
trap cleanup EXIT
cat >"$work_dir/Dockerfile" <<'EOF'
FROM alpine:3.22
CMD ["sh", "-c", "printf setup-docker-ok"]
EOF
docker build --platform linux/amd64 -t "$image_name" "$work_dir"
result=$(docker run --rm --platform linux/amd64 "$image_name")
[[ "$result" == setup-docker-ok ]]
echo 'Docker linux/amd64 build and container execution passed.'
