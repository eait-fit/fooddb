# Labelling rules for the DK search bench

Input: `batches/bK.txt`. Each block is one query: `## <i> | <q> | en: ... | head: ... | plain: ... | cat: ...`, then
the candidate pool, one line per product: `cK  <source>  <record ids>  <kcal/100 g> kcal [<kcal source>]  <name>`.
Names are English (Frida names are English). Candidates are sorted by source then name, NOT by search rank: rank
is irrelevant here.

Output: `labels/bK.jsonl`, one JSON object per query, in input order, every query present:

    {"i": 12, "q": "rundstykke", "accept": ["c3", "c7"], "best": "c3", "why": "bread: the plain white breakfast roll"}
    {"i": 40, "q": "X", "accept": [], "best": null, "gap": true, "tried": ["alt 1", "alt 2"], "why": "veg: searched X, en Y, alt1, alt2; no Z in the pool"}

- `accept`: EVERY candidate that is the same food in the same state. Candidate ids (`"c3"`), or record ids
  (`"frida:123"`) for items found only by a retry phrasing (see gaps).
- `best`: one element of `accept`: the kcal reference. It is the most canonical form of what the query means: the
  plain raw/as-bought form for an unprepared query, the matching preparation for a prepared one, the as-eaten
  form for things only ever eaten prepared (frikadeller, brunede kartofler, spejlæg).
  **Choose a Frida candidate whose kcal source in brackets is `[frida]`** whenever one is acceptable. Otherwise
  the best acceptable candidate whose kcal source is its own source (a `frida`-named line showing `[bls]` carries
  another table's merged number: never cite it as best, but still list it in accept). If no acceptable candidate
  has a kcal source matching its own source, pick the one whose bracketed source appears among its record ids.
- `why`: `"<cat>: <what makes it representative>"`, short. cat is the block's cat. For a generic word say which
  typical form you picked ("generic: ...").

## What counts as acceptable

1. Same food. A variety is still the food ("æbler" accepts any apple variety, raw). A different food is not,
   however close in kcal ("fuldkornsrugbrød" accepts wholegrain rye breads, not wheat bread; "laks" not trout).
2. Same state.
   - Query names a preparation ("stegt", "kogt", "dampet", "røget", "paneret", "i dåse"/"i tomat"/"i olie",
     "syltet", "ristet", "bagt"): accept only that preparation (stegt ≈ pan-fried/sautéed; kogt ≈ boiled; dampet ≈
     steamed/boiled without fat for veg). Not raw.
   - Plain query for a food normally eaten raw (fruit, salad leaves, cucumber, tomato, radish, nuts): raw only.
     Stewed, canned, dried, juice are different foods. Frozen berries/veg = raw.
   - Plain query for a food normally eaten cooked (meat, fish, potato, rice, pasta, grains, legumes, most cooking
     vegetables): the raw/dry form AND plainly cooked forms (boiled, steamed, roasted, grilled, fried without
     coating) are all acceptable. Breaded, battered, in sauce, or as part of a dish are not.
   - Dried legumes vs canned/cooked legumes: both acceptable for a plain legume query.
3. Specific vs generic.
   - Generic query ("mælk", "fløde", "brød", "kage", "is", "slik", "juice", "pølse"): accept the generic entry and the
     common plain variants — not flavoured, sweetened or filled ones unless the query is itself generic in that way
     ("frugtyoghurt" accepts any fruit yogurt).
   - Specific query ("skummetmælk", "mørk chokolade", "pilsner", "creme fraiche 18%"): only that variant; a fat level
     or type that contradicts the query is not acceptable.
4. Any core source is fine: frida, bls, fdc, ciqual, cofid, matvaretabellen, fineli, mext, tfda, recipe. List them
   all when they match; do not stop at the Frida one. A `recipe` record is fine for a dish it names.
5. Mixed dishes: accept records that are that dish (any reasonable recipe of it). "stegt flæsk med persillesovs"
   accepts a combined record only, or failing that is a gap if only the parts exist — do not accept the pork alone
   for the combo. Same for "spaghetti bolognese" (not plain spaghetti, not the sauce alone).
6. Drinks: "te"/"kaffe"-style queries mean the plain infusion (no milk, no sugar). Zero/light drinks accept only
   sugar-free variants. Alcohol: the type named ("rødvin" any red wine; "snaps"/"akvavit" any ~40 % spirit).
7. Do not accept something just to avoid a gap. A wrong label is worse than a gap.

## Danish conventions (how people in Denmark eat it)

- **rugbrød** family: dark Danish rye bread, any variety (with kernels, seeds, wholegrain); "lyst rugbrød" = light
  rye only. Not wheat bread, not crispbread.
- **franskbrød** = white wheat loaf; **rundstykke(r)** = plain white wheat breakfast roll; **grovbolle** = wholemeal/
  coarse roll; **boller** = plain wheat buns (white or coarse), not sweet buns with filling.
- **wienerbrød** = Danish pastry (any filling); **kanelsnegl** = cinnamon roll/swirl; **spandauer** = Danish pastry
  with custard/jam centre (accept Danish pastry generally if no exact one); **tebirkes** = poppy-seed Danish pastry.
- **mælk** (generic) = cow's milk, any plain fat level. **minimælk** = 0.4–0.5 % milk; **skummetmælk** = skimmed
  (0.1 %); **kærnemælk** = buttermilk; **kakaomælk** = chocolate milk.
- **kondenseret mælk** = UNSWEETENED evaporated milk (the Danish coffee/sauce product); sweetened condensed milk only
  for "sødet kondenseret mælk".
- **fløde** (generic) = cream, any plain fat level; **piskefløde** = whipping cream ~38 %; **madlavningsfløde** =
  cooking cream 9–18 %; **kaffefløde** = coffee/single cream ~9 %. **creme fraiche N%** = that fat level.
- **ymer**, **tykmælk** = Nordic cultured/soured milk products (accept cultured milk/soured milk of that type).
- **skiveost**, **ost 30+**, **lagret ost**, **havarti**, **esrom**: Danish firm/semi-firm cheese; 30+ = reduced fat
  (~30 % fat in dry matter). **rygeost** = Danish smoked fresh cheese. **smørbar** = spreadable butter-oil blend.
- **hakkekød** (generic) = minced beef or minced pork or the mix (all raw or plainly fried). **hakket oksekød** beef
  only, **hakket svinekød** pork only.
- **frikadeller/frikadelle** = Danish pan-fried pork (or pork+veal) meatballs, as eaten. Not in sauce.
- **flæskesteg / ribbensteg** = roast pork with crackling (belly or loin roast with rind), as eaten roasted.
  **stegt flæsk** = fried pork belly slices.
- **pølse** (generic) / **rød pølse** / **wienerpølse** / **grillpølse**: cooked pork sausage (frankfurter type).
  **medisterpølse** = Danish fresh pork sausage (raw or fried).
- **skinke** (plain) = cooked ham cold cut (kogt skinke). **røget skinke** = smoked ham (cured, cooked or raw-cured
  smoked). **spegepølse** = Danish dry-cured salami-type sausage; accept salami. **rullepølse** = rolled spiced pork
  cold cut. **hamburgerryg** = cured smoked pork loin (cold cut / boiled). **leverpostej** = pork liver pâté, plain
  (not the warm dish).
- **sild** family: **marinerede sild** / **kryddersild** = pickled (marinated) herring; **stegt sild** = fried
  herring (also fried-then-marinated "stegte sild i eddike" acceptable); **røget sild** = smoked herring.
- **tun** (plain) = canned tuna (in water or oil, either). "tun i vand"/"tun i olie": that medium only.
- **makrel i tomat** = canned mackerel in tomato sauce (classic pålæg). **makrel** plain = mackerel raw or plainly
  cooked; **røget makrel** smoked.
- **rejer** = shrimp/prawns raw or cooked, incl. peeled cooked in brine; not breaded, not in a salad.
- **torskerogn** = cod roe (boiled/canned or raw — all plain forms). **stenbiderrogn** = lumpfish roe.
- **fiskefrikadeller** = Danish fish cakes, fried. **paneret fiskefilet/rødspætte** = breaded (fried) fish fillet.
- **rødkål** (plain) = the Danish sweet-sour braised/pickled red cabbage side (jar). Raw red cabbage only for
  "rå rødkål".
- **syltede rødbeder** = pickled beetroot; **rødbeder** plain = beetroot raw or boiled. **asier** = Danish pickled
  cucumber/gherkin; accept pickled cucumber/gherkins.
- **majs** = sweetcorn kernels, raw, boiled or canned (all used); not popcorn, not cornmeal, not cornflakes.
- **dadler** = dried dates (what is sold in DK). **rosiner** = raisins. **svesker** = dried prunes.
- **æblemos** = stewed apple purée/compote (sweetened or not).
- **nuts** plain (mandler, hasselnødder, valnødder, cashewnødder, pistacienødder) = raw or dry-roasted, unsalted or
  salted both acceptable; **peanuts** plain = peanuts raw or roasted (salted or not); **saltede peanuts** = roasted
  salted only. **kokosmel** = desiccated coconut, unsweetened.
- **kartofler/kartoffel** plain = raw or boiled potato. **nye kartofler** = new potatoes, raw or boiled.
  **brunede kartofler** = caramelised (sugar-browned) potatoes. **pommes frites** = fries, as eaten (fried or oven).
- **havregrød** = oatmeal porridge (water or milk, either). **risengrød** = rice pudding porridge made with milk.
  **grødris** = dry short-grain pudding rice (accept plain raw rice records only if no pudding-rice record).
- **risalamande** = rice pudding with whipped cream and almonds; accept rice pudding with cream records.
- **sodavand** = regular sugared soft drink; **cola** = regular cola; **cola zero** = sugar-free cola only.
  **saftevand** = squash diluted ready to drink (not concentrate). **hyldeblomstsaft** = elderflower cordial (the
  concentrate if that is all there is; say so). **danskvand** = carbonated water (plain or flavoured, unsweetened).
- **snaps/akvavit** = any ~40 % spirit (aquavit preferred). **gløgg** = mulled wine. **julebryg** = Christmas
  beer (stronger lager/dark beer; accept dark lager/strong beer records). **pilsner** = lager.
- **remoulade** = Danish remoulade (mayonnaise-based dressing with pickles). **brun sovs** = brown gravy.
  **persillesovs** = parsley white sauce. **ristede løg** = fried crispy onions.
- **lakrids** = sweet licorice; **saltlakrids** = salty licorice (salmiak) — accept licorice records if no salmiak.
- **vaniljekranse/brunkager/pebernødder** = Danish Christmas biscuits; accept butter biscuits / spice biscuits
  of the matching kind.
- **is** (generic) = dairy ice cream, vanilla-type; **softice** = soft-serve.
