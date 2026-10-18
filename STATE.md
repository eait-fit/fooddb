# STATE — dv-fooddb-161 (issue #161)

Task: one PR per class. Class 2 DONE+MERGED (PR #165, squash-merged 9ea4621). Deploy freeze still on (coordinator) — never deploy regardless. Now: **class 1** (dish/derivative containing the query word beats the plain food) as a separate PR off new main, same rules: all 11 sets measured, no set loses hit@1 by >1 query, REVIEW to lead-fooddb then STOP. Branch: **dv-fooddb-161-c1** (off 9ea4621).

## Class 2 recap (merged)
- stems.py fallback + migration 0025 (f_stemtext + food_stem_idx/food_name_name_stem_idx). Dev bench: 170 emptied queries answered, 0 hit@1 losses. `dev161` bench files: bench/results/2026-10-18-dv161-{before,after}.json (after = class-1's BEFORE baseline).

## Class 1 — in progress
- Analysis (from dev161-after.json + golden whys): hit@5-not-@1 pool ~1,094. Real class-1 shapes: dish word in name (`Cabbage pie`, `Egg nog`, `Cheese dip`, `Coconut milk`, `Mutton goulash`, `Veal stock`, `Quark cream`, `Liver risotto`, `Rice and split peas`, `Cookie, applesauce`), variant markers (`light`, `sweetened`, `frosted`, `toasted`, `reduced fat`, `with oats/ham/sauce`), category-head names (`Nuts, coconut meat`, `Fish, salmon, canned`) where the food sits in the tail.
- Issue hint: head noun matching the query is the signal; #158 rejected a blunt head-first because "category head and wrong-food head are positionally identical" (lost hit@1 on any/gb/us/dk).
- DESIGN implemented in src/fooddb/search.py (UNCOMMITTED):
  - `DISH` tuple (~150 words, multilingual, inert when word ∈ query): en dishes/derivatives (pie nog dip stock broth spread compote goulash stew salad casserole strudel torte tart wrap sandwich pizza cake cookie muffin pancake waffle pastry dumpling pudding parfait smoothie shake sundae brownie trifle mousse curry ragu wok gratin quiche omelette crepe galette flan salsa chutney relish preserves jam jelly sauce ketchup dressing marinade sushi taco burrito burger kebab risotto paella pasta noodle noodles spaghetti macaroni rice crust breaded battered coated stuffed filled butter cream milk paste extract essence chips pretzel) + variant markers (light lite "reduced fat" "low fat" low-fat "fat free" fat-free nonfat skimmed skim diet sweetened frosted honey imitation with and extra) + de/ru/es/fr/da-nb/sv/nl/it/pt/fi dish nouns.
  - `_penalty(name, uq, words)` now parameterized (same CASE-sum whole-word mechanism).
  - `_cover(name, words)`: 0 if every query word whole-word-matches name (s/es plural tolerance in query-word forms), else 1 — the #158-safe head signal ("canned salmon" keeps "Fish, salmon, canned" over "Salmon, smoked").
  - `_words(variant)`: unaccented lowercase word tokens via stems._unaccent + re.findall.
  - Tuple is now `(sim, cov, pen, dpen, rk, len)` — wired identically in both `best()` legs (trigram + stem fallback) and both ordering sites.
- NOT DONE YET: tests for class 1, decisions.md row, bench before/after, PR.
- Test ideas (verified winners): `egg` → 'Egg, raw' over 'Egg nog'; `cabbage` → 'Cabbage, green, raw' over 'Cabbage pie'; `canned salmon` → 'Fish, salmon, canned' over 'Salmon, smoked'; `coconut` → 'Nuts, coconut meat' over 'Coconut milk'; `sour cream` → 'Cream, sour, cultured' over 'Sour cream, light'.
- Baseline file for before/after: reuse `bench/results/2026-10-18-dv161-after.json` as "before" (it is the merged-main behavior); measure "after" with the in-process runner `/tmp/inproc_bench.py` (TestClient, ~7 min for all 11 sets; env: source .env.worktree, FOODDB__BENCH__KEY=fdb_XuLITJrvEcP8fA0d20refrr2lGDSDD6QFFAtqwOyLQ8, FOODDB__BACKEND__DATABASE_URL=…/fooddb_dv_fooddb_161; api_key rate_limit already bumped to 1M in dev db; .env.worktree SECRET_KEY=test-only-secret — do NOT change, ./dev test needs it).
- ⚠ Dev API process may still be running with old env; restart via ./dev restart --api if probing via HTTP (in-proc runner bypasses it anyway).

## Next
1. Write class-1 DB tests in tests/test_db.py (names()/rec()/ingest pattern as before).
2. `./dev test` → green.
3. Run `/tmp/inproc_bench.py` "c1" → bench/results/<dated>-c1.json; compare vs dev161-after baseline; verify no set loses hit@1 by >1 query; iterate DISH list if regression.
4. decisions.md row for class 1; commit; push dv-fooddb-161-c1; open PR (second PR for #161, does NOT close it — reference it) with before/after table + test count.
5. `agent-fleet tell agent:kir/eait/lead-fooddb REVIEW eait-fit/fooddb#<pr> "…"` → STOP.
- c1 bench 401s: bench api_key was hashed under old secret; rehashed under test-only-secret (update api_key ... where name='bench')
- c1 bench (in flight): any +0.015/+0.004, at +0.004/+0.012, de +0.012/+0.016, dk +0.016/-0.004 hit5, **es hit@1 0.270→0.264 = -3 queries, OVER THE 1-LOSS LIMIT — must diff es cases vs dev161-after and fix DISH/cover**

## Class 1 — iteration log
- v1 bench (2026-10-18-dv161-c1.json): overall 0.563→0.575 @1, 0.742→0.750 @5 — but **es net -3 hit@1 (over limit)**, at -1.
- Loss diff: many flips are identical-tuple ties between duplicate products (зефир, atún, tarta de queso, vinagre, compote, cheesecake, кунжут — same name text, same tuple → DISTINCT-ON picks arbitrarily; pre-existing noise).
- Real culprits: DISH words that are legit food-name components — removed: with, and, extra, sweetened, sauce, salsa, pizza, pasta, spaghetti, macaroni, noodle(s), diet. Also hyphen/space normalized in _penalty patterns ('low fat' now matches 'low-fat' and vice versa; also applies to PROCESSING's 'gluten-free').
- v2 bench running → bench/results/2026-10-18-dv161-c1v2.json, log /tmp/ib_c1v2.log. Watch es/at net hit@1 vs bench/results/2026-10-18-dv161-after.json baseline.
