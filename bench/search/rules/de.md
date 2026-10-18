# DE delta labelling: newly pooled candidates

The DE set is already labelled (`labels/bK.jsonl`, rules in `RULES.md`). Each query was then searched once
more with a plain table-style phrase ("plain:"), and that search pooled NEW candidates. Your job: decide which
NEW candidates are the same food in the same state as the query, by `RULES.md`, plus the DE conventions below.

Input `delta/dK.txt`, one block per query: what is accepted now, the current best (the kcal reference),
and the NEW candidates `cK source records kcal name`. Output `labels2/dK.jsonl`, one line per block, in order:

    {"i": 12, "q": "Erbsen", "add": ["c31", "c33"], "best": "c31", "why": "veg: ..."}

- `add`: every NEW candidate that is acceptable (may be empty). Only NEW candidate ids from the block.
- `best`: keep the current one by OMITTING the key, unless a new candidate is clearly the better kcal
  reference: a BLS record where the current best is not BLS, or the plain raw/as-bought BLS form where the
  current best is a prepared/odd form for an unprepared query. Then set it to that `cK`.
- A block marked `CURRENTLY GAP`: if any new candidate is acceptable, `add` it and set `best`; then also give
  `"why"` (the case is no longer a gap). Otherwise `add: []` and nothing else.
- `why` only when you change `best` or close a gap.

## DE conventions (decided in the pilot; label to them)
- Datteln: dried dates (as sold in DE); fresh dates also accepted.
- Mais: canned sweetcorn is the reference; raw/boiled/frozen sweetcorn also accepted; maize grain/flour not.
- Rotkohl: raw, plus the apple-stewed and canned Rotkohl as eaten.
- Erdnüsse, Cashewkerne, Pistazien: raw and roasted/salted. Walnüsse, Mandeln, Haselnüsse: raw (ground ok).
- Plain fish queries (Thunfisch, Sardinen, Lachs, Makrele, Hering): raw, plainly cooked, and canned-drained
  (not in sauce/oil-with-sauce). "aus der Dose" queries: canned only.
- Kondensmilch: unsweetened evaporated milk, not sweetened condensed.
- Wiener Schnitzel: breaded veal only. Schnitzel paniert: breaded pork (or veal) schnitzel.
- Pfannkuchen: pancakes, not the Berlin doughnut.
- Frozen unsweetened fruit/veg = same state as raw.
- Generic Käse/Kuchen/Kekse/Eis/Salatdressing/Marmelade: generic entry + plain everyday variants, as already.

Never print the API key. No HTTP calls are needed for this pass.
