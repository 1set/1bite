PYTHON ?= python3
SHELL_FILES := 1bite scripts/verify.sh scripts/docker-smoke.sh scripts/session.sh scripts/welcome.sh scripts/editor.sh scripts/quality.sh apps/qbittorrent/qbt.sh

.PHONY: build test format-check quality check
build:
	@for file in $(SHELL_FILES); do bash -n "$$file"; done
	zsh -n config/shell.zsh
	zsh -n config/env.zsh
	@for file in config/zsh/*.zsh; do zsh -n "$$file"; done
	$(PYTHON) -m compileall -q scripts tests apps
	awk -f scripts/plain-log.awk /dev/null
	actionlint .github/workflows/quality.yml
	shellcheck -x $(SHELL_FILES)
	$(PYTHON) scripts/check-change.py
	$(PYTHON) scripts/check-repository.py --archive dist/1bite.tar.gz

test:
	$(PYTHON) -m unittest discover -s tests -v

format-check:
	shfmt -d -i 2 -ci $(SHELL_FILES)
	$(PYTHON) scripts/check-format.py

quality check:
	./scripts/quality.sh
