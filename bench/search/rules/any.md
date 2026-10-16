# Labelling rules for the ANY (no-country) search bench

The queries are `name_en` values: the canonical English food name the eait meal analyzer writes for each
item it sees on a photo or in a typed meal, used only for the catalog lookup. Plain, generic, lowercase
English ("chicken breast", "white rice", "grilled chicken breast", "pad thai"). The search runs WITHOUT a
country, so every core table competes. The grams the analyzer pairs with the name are grams of the food
AS SERVED (prompt rule: "Weights are grams of the food as served"), which decides the kcal reference.

Input: `batches/bK.txt`. Each block is one query: `## <i> | <q> | head: ... | plain: ... | cat: ...`, then the
candidate pool, one line per product: `cK  <source>  <record ids>  <kcal/100 g> [kcal source]  <name>`. Names are
English. Candidates are sorted by source then name, NOT by search rank: rank is irrelevant here.

Output: `labels/bK.jsonl`, one JSON object per query, in input order, every query present:

    {"i": 12, "q": "bagel", "accept": ["c3", "c7"], "best": "c3", "why": "bread: plain bagel"}
    {"i": 40, "q": "X", "accept": [], "best": null, "gap": true, "tried": ["alt 1", "alt 2"], "why": "veg: searched X, alt1, alt2; no Z in the pool"}

- `accept`: EVERY candidate that is the same food in the same state. Candidate ids (`"c3"`), or record ids
  (`"fdc:171845"`) for items found only by a retry phrasing (see gaps).
- `best`: one element of `accept`, the kcal reference (see below).
- `why`: `"<cat>: <what makes it representative>"`, short. cat is the block's cat.

## What counts as acceptable

1. Same food. A variety is still the food ("apple" accepts any apple variety, raw). A different food is not,
   however close in kcal ("whole wheat bread" accepts wholemeal breads, not white bread; "salmon" not trout).
2. Same state. Cooking states, each one group:
   - raw / as bought;
   - dry heat: grilled, broiled, barbecued, roasted, baked (one group);
   - fried WITHOUT coating: pan-fried, sautéed, stir-fried, fried in oil;
   - moist heat: boiled, steamed, poached, stewed without sauce, microwaved;
   - breaded / battered / deep-fried in coating;
   - canned, dried, smoked, pickled, cured: each its own state.
   A query that names a preparation ("grilled chicken breast", "boiled potatoes", "fried egg") accepts only
   its group. A plain query for a food normally eaten cooked (meat, fish, seafood, potato, rice, pasta,
   noodles, grains, legumes, cooking vegetables) accepts raw/dry AND every plainly cooked group (dry heat,
   fried without coating, moist heat) — never breaded, battered, in a sauce, or part of a dish. A plain query
   for a food normally eaten raw (fruit, salad leaves, cucumber, tomato, radish, nuts, seeds): raw only
   (nuts: raw or roasted). Stewed, canned, dried, juice are different foods from the fresh fruit.
3. Specific vs generic.
   - Specific query ("greek yogurt", "skim milk", "dark chocolate", "basmati rice"): only that variant; a fat
     level or type that contradicts the query is not acceptable ("lean ground beef" = ≥90 % lean).
   - Generic query: accept the generic entry and the common plain variants; not flavoured, sweetened or
     filled ones unless the query is itself generic that way ("fruit yogurt" accepts any fruit yogurt).
4. Any core source is fine: fdc, bls, ciqual, cofid, frida, matvaretabellen, fineli, mext, tfda, recipe.
   List them ALL when they match; do not stop at the first. A `recipe` record is fine for a dish it names.
   Branded records (UPPER-CASE brand names, "McDONALD'S, ...", "ACME, ...") are acceptable only when they are
   plainly the same food with nothing added; never `best` while a generic record is acceptable.
