## Change

Describe the concrete trigger and resulting behavior.

## Validation

- [ ] I added regression coverage for the changed behavior and its preservation boundaries.
- [ ] I updated user and developer documentation where behavior or ownership changed.
- [ ] I bumped `VERSION` for a distributable product change.
- [ ] I updated `config/repository-files.txt` for every added or removed published path.
- [ ] I reviewed and regenerated the complete config golden fixture after any `config/` change.
- [ ] `./scripts/quality.sh` passes from an independent Git checkout.
- [ ] I identified whether disposable-Mac installation acceptance is required; I did not treat the repository quality gate as that evidence.
- [ ] I reviewed the diff and archive for credentials, identity, private paths, logs, and local artifacts.
