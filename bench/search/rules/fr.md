# Labelling rules for the FR search bench

Input: `batches/bK.txt`. Each block is one query: `## <i> | <q> | en: ... | head: ... | cat: ...`, then the
candidate pool, one line per product: `cK  <source>  <record ids>  <kcal/100 g>  <name>`. Names are English
(CIQUAL names are English). Candidates are sorted by source then name, NOT by search rank: rank is irrelevant here.

Output: `labels/bK.jsonl`, one JSON object per query, in input order, every query present:

    {"i": 12, "q": "Semmel", "accept": ["c3", "c7"], "best": "c3", "why": "bread: Bavarian/Austrian word for the breakfast roll"}
    {"i": 40, "q": "X", "accept": [], "best": null, "gap": true, "tried": ["alt 1", "alt 2"], "why": "veg: searched X, en Y, alt1, alt2; no Z in the pool"}

- `accept`: EVERY candidate that is the same food in the same state. Candidate ids (`"c3"`), or record ids
  (`"bls:G123100"`) for items found only by a retry phrasing (see gaps).
- `best`: one element of `accept`: the best CIQUAL record among them (else the best core record). This is the
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
   them all when they match; do not stop at the CIQUAL one. A `recipe` record is fine for a dish it names.
5. Mixed dishes: accept records that are that dish (any reasonable recipe of it). "Currywurst mit Pommes"
   accepts a combined record only, or failing that is a gap if only the parts exist — do not accept the
   sausage alone for the combo. Same for "Spaghetti Bolognese" (not plain spaghetti, not the sauce alone).
6. Drinks: "Tee"/"Kaffee"-style queries mean the plain infusion (no milk, no sugar). Diet/zero drinks accept
   only sugar-free variants. Alcohol: the type named ("Rotwein" any red wine; "Schnaps" any ~40 % spirit).
7. Do not accept something just to avoid a gap. A wrong label is worse than a gap.

## Gaps

When nothing in the pool is acceptable, try 2 more phrasings (a synonym, a simpler English name), one call:

    cd /home/kirill/.herdr/worktrees/fooddb/bench-6k && set -a; . ~/.config/fooddb/bench.env; set +a; \
      TMPDIR=/home/kirill/.cache/tmp-gate uv run python /home/kirill/.cache/bench-fr/gather.py try "alt 1" "alt 2"

