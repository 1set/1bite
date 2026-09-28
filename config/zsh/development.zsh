# Managed by 1bite: development. Personal overrides belong after the source in .zshrc.
alias ll='ls -lah'
alias g='git'
alias cl='claude'
alias clc='claude --continue'
# Explicit opt-in shortcuts: skip Claude permission checks / Codex approvals and sandbox.
alias cld='claude --dangerously-skip-permissions'
alias cldc='claude --dangerously-skip-permissions --continue'
alias cx='codex'
alias cxc='codex resume --last'
alias cxd='codex --dangerously-bypass-approvals-and-sandbox'
alias cxdc='codex resume --last --dangerously-bypass-approvals-and-sandbox'
alias dc='docker compose'

# Portable local shortcuts; these override colliding Oh My Zsh aliases.

# Make
alias m=make
alias mb='make build'
alias mi='make install'
alias mr='make run'
alias mt='make test'
alias mp='make preview'

# Git
alias ga='git add'
alias gaa='git add --all'
alias gcmsg='git commit --message'
alias gs='git status -s'
alias gst='git status'
alias gss='git status --short'
alias gd='git diff --no-index'
alias gdiff='git diff'
alias gds='git diff --staged'
alias gdca='git diff --cached'
alias gb='git branch'
alias gba='git branch --all'
alias gco='git checkout'
alias gcb='git checkout -b'
alias gsw='git switch'
alias gswc='git switch --create'
alias gl='git pull'
alias gp='git push'
alias glo='git log --oneline --decorate'
alias glog='git log --oneline --decorate --graph'
alias glg='git log --stat'
alias gstl='git stash list'
alias gstp='git stash pop'
alias grs='git restore'
alias grst='git restore --staged'
alias git_undo_last='git reset --soft HEAD~1'
alias gmtag='TZ=UTC git --no-pager show --quiet --abbrev=12 --date="format-local:%Y%m%d%H%M%S" --format="v0.0.0-%cd-%h"'
alias lg='lazygit'

# Go
alias gdoc='go doc -all .'
alias glist='go list -m -u all'
alias glistj='go list -m -json all'
alias grun='go run -v .'
alias gbuild='go build -ldflags "-s -w" -trimpath -v .'
alias gbuildmac='GOOS=darwin GOARCH=arm64 go build -ldflags "-s -w" -trimpath -v .'
alias gbuildmacintel='GOOS=darwin GOARCH=amd64 go build -ldflags "-s -w" -trimpath -v .'
alias gbuildlinux='GOOS=linux GOARCH=amd64 go build -ldflags "-s -w" -trimpath -v .'
alias gbuildwindows='GOOS=windows GOARCH=amd64 go build -ldflags "-s -w" -trimpath -v .'
function gcv {
  go test -v -race -cover -covermode=atomic -coverprofile=coverage.out -count 1 ./... "$@" || return
  go tool cover -html=coverage.out -o coverage.html
}
alias gtest='go test -v -race -cover -covermode=atomic -count 1 ./...'
alias gbench='go test -parallel=4 -run=none -benchtime=2s -benchmem -bench=.'
alias gm='go mod'
alias gmi='go mod init'
alias gmt='go mod tidy'
alias gmg='go mod graph'
alias gmc='go clean --modcache'

# Docker; d stays the directory stack function defined below.
alias dk=docker
alias dkc='docker container'
alias dkcm='docker compose'
alias dexec='docker exec -it'
alias di='docker images'
alias dimg='docker images'
alias dkimg='docker image ls'
alias dklg='docker logs -f'
alias dkls='docker ps -a'
alias dkps='docker ps -a'
alias dkrm='docker rm -f'
alias dps='docker ps'
alias dpsa='docker ps -a'
alias drmi='docker rmi'
alias dks='docker service'
alias dksm='docker swarm'
alias dkst='docker stack'
alias dkstat='docker system df'

# Disk
alias df='df -h'

# Multi-command shortcuts stop immediately if an earlier command fails.
unalias gpre gps1 mkcd mcd d cdf o dl mktgz mkzip tfind ff jv jp jsonview pcat \
  sha1 sha224 sha256 sha384 sha512 sha512224 sha512256 gci gcia git_corb \
  git_ignore git_readme tn tad to tkss tmuxconf tds cn gcv dkclear fingerprint \
  ffmpeg2wav ffmpeg2pcm video2wav pcm2wav heic2jpg png2jpg webp2png svg2png \
  transpng img_trans img_pure_jpg img_pure_png new_bash 2>/dev/null || true
