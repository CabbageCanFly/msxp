# Working on this project

This is an independent MapleStory Classic EXP tracker proof of concept.
Keep modules small and explicit. Python, Pillow, Tesseract and SQLite are sufficient
until measurements establish a need for more infrastructure.

- Read README.md, the docs index (docs/README.md) and the relevant docs before changing
  acquisition or tracking assumptions; docs/legacy-readme.md keeps the detailed developer notes.
- `msxp` (src/exp_tracker/msxp.py) is the user-facing entry point: keep its commands, the README
  command table and `msxp help` in step when a tool's options or defaults change.
- Run `python -m pytest` after code changes. Report sample skips separately from passes.
- Reuse normal pytest temporary storage; do not accumulate a new permanent `--basetemp` per run.
  Remove disposable browser profiles after review. Preserve unique fixtures separately from generated output;
  see `docs/private-test-data.md` for verified recovery from the private test-data repository.
- Never hardcode expected sample readings in production code or infer character identity
  from level/EXP alone. Reject uncertain readings and preserve the last accepted state.
- Do not add screenshots, crops, credentials, databases or logs to Git. Samples are
  private fixtures; only generated synthetic fixtures may be committed.
- Use placeholders (`Streamer_A`, `CharA`) for real streamer logins and character names in
  Git-tracked files and commit messages; real names stay in private, ignored files.
- Keep OBS credentials on the streamer's machine and separate capture authorization
  from public, read-only overlay URLs. No disabling browser security to make capture work.
- No provisioning, purchases, publishing or pushing without explicit authorization.
- Use Conventional Commits for logical local milestones. Do not add frameworks or
  services to this feasibility milestone. Document measured and untested behavior separately.