It prints `records<TAB>kcal<TAB>name<TAB>via`. If something acceptable turns up, accept it by record id (all of
the product's records, comma-split into separate strings) and set best to one of them; also put the phrasings in
`tried`. If still nothing: `"accept": [], "best": null, "gap": true, "tried": [...]`, and `why` says what was
searched. Never print or echo the API key; only that command, no other HTTP calls; run retries one at a time.

## France: conventions for ambiguous words (decided by how people in France eat it)

Examples in the generic rules above are German; the logic is the same. These are the French decisions; label to them.

- **kcal reference** is a CIQUAL record whenever one is acceptable (the national table). Never a CIQUAL record
  whose kcal is `None`: pick the next best acceptable CIQUAL record.
- **"pain"** = baguette-type white bread. "pain de mie" = sliced sandwich loaf. "pain complet" = wholemeal,
  "pain aux céréales" = multigrain, "pain de campagne" = country bread (its own CIQUAL entry), not the same as baguette.
- **viennoiseries** (croissant, pain au chocolat/chocolatine, pain aux raisins, brioche, chausson aux pommes)
  are each their own food; "chocolatine" = pain au chocolat.
- **"jambon"** alone = jambon blanc / jambon cuit (cooked ham), the French default. "jambon cru" / "jambon de
  Bayonne" / "jambon sec" = dry-cured raw ham. Not interchangeable.
- **"lardons"** = smoked or plain lardons, raw as bought (cooked lardons also fine); not bacon rashers of another cut
  unless the record is the same cured pork belly.
- **"steak haché"** = minced beef patty; fat level in the query is binding (5 %, 15 %, 20 %); plain = any fat level,
  raw or cooked. **"steak"** alone = beef steak (bavette, rumsteck, entrecôte...), not a minced patty.
- **"escalope"** alone = turkey escalope (dinde) — the everyday one; "escalope de veau" = veal.
  **"escalope panée"** = breaded.
- **"blanc de poulet"** = chicken breast, as is "filet de poulet". **"poulet rôti"** = roast chicken with skin.
- **"saucisse"** alone = fresh pork sausage (Toulouse type), cooked or raw. "saucisse de Strasbourg"/"knacki" =
  frankfurter type. "saucisson" = dry-cured sausage (saucisson sec) — a different food from "saucisse".
- **canned fish**: "thon" alone = canned tuna (natural / in brine) — that is how France logs tuna; "thon à l'huile"
  = in oil; "thon frais"/"steak de thon" = fresh. "sardines" alone = canned sardines in oil. "maquereau" alone =
  fresh/cooked mackerel; "maquereau au vin blanc" etc. = canned.
- **"saumon"** alone = fresh salmon raw/cooked; "saumon fumé" = smoked. "cabillaud" = fresh cod (not salt cod);
  "colin" = hake/pollock as named by CIQUAL (colin d'Alaska = Alaska pollock; colin = hake).
- **"crème fraîche"** = thick 30 % cream; "crème fraîche légère" / "crème légère" = reduced-fat 15 %. "crème liquide"
  = liquid cream (fat level as named). **"lait demi-écrémé"** = semi-skimmed 1.5 %, "lait écrémé" = skimmed.
  "lait concentré sucré" = sweetened condensed milk; "lait concentré non sucré" = evaporated; not interchangeable.
- **"fromage blanc"** = fromage blanc (fat level as named; plain = any plain). "petit suisse" its own entry.
  "faisselle" = fromage blanc in faisselle. "yaourt nature" = plain; "yaourt aux fruits" = any fruit yogurt.
- **Cheeses**: each named cheese accepts only that cheese (Comté ≠ Emmental ≠ Gruyère; "gruyère" in France often
  means grated hard cheese, but label the record named Gruyère). "fromage râpé" = grated cheese (emmental type).
- **"maïs"** = sweetcorn canned/drained (how France eats it, in salads); corn on the cob raw/boiled also fine.
  Not popcorn, not polenta.
- **"dattes"** = dried dates (the only form sold in France). **"pruneaux"** = prunes (dried). **"raisins secs"**
  = raisins; **"raisin"** = fresh grapes.
- **nuts**: "amandes", "noix", "noisettes", "noix de cajou" plain = raw/plain; dry-roasted unsalted also fine;
  "cacahuètes" = roasted salted peanuts (the aperitif form) and plain roasted ones; "pistaches" = roasted salted.
- **"haricots verts"** = green beans, raw/boiled/canned/frozen all fine. "flageolets" = flageolet beans, cooked or canned.
  "haricots blancs" = white beans dried/cooked/canned (not in tomato sauce unless said).
- **"petits pois"** = garden peas raw/cooked/canned/frozen. "petits pois carottes" = the canned mix.
- **"frites"** = French fries as eaten (fried / oven-baked); **"purée"** = mashed potato (homemade or from flakes,
  prepared); "pommes de terre sautées" = pan-fried potatoes.
- **"compote"** = apple compote/applesauce (sweetened or not, the fruit as named); "compote sans sucre ajouté" = no
  added sugar only.
- **"jus d'orange"** = orange juice (pure juice or from concentrate; not a nectar or drink). "pur jus" = not from
  concentrate preferred but both fine.
- **"thé"/"café"/"tisane"/"infusion"** = plain infusion, no milk, no sugar. "café au lait"/"crème" = coffee with milk.
- **"vin blanc"/"vin rosé"/"champagne"/"cidre"/"pastis"** = that drink; "apéritif anisé" = pastis.
- **dishes**: accept records that are that dish (prepacked or homemade). "steak frites", "moules frites" etc.
  need a combined record or are gaps. "blanquette" alone = blanquette de veau. "bourguignon" = boeuf bourguignon.
  "hachis parmentier" = hachis parmentier (not shepherd's pie of lamb unless that's the only same dish, which it
  isn't). "quiche" alone = quiche lorraine. "galette" alone = buckwheat galette (savoury crêpe), "galette des rois"
  = the frangipane cake. "crêpe" = sweet/plain crêpe.
- **"salade"** alone = lettuce (salad leaves), raw. "salade verte" = lettuce. A named composed salad (niçoise,
  piémontaise, de riz) = that dish.
- **"chocolat"** alone = dark chocolate (chocolat noir), the French default bar; "chocolat au lait" = milk.
  "chocolat chaud" = hot chocolate drink.
- **"biscottes"** = rusks. "tartine" = bread slice (label as bread); "tartine beurrée" = bread with butter (combo
  or gap).
