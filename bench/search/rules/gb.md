# Labelling rules for the GB search bench

Input: `batches/bK.txt`. Each block is one query: `## <i> | <q> | alt: ... | head: ... | plain: ... | cat: ...`,
then the candidate pool, one line per product: `cK  <source>  <record ids>  <kcal>[<kcal source>]  <name>`.
Candidates are sorted by source (CoFID first) then name, NOT by search rank: rank is irrelevant here.

Output: `labels/bK.jsonl`, one JSON object per query, in input order, every query present:

    {"i": 12, "q": "bap", "accept": ["c3", "c7"], "best": "c3", "why": "bread: soft white roll, Midlands/North word"}
    {"i": 40, "q": "X", "accept": [], "best": null, "gap": true, "tried": ["alt 1", "alt 2"], "why": "veg: searched X, alt, alt1, alt2; no Z in the pool"}

- `accept`: EVERY candidate that is the same food in the same state. Candidate ids (`"c3"`), or record ids
  (`"cofid:13-123"`) for items found only by a retry phrasing (see gaps).
- `best`: one element of `accept`: the kcal reference, so it is the most canonical form of what the query means:
  the plain raw/as-bought form for an unprepared query, the matching preparation for a prepared one, the as-eaten
  form for things only ever eaten prepared (chips, mash, scrambled eggs, a dish).
  **Prefer a CoFID candidate.** Else the best other core record (fdc, ciqual, bls, frida, matvaretabellen, …).
  **The best's kcal must be its own**: pick only a candidate whose `[kcal source]` equals its own source and that
  holds exactly one record of that source. A merged product whose kcal comes from another table is fine to
  ACCEPT but not to be best (its number is not the cited table's number).
- `why`: `"<cat>: <what makes it representative>"`, short. cat is the block's cat. For a generic word say which
  form you picked as typical.

## GB conventions for ambiguous words (decided by how people in the UK eat it)

- **Milk** unqualified = semi-skimmed (the most-drunk UK milk). "whole/skimmed/1%" = that fat level only.
- **Yoghurt** unqualified = plain/natural whole-milk yoghurt (generic: accept natural/plain variants, not
  fruit or flavoured). "greek yoghurt" = Greek/Greek-style (strained). "fat free" = 0.1–0.5 % fat plain only.
- **Cheese** unqualified = cheddar (the UK default). "grated cheese" = cheddar too.
- **Cream**: single/double/whipping/clotted are distinct foods; "whipped cream" accepts whipping cream (whipped)
  and aerosol cream.
- **Bacon** unqualified = back bacon rashers, raw or plainly cooked (grilled/fried/dry-fried). Streaky ≠ back.
  "bacon" accepts any plain bacon rasher record; it does not accept gammon or ham.
- **Ham** = cooked sliced ham (not raw cured/Parma unless nothing else; never gammon steak).
- **Sausages** unqualified = British pork sausages, raw or grilled/fried. Not frankfurters, chorizo, salami.
- **Mince** unqualified = beef mince. "lean mince" = lean/extra-lean beef mince only.
- **Steak** unqualified = beef steak (any common cut, raw or grilled/fried).
- **Chips** = British chip-shop / thick-cut fried potato chips (CoFID "chips, fried" or "chips, homemade/fine cut/
  retail"), not crisps; "oven chips" = oven-baked chips only. "crisps" = potato crisps (US chips).
- **Jacket potato** = baked potato flesh and skin. **Roast potatoes** = roasted in fat.
- **Sweetcorn** = canned/frozen kernels as eaten (canned, boiled); "corn on the cob" = whole cob boiled/raw.
- **Peas** unqualified = garden peas, raw/frozen/boiled; mushy peas and processed peas are different foods.
- **Baked/tinned tomatoes**: "tinned/chopped tomatoes" = canned tomatoes only; plain "tomato" = raw.
- **Beans**: "baked beans" are their own food; "green/runner/broad beans" are the fresh veg.
- **Tuna** unqualified = canned tuna (what the UK mostly eats, brine/water/oil) AND fresh tuna raw or plainly
  cooked; best = canned in brine. "tinned tuna" = canned only; "tuna in brine" = canned in brine or water only.
- **Sardines/anchovies** unqualified = canned (oil or brine). "in tomato sauce" = that only.
- **Prawns** = cooked prawns (as bought in the UK); raw prawns also accepted, breaded/battered not.
- **Smoked fish** (salmon, haddock, mackerel, kippers) = smoked only, not fresh.
- **Dates** = dried dates (the UK buys them dried). **Figs** = fresh unless "dried".
- **Raisins/sultanas/currants** are distinct; do not cross-accept.
- **Apricots** plain = fresh; "dried apricots" = dried only. Prunes = dried plums (ready-to-eat or dried; not stewed
  unless nothing else — and then not).
- **Nuts**: plain "almonds/cashews/walnuts/…" accept raw and plain roasted (unsalted or salted); not coated,
  honey-roasted, chocolate. "salted peanuts" = roasted salted only. "peanuts" = raw or roasted, plain or salted.
- **Coconut** "desiccated" = desiccated/dried unsweetened only.
- **Condensed milk** = sweetened condensed only; **evaporated** = unsweetened evaporated. Never cross.
- **Tea** = black tea infusion; "tea with milk" = tea with milk (a combined record) — black tea alone is not
  acceptable. **Coffee** plain = black infusion; "coffee with milk"/latte/cappuccino/flat white = the milky drink.
  "americano" = black coffee. "instant coffee" = instant powder OR made-up instant coffee.
- **Squash** = fruit squash/cordial diluted (or concentrate if only that exists — accept both, best = diluted).
- **Lemonade** = UK clear fizzy lemonade (carbonated), not US still lemonade.
- **Beer** "lager", "stout", "bitter" are distinct types; "cider" any cider (dry/sweet), not perry.
- **Wine** red/white/rosé by colour; "prosecco" = sparkling white wine.
- **Gravy** = made-up gravy (granules + water or meat gravy), not dry granules.
- **Custard** = made-up custard (from powder with milk, or ready-to-serve), not custard powder.
- **Jelly** = the set dessert (made with water), not jam/jelly preserve.
- **Pancakes** = UK thin pancakes/crêpes (Shrove Tuesday), plain; scotch pancakes/drop scones are different.
- **Biscuits** = UK biscuits (cookies), never US scone-like biscuits.
- **Pudding** names: "christmas pudding", "sticky toffee pudding", "rice pudding" are the desserts; "black pudding"
  is blood sausage; "yorkshire pudding" is the batter pudding.
- **Curry** dishes: "chicken curry" accepts any chicken curry record; a named curry (tikka masala, korma,
  jalfrezi, rogan josh, biryani) accepts only records naming that curry. Rice is not implied: a "curry with rice"
  record is not acceptable for a curry query.
- **Shepherd's pie** = lamb; **cottage pie** = beef. Do not cross-accept.
- **Pasty** unqualified/"cornish pasty" = beef & veg pasty.
- **Sandwich** queries: accept a record that is that sandwich (any bread). Not the filling alone.
- **Pizza** named type: that topping only; "margherita" = cheese and tomato pizza.

## What counts as acceptable

1. Same food. A variety is still the food ("pear" accepts any pear variety, raw). A different food is not,
   however close in kcal ("wholemeal roll" accepts wholemeal/wholewheat rolls, not white rolls; "trout" not salmon).
2. Same state.
   - Query names a preparation ("boiled", "fried", "grilled", "roast", "tinned", "smoked", "battered",
     "breaded", "mashed"): accept only that preparation (fried ≈ pan-fried/sautéed; boiled ≈ cooked in water;
     roast ≈ roasted/baked). Not raw.
   - Plain query for a food normally eaten raw (fruit, salad leaves, cucumber, tomato, radish, nuts): raw
     only. Stewed, canned, dried, juice are different foods.
   - Plain query for a food normally eaten cooked (meat, fish, potato, rice, pasta, grains, legumes, most
     cooking vegetables): the raw/dry form AND plainly cooked forms (boiled, steamed, roasted, grilled,
     fried without coating) are all acceptable. Breaded, battered, in sauce, or as part of a dish are not.
   - Dried legumes vs canned/cooked legumes: both acceptable for a plain legume query.
3. Specific vs generic.
   - Generic query ("cheese", "yoghurt", "cake", "ice cream", "crisps"): accept the generic entry and the
     common plain variants per the GB conventions above — not flavoured, sweetened or filled ones unless the
     query is itself generic in that way ("fruit yoghurt" accepts any fruit yoghurt).
   - Specific query ("mature cheddar", "dark chocolate", "lager"): only that variant; a fat level or type that
     contradicts the query is not acceptable ("mature cheddar" accepts cheddar records that are not reduced-fat).
4. Any core source is fine: cofid, fdc, ciqual, bls, frida, matvaretabellen, fineli, mext, tfda, recipe. List
   them all when they match; do not stop at the CoFID one. A `recipe` record is fine for a dish it names.
5. Mixed dishes: accept records that are that dish (any reasonable recipe of it). "fish and chips" accepts a
   combined record only, or failing that is a gap — do not accept battered cod alone. Same for "beans on toast",
   "bangers and mash", "spaghetti bolognese" (not plain spaghetti, not the sauce alone).
6. Drinks: diet/zero drinks accept only sugar-free variants. Alcohol: the type named.
7. Do not accept something just to avoid a gap. A wrong label is worse than a gap.

## Gaps

When nothing in the pool is acceptable, try 2 more phrasings (a synonym, a CoFID-style "food, qualifier" name,
a US name), one call:

    cd /home/kirill/.herdr/worktrees/fooddb/bench-6k && set -a; . ~/.config/fooddb/bench.env; set +a; \
      TMPDIR=/home/kirill/.cache/tmp-gate uv run python /home/kirill/.cache/bench-gb/gather.py try "alt 1" "alt 2"

It prints `records<TAB>kcal[kcal source]<TAB>name<TAB>via`. If something acceptable turns up, accept it by record
id (all of the product's records, comma-split into separate strings) and set best to one of them (its own kcal
rule still applies); also put the phrasings in `tried`. If still nothing: `"accept": [], "best": null,
"gap": true, "tried": [...]`, and `why` says what was searched. Never print or echo the API key; only that
command, no other HTTP calls; run retries one at a time (the script paces itself).
