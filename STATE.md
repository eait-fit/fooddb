# STATE — dv-fooddb-161 (issue #161, class 2: inflection/compounds)

Task: one PR per class; class 2 first. PR open → `agent-fleet tell agent:kir/eait/lead-fooddb REVIEW` → STOP.

## Done so far
- Read CONTRIBUTING/design/decisions + issue 161 (via `gh api` — `gh issue view` GraphQL broken).
- Prod bench (read-only, bench key): `bench/results/2026-10-18-dev161-prod-ece37b849d4f.json` — overall hit@1 56.5 %, hit@5 74.2 % (matches issue's post-#158 figure).
- Dev data: `fooddb_dv_fooddb_161` = clone of `fooddb_names_mt_2d_review` + `names load-mt` + fresh `table bls` + forced restate of frida/matvaretabellen/ciqual names + `run snapshot --full` (219 recipes) + bulk-accepted pending obs (mimics prod review state). Dev read key `bench` created; `.env.worktree` got a local FOODDB__BACKEND__SECRET_KEY.
- Implemented fallback search (`search.by_name` → `_by_stems` when trigram result is empty — provably non-regressing on hit@1):
  - `src/fooddb/stems.py`: CONFIG lang→regconfig, `tsv(table)` = `f_stemtext(lang,name)` GIN'd tsvector, `tsquery(phrase)` = OR over all name configs of plainto_tsquery, corpus `vocab(lang)` (TTL cache, `reset()`), `segment()` greedy longest vocab-stem constituents, `variants()` emits (phrase,score_against) pairs — split parts score vs ORIGINAL query.
  - `alembic/versions/0024_name_stem_indexes.py`: f_stemtext IMMUTABLE wrapper + 2 GIN indexes (applied on dev db).
  - Verified live: laksefilet, svinekjøtt, lammelår, andebryst, kokte gulrøtter, kneippbrød, knoldselleri, hakkede tomater, maiskolbe, Staudensellerie, æggeblomme, spejlæg, speilegg, Vollkornnudeln all return candidates now (was empty).
  - Still empty (genuine gaps): Blaubeeren, solsikkekerner-ish tails, most dish names (borodinsky, etc.).
- Dev baseline bench `bench/results/dev161-before.json` was STILL RUNNING when I stopped probing (log /tmp/dev_before.log — check it finished).

## Next
1. Write tests in tests/test_db.py (cases verified empty under trgm: laksefilet/nb 'Laks, filet, rå', æggeblomme/da 'Æg, høne, blomme, rå', walnüsse/de 'Walnuss', kokte gulrøtter/nb 'Gulrot, kokt'; call `stems.reset()` — vocab caches). Pure `segment` unit tests optional in tests/test_stems.py.
2. `./dev test` must be green.
3. Run AFTER bench on dev API: `FOODDB__BENCH__KEY=<dev key> uv run python scripts/bench_search.py --base-url http://127.0.0.1:9700 --out bench/results/dev161-after.json` (~10 min).
4. Post miss classification comment on issue 161 (per-set counts: empty / nonhit@5 / hit@5-not-@1 from the prod result json).
5. decisions.md row (2026-10-18): stem fallback design.
6. Commit (one logical change — code+tests+decisions+indexes; bench results optional commit), push `dv-fooddb-161`, open PR vs main closing #161 with per-set before/after + `./dev test` numbers.
7. `agent-fleet tell agent:kir/eait/lead-fooddb REVIEW eait-fit/fooddb#<pr> "<status + numbers>"` → STOP.

## Key file refs
- src/fooddb/search.py (`_by_stems`), src/fooddb/stems.py, alembic/versions/0024_name_stem_indexes.py
- Prod results: bench/results/2026-10-18-dev161-prod-ece37b849d4f.json (has per-case ids for miss classification)
