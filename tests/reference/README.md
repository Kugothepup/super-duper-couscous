# Reference scripts

The `interview-synthesis` skill's scripts exactly as they stood at commit `dd8e629`, copied from `.claude/skills/interview-synthesis/scripts/`. They are the reference implementation for comparison tests (D7): a ported calculation in `crp/` must match these on the same inputs, unless `DECISIONS.md` changed the method.

Don't edit them. `SHA256SUMS` lists their hashes and `tests/test_reference.py` fails if any file changes.
