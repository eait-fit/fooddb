# STATE — dv-fooddb-161 (issue #161, class 2: inflection/compounds)

Task: one PR per class; class 2 first. PR open → `agent-fleet tell agent:kir/eait/lead-fooddb REVIEW` → STOP.

## Done
- Prod bench `bench/results/2026-10-18-dev161-prod-ece37b849d4f.json` (hit@1 56.5%, hit@5 74.2%).
- Dev db `fooddb_dv_fooddb_161` fully prepped (clone + mt names + fresh BLS + restated frida/mvt/ciqual names + snapshot + accepted pending). Dev read key exists (in .env.worktree / used in /tmp/bench_ba.sh).
- Implemented + COMMITTED `10de51d`: `src/fooddb/stems.py`, `_by_stems` fallback in `search.by_name`, migration 0024 (`f_stemtext` + 2 GIN indexes — applied to dev AND test dbs). Fallback fires only on empty trigram result → cannot regress.
- Tests added in tests/test_db.py (test_search_finds_inflected_and_compound_forms, test_search_falls_back_to_stems_only_when_the_trigram_path_is_empty, test_stems_segment_splits_on_corpus_stems). All 3 pass when run with ONLY them selected.
- Classification comment posted on issue 161 (per-set empty/miss@5/hit@5-not-@1).
- decisions.md row added (2026-10-18, stem fallback) — UNCOMMITTED.

## In flight
- Parallel before-bench running: `/tmp/bench_par.sh before` → /tmp/benchparts/before-<cc>.json per set (11 parallel; ~90 min; ~300-500ms/query — server CPU bound, parallelism doesn't speed it). `src/fooddb/search.py` is currently the OLD (origin/main) version — correct for "before". `/tmp/search_new.py` holds the new file; restore with `cp /tmp/search_new.py src/fooddb/search.py` then `./dev restart --api` before the AFTER phase (`/tmp/bench_par.sh after` + `uv run python /tmp/merge_bench.py after bench/results/dev161-after.json`; merge before: `uv run python /tmp/merge_bench.py before bench/results/dev161-before.json`).
- test_auth.py::test_keys_are_stored_as_hashes_only failure is ENV: my worktree SECRET_KEY in `.env.worktree` overrides the test's `setdefault('test-only-secret')`. Verified: with `FOODDB__BACKEND__SECRET_KEY=test-only-secret` the test passes. Fix after benches: set the value in `.env.worktree` to `test-only-secret`, re-run `./dev test` (needs no re-mint since benches will be done).

## Next
1. Wait for /tmp/bench_par.sh before → merge → cp /tmp/search_new.py → restart api → /tmp/bench_par.sh after → merge after.
2. Set `.env.worktree` SECRET_KEY value to `test-only-secret`; `./dev test` must be green.
3. Compute per-set before/after hit@1/hit@5; verify no set loses hit@1 by >1 query.
4. Commit tests + decisions.md (+ bench results + STATE.md), push dv-fooddb-161, open PR vs main closing #161 with numbers (draft body in /tmp/pr_body.md).
5. `agent-fleet tell agent:kir/eait/lead-fooddb REVIEW eait-fit/fooddb#<pr> "…"` → STOP.

## Final status (DONE — stopped)
- PR open: https://github.com/eait-fit/fooddb/pull/165 (closes #161, class 2 only)
- Reported REVIEW to lead-fooddb: msg 01M587TPQNKACPZ4NXAHM2N06G
- Fleet NOTE received: DEPLOY FREEZE (coordinator) — no `make deploy`, no ieat-app pin PRs until lifted. Code/PRs/reviews continue. Noted; no deploy planned by me regardless.

## Fix round 1 (REVIEW #2 sent, msg 01M58827JVSB4C6M0ADVGYRP9Q)
- Merged origin/main (no rebase) — includes 0024_fetch_run_code (#163).
- Stem migration renumbered 0025 off 0024; food index renamed food_stem_idx; dev+test dbs re-migrated to 0025.
- GIN build measured: food 48.9K → 0.83 s / 1.9 MB; food_name 84.6K → 1.45 s / 2.0 MB (prod extrapolation noted in PR body).
- Bench results renamed to dated names (2026-10-18-dv161-{before,after}.json).
- ./dev test on merged tree: 387 passed. PR body updated via REST PATCH.
