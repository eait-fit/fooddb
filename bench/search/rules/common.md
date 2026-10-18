# Labelling rules for the DE search bench

Input: `batches/bK.txt`. Each block is one query: `## <i> | <q> | en: ... | head: ... | cat: ...`, then the
candidate pool, one line per product: `cK  <source>  <record ids>  <kcal/100 g>  <name>`. Names are English
(BLS names are English). Candidates are sorted by source then name, NOT by search rank: rank is irrelevant here.

Output: `labels/bK.jsonl`, one JSON object per query, in input order, every query present:

    {"i": 12, "q": "Semmel", "accept": ["c3", "c7"], "best": "c3", "why": "bread: Bavarian/Austrian word for the breakfast roll"}
    {"i": 40, "q": "X", "accept": [], "best": null, "gap": true, "tried": ["alt 1", "alt 2"], "why": "veg: searched X, en Y, alt1, alt2; no Z in the pool"}

- `accept`: EVERY candidate that is the same food in the same state. Candidate ids (`"c3"`), or record ids
  (`"bls:G123100"`) for items found only by a retry phrasing (see gaps).
- `best`: one element of `accept`: the best BLS record among them (else the best core record). This is the
  kcal reference, so it is the most canonical form of what the query means: the plain raw/as-bought form
  for an unprepared query, the matching preparation for a prepared one, the as-eaten form for things only
  ever eaten prepared (Pommes, Bratkartoffeln, Rührei).
- `why`: `"<cat>: <what makes it representative>"`, short. cat is the block's cat.

## What counts as acceptable

1. Same food. A variety is still the food ("Apfel" accepts any apple variety, raw). A different food is not,
   however close in kcal ("Vollkornbrot" accepts wholemeal breads, not white bread; "Lachs" not trout).
2. Same state.
   - Query names a preparation ("gebraten", "gekocht", "gedünstet", "aus der Dose", "geräuchert",
     "paniert"): accept only that preparation (fried ≈ pan-fried/sautéed; boiled ≈ cooked in water;
     steamed ≈ stewed/cooked without fat for veg). Not raw.
   - Plain query for a food normally eaten raw (fruit, salad leaves, cucumber, tomato, radish, nuts): raw
     only. Stewed, canned, dried, juice are different foods.
   - Plain query for a food normally eaten cooked (meat, fish, potato, rice, pasta, grains, legumes, most
     cooking vegetables): the raw/dry form AND plainly cooked forms (boiled, steamed, roasted, grilled,
     fried without coating) are all acceptable. Breaded, battered, in sauce, or as part of a dish are not.
   - Dried legumes vs canned/cooked legumes: both acceptable for a plain legume query.
3. Specific vs generic.
   - Generic query ("Käse", "Joghurt", "Quark", "Wurst", "Kuchen", "Schnaps"): accept the generic entry and
     the common plain variants (fat levels, the everyday types) — not flavoured, sweetened or filled ones
     unless the query is itself generic in that way ("Fruchtjoghurt" accepts any fruit yogurt).
   - Specific query ("Magerquark", "Zartbitterschokolade", "Pils"): only that variant; a fat level or type that
     contradicts the query is not acceptable.
4. Any core source is fine: bls, fdc, ciqual, cofid, frida, matvaretabellen, fineli, mext, tfda, recipe. List
   them all when they match; do not stop at the BLS one. A `recipe` record is fine for a dish it names.
5. Mixed dishes: accept records that are that dish (any reasonable recipe of it). "Currywurst mit Pommes"
   accepts a combined record only, or failing that is a gap if only the parts exist — do not accept the
   sausage alone for the combo. Same for "Spaghetti Bolognese" (not plain spaghetti, not the sauce alone).
6. Drinks: "Tee"/"Kaffee"-style queries mean the plain infusion (no milk, no sugar). Diet/zero drinks accept
   only sugar-free variants. Alcohol: the type named ("Rotwein" any red wine; "Schnaps" any ~40 % spirit).
7. Do not accept something just to avoid a gap. A wrong label is worse than a gap.

## Gaps

When nothing in the pool is acceptable, try 2 more phrasings (a synonym, a simpler English name), one call:

    cd /home/kirill/.herdr/worktrees/fooddb/bench-6k && set -a; . ~/.config/fooddb/bench.env; set +a; \
      TMPDIR=/home/kirill/.cache/tmp-gate uv run python /home/kirill/.cache/bench-de/gather.py try "alt 1" "alt 2"

It prints `records<TAB>kcal<TAB>name<TAB>via`. If something acceptable turns up, accept it by record id (all of
the product's records, comma-split into separate strings) and set best to one of them; also put the phrasings in
`tried`. If still nothing: `"accept": [], "best": null, "gap": true, "tried": [...]`, and `why` says what was
searched. Never print or echo the API key; only that command, no other HTTP calls; run retries one at a time.
