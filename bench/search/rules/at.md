# Labelling rules for the AT search bench

Input: `batches/bK.txt`. Each block is one query: `## <i> | <q> | en: ... | head: ... | cat: ...`, then the
candidate pool, one line per product: `cK  <source>  <record ids>  <kcal/100 g> [kcal source]  <name>`. Names are English
(BLS names are English). Candidates are sorted by source then name, NOT by search rank: rank is irrelevant here.

Output: `labels/bK.jsonl`, one JSON object per query, in input order, every query present:

    {"i": 12, "q": "Kaisersemmel", "accept": ["c3", "c7"], "best": "c3", "why": "bread: the star-cut Austrian breakfast roll"}
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
      TMPDIR=/home/kirill/.cache/tmp-gate uv run python /home/kirill/.cache/bench-at/gather.py try "alt 1" "alt 2"

It prints `records<TAB>kcal<TAB>name<TAB>via`. If something acceptable turns up, accept it by record id (all of
the product's records, comma-split into separate strings) and set best to one of them; also put the phrasings in
`tried`. If still nothing: `"accept": [], "best": null, "gap": true, "tried": [...]`, and `why` says what was
searched. Never print or echo the API key; only that command, no other HTTP calls; run retries one at a time.

## Austrian conventions (decided by how people in Austria eat and say it)

Austrian German differs from German German in vocabulary, and in a few places the SAME word means a
different food. These decisions bind every label. The national table is BLS (German, English names).

Words that mean something else than in Germany:
- **Hörnchen** = elbow macaroni (pasta), NOT a croissant. **Kipferl** = the croissant/crescent roll.
- **Kohl** = savoy cabbage (Wirsing). **Kraut / Weißkraut** = white cabbage. **Blaukraut** = red cabbage
  as served: cooked/braised red cabbage only. **Rotkraut** = red cabbage, raw or plainly cooked.
- **Schnitten** = cream-filled wafer slices (hazelnut cream wafers), not slices of bread or cake.
- **Indianer** = Indianerkrapfen: sponge with cream filling and chocolate glaze. Not a chocolate marshmallow (Schokokuss).
- **Most** = alcoholic cider/perry (fermented apple/pear). Not apple juice, not grape must.
- **Sturm** = partially fermented grape must. Not wine, not grape juice.
- **Mineral** = sparkling mineral water.
- **Frankfurter (Würstel)** = the Wiener/Frankfurter sausage (Brühwurst, Wiener Würstchen).
- **Rahm** alone: in Austria the cooking word for cream that collides with sour cream (Sauerrahm). Treat
  as a generic word: accept sweet cream (whipping/cooking cream) and sour cream; best = sweet cream 30 %.
- **Obers / Schlagobers** = sweet cream 30-36 % (Schlagsahne). **Kaffeeobers** = coffee cream 10-15 %,
  not evaporated milk. **Sprühobers** = aerosol whipped cream (accept whipped cream records).
- **Topfen** = quark. **Magertopfen** = low-fat quark only. **Topfen 20%** = quark 20 % f.i.d.m. only.
- **Eierspeise** = scrambled eggs (Rührei), as eaten. **Eiklar / Dotter** = raw egg white / raw yolk.
- **Paradeiser** = tomato, raw. **Karfiol** = cauliflower. **Fisolen** = green beans. **Kohlsprossen** =
  Brussels sprouts. **Melanzani** = aubergine. **Kukuruz** = sweet corn kernels; like the DE pilot's Mais,
  canned drained / cooked / raw sweetcorn all count, maize grain/flour/grits do not. **Porree** = leek.
  **Schwammerl** = mushrooms (cultivated mushrooms count). **Eierschwammerl** = chanterelles only.
  **Häuptelsalat** = butterhead/head lettuce. **Vogerlsalat** = lamb's lettuce. **Rote Rüben** = beetroot
  (raw or plainly cooked; pickled is a different food). **Gelbe Rüben** = carrots.
- **Marille** = apricot (raw); **Zwetschken** = plums (raw); **Weichseln** = sour cherries (raw); **Ribisel** =
  currants (redcurrant default; schwarze Ribisel = blackcurrant); **Schwarzbeeren** = bilberries/blueberries;
  **Ringlotten** = greengages; **Kletzen** = dried pears; **Holler** = elderberries (fruit);
  **Dörrzwetschken** = prunes; **Zwetschkenröster** = stewed plums (compote; accept plum compote).
  **Preiselbeeren**: in Austria eaten as the preserved compote with schnitzel: accept preserved/stewed
  lingonberries (compote, jam-style) AND raw; best = preserved when present.
- **Erdäpfel** = potatoes; plain = raw or boiled. **Salzerdäpfel** = boiled. **Braterdäpfel** = pan-fried
  potatoes (Bratkartoffeln). **Püree** = mashed potato. **Knödel** alone = Semmelknödel (bread dumpling).
  **Nockerl** = small dumplings: spaetzle count. **Fleckerl** = small square pasta: dry pasta (egg or durum)
  raw or plainly cooked counts.
- **Faschiertes** = mince; Austrian default is mixed beef/pork: accept mixed and generic mince, raw or
  plainly cooked; not beef-only or pork-only. **Rinderfaschiertes** = beef mince only.
- **Hendl** = chicken; **Truthahn** = turkey; **Schweins-** = pork. **Beiried** = sirloin/striploin (DE Roastbeef
  cut, rump steak). **Lungenbraten** = tenderloin/fillet. **Rostbraten** = entrecôte/rib steak. **Schopf** =
  pork neck/collar. **Siedfleisch** = beef for boiling, boiled beef (raw soup beef also counts).
- **Selchfleisch / Geselchtes** = smoked cured pork (Kassler). **Kaiserfleisch** = smoked cured pork belly.
- **Extrawurst / Pariser** = the Lyoner/Fleischwurst family of bologna-type Brühwurst. **Burenwurst** =
  coarse Brühwurst like Bockwurst. **Krakauer, Debreziner, Polnische, Käsekrainer, Kaminwurz** = only a record
  of that sausage (or the named type); a different sausage is a different food → gap.
- **Leberkas** = Leberkäse/Fleischkäse. **Blunzen** = blood sausage. **Grammeln** = pork cracklings.
- **Schnitzel** alone = breaded pork schnitzel, fried (Wiener Art); unbreaded escalope does not count.
  **Wiener Schnitzel vom Kalb** = breaded veal schnitzel. **Naturschnitzel** = unbreaded escalope, fried.
  **Backhendl** = breaded fried chicken.
- **Kren** = horseradish: raw root and plain grated/jarred horseradish both count. **Powidl** = plum butter
  (thick plum jam). **Liptauer** = quark/cheese spread with paprika only.
- **Staubzucker** = icing sugar. **Kristallzucker** = white sugar (generic sugar records count).
- **Melange** = coffee with steamed milk: accept milk coffee/café au lait/cappuccino records.
  **Verlängerter** = black coffee (infusion). **kleiner Brauner** = espresso with a little cream: only such a
  record, else gap. **Einspänner** = coffee with whipped cream, else gap.
- **Gespritzter** = white wine spritzer (wine + soda water); **Apfelsaft gespritzt** = apple juice spritzer
  (Apfelschorle). Plain wine or plain juice do not count.
- **Maroni** = chestnuts as eaten from the street stand: roasted; raw chestnuts also count (cooked-food rule).
- **Gugelhupf** = bundt cake: marble or plain pound/sponge-type cake count. **Biskotten** = ladyfingers.
  **Stanitzel** = an (empty) ice cream wafer cone. **Zuckerl** = hard candy/bonbons. **Krapfen** = jam-filled
  doughnut (Berliner). **Golatsche** = filled danish/puff pastry (quark default; fruit-filled also).
- **Wecken** = a white wheat loaf: white bread counts.
- Dishes named after Austrian cooking (Tafelspitz, Beuschel, Kasnocken, Krautfleckerl, Grenadiermarsch,
  Kaspressknödel, ...) need a record of that dish (any recipe of it, `recipe` records included); the main
  ingredient alone is a gap, as in the pilot rule 5.

Generic words in this set (cap ~3 %): Pizza, Rahm, Schnittkäse, Kraut, Obstkuchen, Fruchtgummi, Zuckerl.
Pick the most typical form and say so in `why`.

## kcal reference (fix 4)

The pool line shows `kcal [src]`: the product's merged kcal and the table it came from. `best` must be a
candidate whose kcal source is the cited record's own table (`bls` for a BLS record) — otherwise the number
belongs to another table's record. Prefer a BLS record whose line shows `[bls]`; if the only BLS candidate
shows another table's kcal, choose the best acceptable record whose kcal source equals its own source.

## Additions after batches b0-b2

- **Missing canonical record**: when the pool has acceptable candidates but plainly lacks the canonical BLS
  record (e.g. the plain BLS creamed spinach, BLS spray cream), you MAY run one `gather.py try` to find it and
  add it by record id; make it `best` if it is the better kcal reference. Put the phrasings in `tried`.
- **Sardellen** = anchovies as Austrians buy them: in oil or salted fillets count, as does raw anchovy.
- **Raw form whose kcal comes from another table**: keep it in `accept`; `best` falls to the plainly cooked
  BLS record (boiled) with `[bls]` kcal. This is fix 4 working as intended.