5. Dishes: accept records that ARE that dish (any reasonable recipe of it, any country's table). A combined
   dish needs a combined record: "spaghetti bolognese" is not plain spaghetti and not the sauce alone;
   "fish and chips", "full english breakfast", "chicken with rice" need a record of the whole plate, else gap.
   The main ingredient alone, or a different dish of the same family, is a gap ("chicken tikka masala" does
   not accept "butter chicken"; "chicken curry" accepts any chicken curry with sauce, Indian/Thai/other).
   Fast-food versions of a dish (FDC "Fast foods, ...") count as the dish.
6. Drinks: "coffee"/"tea"/"espresso"/"green tea" mean the plain brewed infusion (no milk, no sugar). Diet/zero
   drinks accept only sugar-free variants. Alcohol: the type named ("red wine" any red; "vodka" any ~40 %).
7. Do not accept something just to avoid a gap. A wrong label is worse than a gap.

## kcal reference (`best`)

- Source: prefer a USDA FDC generic record (SR Legacy / Foundation for single foods — names like "Chicken,
  broilers or fryers, breast, meat only, cooked, roasted"; FNDDS for dishes and as-eaten mixtures — names like
  "Pizza, cheese, from restaurant or fast food"). Else the best acceptable core record (CoFID for British
  dishes, CIQUAL for French, BLS for German/central-European, Frida/Matvaretabellen/Fineli for Nordic, MEXT
  for Japanese, TFDA for Taiwanese/Chinese, then any) — the table of the dish's home cuisine first.
- Its kcal must be the cited record's OWN: the pool line shows `kcal [src]`, and `best` must be a candidate
  whose `[src]` equals its own source (a `fdc` product showing `[fdc]`). If the obvious best shows another
  table's kcal, pick another acceptable record whose kcal is its own. assemble refuses otherwise.
- Form (the grams are AS SERVED, so the reference is the as-served form):
  - query names a preparation → a record of that preparation;
  - plain query for a food eaten cooked → a plainly COOKED record: meat/poultry roasted, grilled or
    pan-browned (ground meats), without skin unless the query says skin/wings/thigh with skin; fish cooked
    dry heat; shrimp/seafood cooked moist heat; rice, pasta, noodles, couscous, bulgur, quinoa, barley,
    buckwheat, millet, polenta, legumes (dry types) → boiled/cooked; potato, sweet potato, cassava, yam,
    taro, plantain → boiled; eggplant, okra, artichoke, brussels sprouts, green beans, asparagus, pumpkin,
    squash, turnip, parsnip, beetroot, celeriac, sweet corn, peas, broccoli, cauliflower, chard, collard
    greens → boiled; "egg" plain → hard-boiled whole egg;
  - raw/as-bought for everything eaten raw or as bought: fruit, salad vegetables, carrot, cabbage, spinach,
    kale, onion, pepper, mushrooms, nuts, seeds, dairy, bread, cereals and oats (dry), flour, oils, sauces;
  - foods only eaten prepared (fries, bacon, scrambled eggs, mashed potatoes, oatmeal porridge, pancakes,
    dishes): the as-eaten record.
  If the as-served record is not in the pool, the raw record may be `best` only when no acceptable cooked
  record with its own kcal exists anywhere in the pool (prefer one `gather.py try` to find it first).

## Conventions for ambiguous words (decided for a world-wide plate)

Meat, fish, eggs
- **chicken breast** = skinless breast meat. **chicken thigh / drumstick / leg / wings** = with or without skin;
  best = meat and skin, cooked. **fried chicken** = breaded/battered deep-fried chicken (any piece).
  **roast chicken** = roasted chicken meat (any parts, skin on or off). **chicken nuggets** = breaded nuggets as eaten.
- **ground beef** = any fat level; **lean ground beef** / **beef mince** as named (beef mince = any fat level).
- **steak** words: beef steak/grilled steak = any beef steak cut, best = top sirloin cooked; named cuts bind.
- **roast beef** = roasted beef (sliced/deli roast beef counts), not raw. **pulled pork** = as eaten, with or
  without sauce. **bacon** = pork bacon cooked (as eaten); "fried bacon" the same; raw bacon not accepted.
- **ham** = cured ham (cooked/boiled ham, sliced); prosciutto = dry-cured, its own food. **smoked ham** = smoked
  cured ham (cooked ham records that are smoked count). **deli meat** = sliced cold cuts (ham, turkey, bologna-type);
  generic, best = sliced ham or luncheon meat as typical.
- **frankfurter sausage** = Wiener/frankfurter/hot dog sausage (no bun). **hot dog** (dish) = the sausage IN A BUN;
  a frankfurter alone is not a hot dog. **pork sausage** = fresh pork sausage (raw or cooked; best cooked).
  **polish sausage** = kielbasa. **bratwurst**, **chorizo**, **salami**, **pepperoni**, **mortadella**,
  **blood sausage**, **chicken sausage**: only that sausage.
- **meatballs** = plain cooked meatballs (any meat), not in sauce; **swedish meatballs** = that dish (with gravy ok).
- **hamburger patty** = cooked beef patty without bun. **hamburger / cheeseburger** = the sandwich with bun.
- **mutton** = sheep meat (lamb records count only if named mutton/sheep; else lamb is acceptable for mutton
  ONLY as a gap fallback — prefer gap). **goat meat**, **horse meat**, **venison**, **rabbit meat**: only that animal.
- **tuna** words: **canned tuna** = canned light or white, water or oil, drained or not; **tuna in oil** = canned in
  oil only; **tuna steak** = fresh/frozen tuna, raw or cooked. **canned sardines** = canned in oil or tomato.
  **sardines** plain = fresh or canned (canned is how most are eaten); best = canned in oil drained.
- **smoked salmon** = cold- or hot-smoked salmon (lox). **salmon roe** = red caviar/ikura.
- **shrimp / prawns / king prawns** = the same animal family; plain = raw or cooked (not breaded); best = cooked.
- **fried fish** = coated (battered/breaded) fried fish fillet, any white fish; generic;
  **battered fish** = battered fried fish only. **white fish fillet** = any lean white fish (cod, haddock,
  pollock, hake, tilapia, whiting), raw or plainly cooked; generic, best = cod cooked.
- **fish sticks** = breaded fish fingers (frozen or cooked). **imitation crab** = surimi.
- **egg** plain = whole hen's egg, raw or plainly cooked (boiled, poached); best = hard-boiled. **fried egg**,
  **scrambled eggs**, **poached egg**, **boiled egg** (hard or soft): only that preparation.
  **omelette** = plain egg omelet (with or without a little milk/cheese), not a filled/vegetable/Spanish omelette.

Dairy
- **whole milk** = 3.25–3.8 % fat. **low-fat milk** = 1–2 % (semi-skimmed, 1 %, 2 %). **skim milk** = ≤0.5 %.
- **plain yogurt** = natural unsweetened yogurt, any fat level; **greek yogurt** = plain Greek/strained, any fat
  level, not flavoured; **low-fat yogurt** = plain low-fat only.
- **cheese** (generic) = everyday hard/semi-hard cheese: cheddar, gouda, edam, emmental, generic "cheese" records;
  best = cheddar. Named cheeses only that cheese ("swiss cheese" = emmental/swiss-type).
- **processed cheese slice** = processed/American cheese slices. **farmer's cheese** = tvorog/quark-like fresh
  curd cheese; cottage cheese and quark records count. **quark** = quark/tvorog/fromage frais-type curd, plain.
- **heavy cream** = ≥30 % (double/whipping/heavy). **whipped cream** = whipped, incl. aerosol.
- **sweetened condensed milk** ≠ **evaporated milk** (unsweetened).

Vegetables, fruit
- **sweet corn** = kernels raw, boiled or canned drained; **corn on the cob** = cooked sweet corn (boiled/grilled).
- **green peas** = raw, frozen or boiled; canned peas count; **frozen peas** = frozen (raw or boiled).
- **beetroot** plain = raw or plainly cooked; pickled is a different food. **pickled cucumber** = dill/sour pickles,
  gherkins. **olives**: green/black as named, any brine/cured.
- **avocado** raw. **chili pepper** = hot chili, raw; **jalapeno** raw (pickled is "pickled jalapenos").
- **fresh coriander** = cilantro leaves; **seaweed** = edible seaweed (wakame, kelp, nori, raw or dried);
  generic; **nori** = dried nori sheets.
- **mixed vegetables** = frozen/canned mix (carrot, peas, corn, beans), raw or boiled. **grilled / roasted /
  steamed / stir-fried vegetables** = a mixed-vegetable record in that state group; generic.
- **dates** = dried dates (how they are sold); **medjool dates** = Medjool only. **raisins, prunes, dried
  apricots/mango/cranberries/figs** = dried. **fresh figs** = raw figs. **coconut** = fresh coconut meat raw.
- **cherries** = sweet cherries raw; **sour cherries** = sour cherries raw. **plantain** = raw or boiled;
  **fried plantain** = fried. **applesauce** = sweetened or not. **canned peaches** = in juice or syrup.
- **berries** words (frozen berries, mixed berries) = a mixed-berry record, or failing that, any single common
  berry raw/frozen is NOT acceptable → gap. **fruit salad** = mixed fresh fruit (canned fruit cocktail counts
  only if no fresh record exists — then say so in why).

Starches
- **rice**, **pasta**, **noodles**, grains: plain query accepts dry and cooked; best = cooked. **instant noodles**
  = instant ramen noodles, dry or prepared; best = prepared. **oatmeal porridge** = oats cooked with water (or milk);
  **rolled oats** = dry oats. **granola / muesli / corn flakes** = dry cereal.
- **mashed potatoes** = with milk/butter as eaten; **french fries** = as eaten (fried or oven-baked), not frozen
  unprepared; **potato chips** = crisps. **hash browns** = as eaten.
- **baked beans** = beans in tomato sauce (canned). **refried beans** = refried. **tofu** = plain firm/regular
  tofu raw; **fried tofu** = deep-fried tofu. **edamame** = green soybeans, raw or boiled.

Dishes (rule 5 applies; examples of decisions)
- **pizza** (generic) = cheese/margherita pizza, any crust; best = cheese pizza. **pizza margherita** = cheese or
  margherita; **pepperoni pizza** only pepperoni.
- **lasagna** = meat lasagna (vegetable lasagna counts only if no meat one exists). **risotto** (generic) = any
  plain risotto (cheese/mushroom/vegetable). **sushi** (generic) = any assorted sushi/maki/nigiri record; best =
  the most typical mixed sushi.
- **chicken curry / fish curry / egg curry / lamb curry / vegetable curry** = that curry with sauce, any cuisine.
  **dal** = cooked dal / dhal / lentil curry; plain boiled lentils do not count.
- **fried rice** = any fried rice (egg, vegetable, meat); **egg fried rice** = egg (± vegetable) fried rice.
- **chicken salad** = American mayo-dressed chicken salad OR a green salad topped with chicken — both count.
  **tuna salad** likewise. **green salad** = leaf salad without dressing (dressed counts too); generic.
- **hot dog** = sausage in bun. **burrito** words: as named (bean / chicken / breakfast).
- **dumplings**: **pork dumplings** = pork-filled Chinese/Japanese dumplings (jiaozi, gyoza, potstickers);
  **shrimp dumplings** = har gow / shrimp dim sum. **pelmeni / vareniki / manti / khinkali / pierogi** = only
  that dumpling (pelmeni and meat-filled pierogi are not each other; vareniki = pierogi with potato/cheese/fruit
  filling — pierogi records with those fillings count for vareniki).
- **blini** = thin Russian pancakes (crepes count); **syrniki** = quark pancakes; **potato pancakes** = draniki/
  latkes/rösti-type fried grated potato cakes.
- **plov** = pilaf with meat (plov/pilau/pilaf records with meat); **vegetable pulao** = vegetable pilaf.
- **chicken shawarma / beef shawarma** = the shawarma meat as served, or a shawarma plate; a wrap/sandwich
  record does not count (that is "chicken shawarma wrap", which needs the wrap). **doner kebab** = doner (in bread or meat
  only, both count). **kebab / lamb kebab / shish kebab** = grilled skewered meat of that kind.
- **hummus, guacamole, tzatziki, salsa, pesto, raita, chutney** are listed as dishes/sauces: the dip/sauce itself.
- **soup** words: that soup, ready-to-eat (condensed undiluted counts only as fallback, say so).

Drinks
- **water** = plain drinking water (tap, still mineral); **sparkling water** = carbonated plain water.
- **latte / cappuccino** = with milk, unsweetened (whole milk when unstated). **coffee with milk** = brewed coffee
  with milk (café au lait, white coffee). **tea with milk** = black tea with milk, unsweetened.
  **masala chai** = spiced tea with milk (sweetened counts). **hot chocolate** = made with milk.
- **iced tea** = ready-to-drink sweetened iced tea OR unsweetened brewed iced tea; best = sweetened RTD.
- **cola** = regular sugared cola; **diet cola** = sugar-free only. **lemonade** = sweetened lemon drink, still or
  sparkling. **energy drink** = regular sugared; **sports drink** = isotonic drink.
- **beer** = regular beer/lager 4–5 %; **non-alcoholic beer** only alcohol-free. **cider** = alcoholic cider.
- **fruit smoothie** = fruit (± yogurt/juice) smoothie; **protein shake** = any prepared protein shake.

Sauces & fats
- **cooking oil** / **vegetable oil** = any plant cooking oil (sunflower, rapeseed/canola, soybean, corn, generic
  vegetable oil); olive oil counts for "cooking oil" only; best = generic vegetable oil. Named oils bind.
- **mayonnaise** = regular, not light. **mustard** = prepared table mustard (yellow, Dijon, medium).
  **hot sauce** = thin chili/hot pepper sauce (Louisiana, Tabasco-type, sriracha counts); not sweet chili sauce.
- **marinara sauce** = plain tomato pasta sauce. **pesto** = basil pesto. **salsa** = tomato salsa.
- **strawberry jam** = strawberry jam or generic jam/preserves (unnamed fruit); other named fruits not.
- **sugar** = white granulated; **brown sugar** = brown. **honey**, **maple syrup** = plain.
- **gravy** = brown meat gravy, prepared. **curry sauce** = ready curry sauce (any style); **butter chicken
  sauce** = butter chicken/makhani/tikka masala sauce only, else a gap.
- **dressing** words: as named (ranch, caesar, vinaigrette = oil-and-vinegar/French/Italian; regular, not light).

Nuts & other
- Plain nut query = raw or roasted, salted or not; not honey-roasted, candied, chocolate-covered, nut butter.
  best = raw for almonds, walnuts, hazelnuts, pecans, macadamia, brazil, pine nuts; dry-roasted for peanuts,
  cashews, pistachios, mixed nuts. **roasted almonds**, **salted cashews**, **roasted salted peanuts**: as named.
- **roasted chestnuts** = roasted (boiled not). **protein powder** = whey protein powder, dry.

Generic words in this set (cap ~3 %): cheese, pizza, cake, cookies, ice cream, sushi, risotto, cooking oil,
deli meat, white fish fillet, mixed vegetables, grilled/steamed/roasted/stir-fried vegetables, green salad,
mixed salad greens, fruit salad, seaweed, mezze platter. Pick the most typical form and say so in `why`.

## Gaps

When nothing in the pool is acceptable, try 2 more phrasings (a synonym, a simpler English name), one call:

    cd /home/kirill/.herdr/worktrees/fooddb/bench-6k && set -a; . ~/.config/fooddb/bench.env; set +a; \
      TMPDIR=/home/kirill/.cache/tmp-gate uv run python /home/kirill/.cache/bench-any/gather.py try "alt 1" "alt 2"

It prints `records<TAB>kcal<TAB>name<TAB>via`. If something acceptable turns up, accept it by record id (all of
the product's records, comma-split into separate strings) and set best to one of them; also put the phrasings in
`tried`. If still nothing: `"accept": [], "best": null, "gap": true, "tried": [...]`, and `why` says what was
searched. The same `try` may also be used ONCE per query when the pool has acceptable candidates but plainly
lacks the canonical as-served record (e.g. cooked rice when only dry rice pooled). Never print or echo the API
key; only that command, no other HTTP calls; run retries one at a time (the script paces itself).

## Additions after batches b0-b5

- **Legumes**: a plain legume query (chickpeas, black beans, lentils, ...) accepts dry, boiled AND canned plain
  legumes (drained or not); beans in sauce (baked beans, chili, refried) do not count. best = boiled.
- **Pasta shapes**: a shape query (spaghetti, penne, macaroni, fusilli) accepts that shape and plain pasta
  records (dry or cooked); not whole-wheat/egg/spinach unless named.
- **A similarly named different species or variety is a different food** (wolffish ≠ catfish, horse mackerel ≠
  mackerel, nashi ≠ pear). Records weighed with bone/shell/stone are the same food (never best if a flesh-only
  record exists).
- **Toasted bread** is its own state. Light/low-fat variants do not count for a plain dairy word.
- **Dish reference**: prefer a home-made/restaurant record of a dish over a canned or dry-mix one as `best`
  (canned soups count only when nothing else exists; say so in why).
- A retry's record ids are used only for the query that ran it.
