# Labelling rules for the ES search bench

Input: `batches/bK.txt`. Each block is one query: `## <i> | <q> | en: ... | head: ... | plain: ... | cat: ...`,
then the candidate pool, one line per product: `cK  <source>  <record ids>  <kcal/100 g> [kcal source]  <name>`.
Names are English. Candidates are sorted by source then name, NOT by search rank: rank is irrelevant here.
fooddb indexes no Spanish names, so most pools come from the English and plain phrasings.

Output: `labels/bK.jsonl`, one JSON object per query, in input order, every query present:

    {"i": 12, "q": "barra de pan", "accept": ["c3", "c7"], "best": "c3", "why": "bread: the white baguette bought daily"}
    {"i": 40, "q": "X", "accept": [], "best": null, "gap": true, "tried": ["alt 1", "alt 2"], "why": "dish: searched X, en Y, alt1, alt2; no Z in the pool"}

- `accept`: EVERY candidate that is the same food in the same state. Candidate ids (`"c3"`), or record ids
  (`"fdc:170457"`) for items found only by a retry phrasing (see gaps).
- `best`: one element of `accept`: the kcal reference (see "kcal reference" below). It is the most canonical
  form of what the query means: the plain raw/as-bought form for an unprepared query, the matching
  preparation for a prepared one, the as-eaten form for things only ever eaten prepared (patatas fritas,
  huevos revueltos, tortilla de patatas).
- `why`: `"<cat>: <what makes it representative>"`, short. cat is the block's cat.

## What counts as acceptable

1. Same food. A variety is still the food ("manzana" accepts any apple variety, raw). A different food is not,
   however close in kcal ("pan integral" accepts wholemeal breads, not white bread; "merluza" not cod).
2. Same state.
   - Query names a preparation ("a la plancha", "frito", "cocido", "asado", "al horno", "en lata",
     "ahumado", "empanado", "a la romana"): accept only that preparation (plancha ≈ grilled/pan-fried
     without coating; cocido ≈ boiled; asado/al horno ≈ roasted/baked). Not raw.
   - Plain query for a food normally eaten raw (fruit, salad leaves, cucumber, tomato, radish, nuts): raw
     only. Stewed, canned, dried, juice are different foods.
   - Plain query for a food normally eaten cooked (meat, fish, potato, rice, pasta, grains, legumes, most
     cooking vegetables): the raw/dry form AND plainly cooked forms (boiled, steamed, roasted, grilled,
     fried without coating) are all acceptable. Breaded, battered, in sauce, or as part of a dish are not.
   - Dried legumes vs canned/cooked legumes: both acceptable for a plain legume query.
   - Frozen unsweetened fruit/veg = same state as raw.
3. Specific vs generic.
   - Generic query ("queso", "yogur", "galletas", "helado", "mermelada", "pizza"): accept the generic entry and
     the common plain variants (fat levels, the everyday types) — not flavoured, sweetened or filled ones
     unless the query is itself generic in that way ("yogures de fresa" accepts strawberry/fruit yogurt).
   - Specific query ("leche desnatada", "chocolate negro", "queso de cabra"): only that variant; a fat level or
     type that contradicts the query is not acceptable.
4. Any core source is fine: fdc, ciqual, bls, cofid, frida, matvaretabellen, fineli, mext, tfda, recipe. List
   them all when they match; do not stop at one. A `recipe` record is fine for a dish it names.
5. Mixed dishes: accept records that are that dish (any reasonable recipe of it). "huevos rotos" (fried eggs on
   fried potatoes) accepts a combined record only, or failing that is a gap if only the parts exist — do not
   accept the fried egg alone for the combo. Same for "espaguetis a la boloñesa" (not plain spaghetti, not the
   sauce alone), "bocadillo de jamón", "churros con chocolate", "pollo con patatas".
6. Drinks: "té"/"café"/"manzanilla"-style queries mean the plain infusion (no milk, no sugar). Zero/diet drinks
   accept only sugar-free variants. Alcohol: the type named ("vino tinto" any red wine; "ginebra" any gin).
7. Do not accept something just to avoid a gap. A wrong label is worse than a gap.

## Gaps

When nothing in the pool is acceptable, try 2 more phrasings (a synonym, a simpler English name), one call:

    cd /home/kirill/.herdr/worktrees/fooddb/bench-6k && set -a; . ~/.config/fooddb/bench.env; set +a; \
      TMPDIR=/home/kirill/.cache/tmp-gate uv run python /home/kirill/.cache/bench-es/gather.py try "alt 1" "alt 2"

It prints `records<TAB>kcal [kcal source]<TAB>name<TAB>via`. If something acceptable turns up, accept it by record id (all of
the product's records, comma-split into separate strings) and set best to one of them; also put the phrasings in
`tried`. If still nothing: `"accept": [], "best": null, "gap": true, "tried": [...]`, and `why` says what was
searched. Never print or echo the API key; only that command, no other HTTP calls; run retries one at a time.
Spanish dishes WILL often be gaps: that is a real finding, keep them as gaps.

## kcal reference (fix 4) — no Spanish national table

fooddb has no Spanish table (BEDCA is not loaded), so `best` is the best acceptable core record from any table.
The pool line shows `kcal [src]`: the product's merged kcal and the table it came from. `best` MUST be a
candidate whose kcal source equals its own source (`[fdc]` on an fdc record, `[ciqual]` on a ciqual record) —
otherwise the number belongs to another table's record. Among acceptable candidates that pass that check,
pick the one that describes the query most exactly (the Spanish form, the right preparation); on a tie prefer
fdc (as the existing ES cases do), then ciqual, then bls, then cofid, then the rest. If NO acceptable
candidate passes the check, choose the best one anyway and say so in `why` (the assembler will flag it).

**Missing canonical record**: when the pool has acceptable candidates but plainly lacks the obvious plain
record (e.g. "Apples, raw, with skin"), you MAY run one `gather.py try` to find it and add it by record id.

## Spanish conventions (decided by how people in Spain eat and say it; these bind every label)

Words that are ambiguous or mean something specific in Spain:
- **plátano** = banana (Canary banana), NOT plantain. **plátanos de canarias** = banana.
- **tortilla** alone and **tortilla de patatas / española / pincho de tortilla** = Spanish potato omelette
  (egg + potato, with or without onion), as eaten. **tortilla francesa** = plain omelette.
  **tortilla de trigo** = wheat-flour tortilla wrap.
- **bocadillo** = baguette sandwich; **sándwich mixto** = toasted ham-and-cheese sandwich (croque monsieur
  counts). These and **pan con tomate**, **tostada con aguacate**, **sándwich vegetal**, **montadito** need a
  combined record (rule 5).
- **tostada** = toasted white bread slice. **pan tostado** = toasted bread (packaged crispbread-toast also).
  **biscotes** = rusks/melba toast. **picos / colines** = breadsticks (grissini). **regañás** = thin crisp
  wheat crackers (plain wheat crackers count; rye crispbread does not). **picatostes** = croutons.
- **barra de pan** = white baguette: baguette and plain white wheat bread count. **pan de payés** = rustic
  white/wheat country loaf. **pan de molde** = sliced sandwich/toast bread (white unless "integral").
- **magdalenas** = Spanish plain/lemon sponge cupcakes: plain sponge muffins or madeleines count, chocolate-chip
  or blueberry muffins do not. **bizcocho / bizcocho de yogur / sobaos** = plain sponge/butter cake (not filled,
  not iced). **ensaimada** = only an ensaimada record (lard-laminated sweet bun) else gap. **napolitana de
  chocolate** = pain au chocolat. **roscón de reyes** = sweet brioche ring: plain brioche/sweet yeast bread counts.
- **leche semidesnatada** = 1.5-1.8 % milk; **desnatada** = skim (≤ 0.5 %). **leche condensada** = SWEETENED
  condensed milk. **leche evaporada** = unsweetened evaporated. **bebida de avena/soja/almendras** = plant
  drink: plain unsweetened and plain sweetened both count, flavoured (chocolate) not; best unsweetened.
- **yogur griego** = Greek-style plain yogurt (any fat level; not sweetened/flavoured). **yogur líquido** =
  drinking yogurt (any flavour). **kéfir** = kefir.
- **queso fresco / queso de burgos** = fresh unripened white cheese (queso blanco/panela-type, ~15-20 % fat).
  Not quark/fromage frais, not cottage cheese, not cream cheese, not mozzarella. **queso batido** = quark /
  fromage blanc (any fat level; best low-fat). **requesón** = ricotta/whey cheese (ricotta counts; cottage cheese
  does not). **queso crema** = cream cheese.
- **queso curado** = aged hard cheese of the Manchego type: manchego and generic hard/aged sheep or mixed-milk
  cheese count; gouda, cheddar, parmesan do not. **queso semicurado** = semi-cured Manchego-type: manchego and
  generic semi-hard cheese count. **queso manchego** = manchego only. **queso de cabra** = goat cheese (soft or
  semi-hard). **queso en lonchas** = sliced sandwich cheese: gouda/edam/havarti-type semi-hard and processed
  cheese slices count (generic). **queso rallado** = grated cheese: any plain grated cheese (generic).
- **nata para montar** = whipping cream 30-36 %. **nata para cocinar** = cooking cream ~15-20 %.
  **nata montada** = whipped cream (aerosol or whipped). **cuajada** = junket/set milk curd: only such a record.
- **huevo frito** = egg fried in oil. **huevos revueltos** = scrambled eggs. **huevo cocido** = hard-boiled.
- **jamón serrano / jamón ibérico** = dry-cured RAW ham (prosciutto/Parma type, BLS "raw ham"). Not cooked ham.
  **jamón york / jamón cocido** = cooked ham. **lomo embuchado** = dry-cured pork loin only. **cecina** =
  air-dried cured beef (bresaola/Bündnerfleisch count).
- **chorizo** = Spanish dry-cured chorizo, as eaten sliced (fresh Mexican chorizo does not count).
  **salchichón / fuet** = dry-cured salami-type sausage: salami records count. **morcilla** = blood sausage (any
  blood sausage incl. rice/onion). **sobrasada** = only a sobrasada record else gap. **butifarra** = fresh
  Catalan pork sausage: fresh pork sausage (raw or plainly cooked, bratwurst-type) counts.
- **salchichas** = frankfurter/wiener-type sausages (the pack "salchichas Frankfurt"). **salchichas frescas** =
  fresh raw pork sausages (raw or plainly cooked).
- **ternera** = beef (Spanish "ternera" is what the supermarket sells as beef): beef and veal, lean, raw or
  plainly cooked. **filete de ternera** = lean beef/veal steak. **carne picada** = mince: Spanish packs are
  mixed pork-beef or beef: accept generic, mixed and beef mince (raw or plainly cooked), not pork-only.
  **carne picada de ternera** = beef (or veal) mince only.
- **hamburguesa** alone = the burger sandwich (bun + patty) as ordered; a plain beef patty also counts because
  Spanish packs call patties "hamburguesas"; best = the sandwich. **hamburguesa de ternera** = beef patty
  (raw or plainly cooked), not the sandwich.
- **pavo** = turkey meat (breast default), raw or plainly cooked. **fiambre de pavo** = turkey breast cold cut.
- **pollo empanado** = breaded chicken fillet/escalope (not nuggets). **san jacobo** = breaded ham-and-cheese
  cutlet: cordon bleu of any meat counts. **cachopo** = breaded beef stuffed with ham and cheese: beef/veal
  cordon bleu counts. **filete empanado** = breaded escalope of veal, beef or pork (not chicken).
- **secreto ibérico** = fatty pork shoulder cut: pork shoulder/neck/collar, raw or plainly cooked.
  **panceta** = fresh pork belly (raw or plainly cooked). **bacon** = cured/smoked bacon, raw or fried.
  **costillas de cerdo** = pork spare ribs raw or plainly cooked (not sauced). **torreznos** = fried pork belly
  strips: fried pork belly and pork cracklings/rinds count. **carrillada** = pork cheek only.
- **atún** plain: raw, plainly cooked, and canned (drained, in oil or water; not in sauce). **atún en lata**:
  canned, oil or water. **atún en aceite**: canned in oil only. **atún al natural**: canned in water/brine only.
  **bonito del norte** = albacore ("white tuna"), canned or raw; light/skipjack tuna does not count.
- **sardinas** plain: raw, cooked, canned in oil. **sardinas en lata**: canned (oil default; in tomato not).
- **boquerones** = fresh anchovies, raw or plainly cooked. **boquerones en vinagre** = vinegar-marinated
  anchovies only. **anchoas** = salted / canned-in-oil anchovy fillets.
- **bacalao** plain = cod: fresh cod raw/cooked AND desalted (soaked) salt cod; NOT dry salt cod as sold dry.
  **bacalao desalado** = soaked salt cod only (fresh cod does not count).
- **gambas / langostinos** = shrimp/prawns, raw or boiled. **calamares** plain = squid raw/plainly cooked;
  **a la romana** = battered fried squid rings. **gulas / palitos de cangrejo / surimi** = surimi.
- **merluza a la romana / pescaíto frito** = battered/floured fried fish: the named fish fried in batter, or a
  generic "fish, battered/floured, fried" record; a different named species does not count.
- **pimientos de padrón** = small green peppers fried in oil: fried green peppers only.
  **pimientos del piquillo / pimientos asados** = roasted red peppers (jarred roasted count).
- **maíz** = sweetcorn kernels: canned sweetcorn is the reference; raw/boiled/frozen also count; maize grain,
  flour, popcorn do not. **setas** = oyster mushrooms / wild mushrooms (not button mushrooms).
  **champiñones** = button mushrooms. **col** = white/green cabbage. **lombarda** = red cabbage, raw or plainly
  cooked. **judías verdes** = green beans. **alubias blancas** = white beans; **judías pintas** = pinto beans.
  **habas** = broad beans, fresh/frozen or dried. **acelgas** = Swiss chard. **boniato** = sweet potato.
- **aceitunas** = table olives in brine: green (the Spanish default) and generic olives; best green.
  **aceitunas negras** = black olives only.
- **tomate frito / salsa de tomate** = cooked tomato sauce (with oil): plain tomato sauce counts; passata,
  ketchup and meat/pasta sauces do not. **tomate triturado** = canned crushed tomatoes.
- **alioli** = garlic mayonnaise (aioli). **salsa rosa** = mayonnaise + ketchup sauce: Marie Rose/European
  "cocktail sauce" and thousand island count; the US ketchup-horseradish cocktail sauce does NOT.
  **salsa brava** = only a brava/spicy paprika-tomato sauce record else gap. **pimentón** = paprika powder.
  **vinagre de módena** = balsamic vinegar.
- **patatas fritas** alone: in Spain the same words mean fries AND bagged crisps; both count, best = fries.
  **patatas fritas de bolsa** = crisps only. **patatas a lo pobre** = pan-fried potato slices with onion and
  pepper: pan-fried potatoes count, deep-fried fries do not. **patatas bravas** = only a bravas record (or fried
  potatoes with spicy sauce). **patatas alioli** = boiled potatoes dressed in garlic mayonnaise: potato salad
  with mayonnaise counts. **ensaladilla rusa** = Russian/Olivier potato salad with mayonnaise: mayonnaise potato
  salads count; vinegar potato salad does not.
- **croquetas** = béchamel croquettes (ham default; chicken, cod count for the plain word). Potato croquettes
  (BLS "Kroketten"/potato croquettes) are a DIFFERENT food. **croquetas de jamón / de pollo**: that filling only.
- **paella** alone (generic): any paella (mixed, chicken, seafood); best mixed/valenciana.
  **paella de marisco**: seafood paella only. **paella valenciana**: chicken (and rabbit) paella only.
- **gazpacho** only gazpacho; **salmorejo** only salmorejo. **cocido madrileño**: cocido or a chickpea stew with
  meat. **fabada**: fabada or white-bean stew with pork sausage. **lentejas con chorizo**: lentil stew with
  chorizo/sausage or meat (a vegetarian lentil soup does not count). **potaje de garbanzos**: chickpea stew
  (with spinach/veg). **caldo de pollo** = ready chicken broth (not dry stock cube/powder).
- **albóndigas** = meatballs, cooked (any sauce or none); **albóndigas en salsa** = meatballs in sauce only.
- **pisto** = ratatouille counts. **escalivada / verduras a la plancha** = roasted/grilled mixed vegetables
  (peppers, aubergine, onion). **menestra** = cooked mixed vegetables.
- **pollo al ajillo** = chicken pieces pan-fried with garlic: pan-fried (unbreaded) chicken counts.
  **gambas al ajillo** = prawns sautéed in garlic oil: sautéed/fried prawns count, boiled do not.
  **pulpo a la gallega** = boiled octopus (with oil/paprika). **champiñones al ajillo** = sautéed mushrooms.
  **coliflor rehogada** = cauliflower sautéed in oil (boiled does not count). **berenjenas con miel** = fried
  (floured/battered) aubergine, with or without honey.
- **empanada gallega** = large filled pie: tuna or meat empanada records. **empanadillas** = small savoury
  turnovers (tuna/meat), fried or baked; Latin-American empanadas count.
- **huevos rellenos** = stuffed eggs (deviled eggs count). **huevos rotos** = combined only.
- **cochinillo asado** = roast suckling pig: roast pork WITH skin/crackling counts; lean roast loin does not.
- **churros / porras** = fried dough churros (porras are thick churros: churros records count).
  **chocolate a la taza** = thick hot chocolate drink made with milk: hot chocolate/cocoa drink with milk counts.
- **turrón** alone = almond turrón (hard Alicante default; soft Jijona also counts); **turrón de jijona** = soft
  almond turrón only. **polvorones** = polvorón/mantecado record only. **mazapán** = marzipan.
  **torrijas** = Spanish French toast: French toast / pain perdu counts. **flan** = crème caramel.
  **natillas** = custard dessert / vanilla pudding. **crema catalana** = crème brûlée counts.
  **arroz con leche** = rice pudding. **tarta de queso** = baked cheesecake. **tarta de santiago** = almond cake.
- **galletas** generic: plain sweet biscuits; **galletas maría** = Marie / rich tea / plain tea biscuits.
  **donut** = ring doughnut (plain or sugar-glazed; filled Berliner does not count). **palmera de chocolate** =
  chocolate-coated palmier only. **buñuelos** = sweet fritters/beignets (choux or yeast). **gofre** = waffle.
- **crema de cacao** = chocolate hazelnut spread. **cacao en polvo** = the sweetened cocoa drink powder of the
  Spanish breakfast (instant cocoa mix); unsweetened baking cocoa does not count.
  **gominolas** = gummy candy. **caramelos** = hard candy. **dulce de membrillo** = quince paste only.
- **café solo** = espresso (black brewed coffee also counts). **cortado** = espresso with a dash of milk: only a
  macchiato/cortado record else gap. **café con leche** = coffee with milk / café au lait / latte.
  **manzanilla** = chamomile infusion (not sherry, not olives).
- **zumo de naranja** = orange juice (fresh or packaged; not nectar, not orange drink). **natural** = freshly
  squeezed / raw orange juice only.
- **refresco de cola** = sugared cola. **cola zero** = sugar-free cola only. **gaseosa** = Spanish clear
  sweet soda water: lemon-lime soda / lemonade (sugared or diet) count.
- **tinto de verano** = red wine with lemon soda: only such a record (red wine spritzer counts); plain wine
  does not. **clara con limón** = beer with lemon soda: shandy/radler. **caña** = draught lager beer.
  **sangría** = sangria only. **cava** = dry sparkling wine. **horchata** = Valencian tiger-nut drink only
  (Mexican rice horchata does NOT count).
- **frutos secos** = mixed nuts (raw or roasted/salted). **pipas** = sunflower / pumpkin seed kernels, raw and
  roasted/salted. **almendras** plain = raw almonds; **almendras tostadas** = roasted (salted too).
  **cacahuetes, anacardos, pistachos**: raw and roasted/salted. **castañas**: raw, roasted or boiled.
  **altramuces** = brined/cooked lupin beans (not flour).
- **melón** = sweet melon (piel de sapo / honeydew / cantaloupe all count), raw. **paraguayo** = flat peach:
  peach counts. **dátiles** = dried dates (as sold in Spain), fresh also count. **pasas** = raisins.
  **ciruelas pasas** = prunes. **higos secos** = dried figs.

Generic words in this set (cap ~3 %): queso (existing), pizza, helado, galletas, mermelada, croquetas, frutos
secos, queso en lonchas, queso rallado, paella, sushi. Pick the most typical form and say so in `why`.

## Decisions taken at review (applied in labels/fix.jsonl)

- **bocadillo de jamón** means dry-cured (serrano) ham: the French cooked-ham baguettes do not count → gap.
- **pollo con patatas** = roast chicken with potatoes: a boiled-potato/fried-chicken dish in béchamel does not
  count → gap.
- **tortilla española con cebolla**: a potato omelette that does not mention onion counts (rule: with or without).
- **patatas fritas**: the crisps accepted for "patatas fritas de bolsa" are added (rule: both meanings count).
- **cola zero**: every sugar-free cola in the pools is added.
- **sangría**: the only record (CIQUAL 1017) has no kcal: the case keeps its records and carries no kcal.
- **paella**: CIQUAL 25242 "Paëlla, home-made" is never returned for "paella" (the ë), found in other pools, added.
