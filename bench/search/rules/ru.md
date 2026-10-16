# Labelling rules for the RU search bench

Input: `batches/bK.txt`. Each block is one query: `## <i> | <q> | en: ... | head: ... | cat: ...`, then the
candidate pool, one line per product: `cK  <source>  <record ids>  <kcal/100 g> [kcal source]  <name>`. Names are English
(all names are English, except a `recipe:<slug>.ru` record). Candidates are sorted by source then name, NOT by search rank: rank is irrelevant here.

Output: `labels/bK.jsonl`, one JSON object per query, in input order, every query present:

    {"i": 12, "q": "батон", "accept": ["c3", "c7"], "best": "c3", "why": "bread: the everyday white wheat loaf"}
    {"i": 40, "q": "X", "accept": [], "best": null, "gap": true, "tried": ["alt 1", "alt 2"], "why": "veg: searched X, en Y, alt1, alt2; no Z in the pool"}

- `accept`: EVERY candidate that is the same food in the same state. Candidate ids (`"c3"`), or record ids
  (`"bls:G123100"`) for items found only by a retry phrasing (see gaps).
- `best`: one element of `accept`: the record that matches the Russian meaning most precisely (fat %, state,
  preparation). fooddb has no Russian national table, so on a tie prefer `fdc`, then `bls`, then any other core
  table; for a dish a `recipe` record of that dish is the natural best. This is the
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
      TMPDIR=/home/kirill/.cache/tmp-gate uv run python /home/kirill/.cache/bench-ru/gather.py try "alt 1" "alt 2"

It prints `records<TAB>kcal<TAB>name<TAB>via`. If something acceptable turns up, accept it by record id (all of
the product's records, comma-split into separate strings) and set best to one of them; also put the phrasings in
`tried`. If still nothing: `"accept": [], "best": null, "gap": true, "tried": [...]`, and `why` says what was
searched. Never print or echo the API key; only that command, no other HTTP calls; run retries one at a time.

## Russian conventions (decided by how people in Russia eat and say it)

fooddb has no Russian national table and almost no Russian names: a Russian query matches only the `recipe`
records' Russian names. Pools therefore come from the English translation, an English head noun and a plain
English form. The `en:` in each block is the meaning: label against the Russian `q`, read through these rules.

Words and defaults:
- **Хлеб / черный хлеб / ржаной хлеб**: Russian everyday dark bread is rye or rye-wheat; any rye or rye-wheat
  (mixed) bread counts, wholemeal rye too. **Бородинский** = dark rye bread with coriander/malt: rye bread counts.
  **Белый хлеб / батон / нарезной батон / тостовый хлеб** = white wheat bread (any plain white loaf, toast
  bread included; toasted bread does not count).
- **Цельнозерновой / с отрубями** = wholemeal; bran bread counts for "с отрубями", wholemeal counts for both.
- **Лаваш** = thin unleavened wheat flatbread: flatbread/lavash/tortilla-type wheat flatbread counts; pita counts
  for **лепешка** and **пита**, not for лаваш unless nothing else (then it is a gap, not a pita).
- **Сушки / баранки / бублик** = boiled-then-baked ring bagels; bagel records count (dry, plain).
- **Сухари** = dried bread rusks (zwieback counts). **Сухарики** = salted/flavoured snack croutons.
  **Гренки** = slices of bread fried in a pan: fried bread / French toast-like fried bread; plain toast does not.
- **Пирожок / пирожки** with a named filling: only a pie/pasty/turnover with that filling (baked or fried);
  a different filling or plain dough is a gap. **Беляш / чебурек** = fried meat-filled dough: the recipe
  chebureki counts for чебурек and беляш (same food: fried meat pie).
- **Ватрушка** = yeast bun with quark: quark/cheese danish counts.
- **Творог** = curd cheese (quark / tvorog; farmer's cheese; NOT cottage cheese in cream, which is
  **зерненый творог**). The % is fat in the product: **творог 5%** ≈ quark 4-6 % fat (US "quark 20 % f.i.d.m"
  ≈ 5 % fat counts), **творог 9%** ≈ 8-10 %, **0% / обезжиренный** = fat-free/low-fat quark (≤1.8 %).
  `recipe:tvorog` counts for plain творог only.
- **Сметана** = sour cream: plain generic sour cream for сметана; for 15 % / 20 % only a record of that fat level
  (15 % accepts 12-18 %, 20 % accepts 18-22 %).
- **Сливки** alone = drinking/coffee cream 10 %: accept cream 10-20 % (light/coffee/half-and-half) and generic cream;
  **сливки 33%** = whipping cream 30-36 %.
- **Кефир** = kefir (plain, unflavoured). **Кефир 1%** low-fat kefir only; **кефир 3,2%** whole kefir (3-3.5 %) and
  generic kefir. **Ряженка / варенец** = fermented baked milk: only such a record, else gap (kefir is not it).
  **Простокваша** = soured/clabbered milk: sour milk / "filmjölk"/"piimä"-type cultured milk counts.
  **Айран** = salted yogurt drink: `recipe:ayran` and ayran records.
- **Молоко 2,5%** ≈ reduced fat milk 1.5-2.5 % (2 % counts); **3,2%** = whole milk 3-3.5 %. **Топленое молоко** = baked
  milk: only such a record, else gap.
- **Сгущенка / сгущенное молоко** = SWEETENED condensed milk, never evaporated. **Вареная сгущенка** = dulce de leche.
- **Сыр** alone = generic hard/semi-hard cheese (Russian default: gouda/edam-type): accept gouda, edam,
  generic semi-hard/hard cheese. **Российский сыр** = semi-hard gouda/edam-type cheese (same set).
  **Брынза** = brined white cheese: feta and brined white cheese count. **Сулугуни** only suluguni, else gap
  (mozzarella is a different cheese). **Адыгейский** = fresh unripened cheese:
  only such a record (paneer/queso fresco count), else gap.
- **Сырок глазированный** = chocolate-glazed sweet curd bar: only such a record, else gap.
  **Творожная масса** = sweetened quark mass (with sugar, often raisins): sweet quark dessert counts, plain quark not.
- **Масло** in a dairy context = butter. **Топленое масло** = ghee/butter oil.
- **Яйца / яйцо** = chicken egg, whole, raw (boiled also counts for the plain word, per the cooked-food rule:
  eggs are eaten cooked). **Яичница** = fried eggs. **Омлет** = plain omelette.
- **Курица** cuts: **грудка / филе** = breast, skinless meat, raw or plainly cooked. Prepared forms only that form.
  **Курица жареная** = pan-fried chicken without coating; roasted counts (no batter). **Курица гриль** = rotisserie /
  roasted chicken, meat with skin or without.
- **Фарш** alone = Russian default mixed pork-beef mince ("домашний"): accept mixed and generic mince, raw or plainly
  cooked; not single-species. **Говяжий фарш** = ground beef only.
- **Свинина / говядина / баранина** alone: any lean-to-medium cut, raw or plainly cooked.
- **Сало** = salted (cured) pork back fat; raw back fat also counts. Not bacon.
- **Колбаса** alone = generic sausage; the Russian default is **вареная колбаса** = bologna / Lyoner-type
  (Doktorskaya): accept bologna, Lyoner, Fleischwurst, mortadella-type. Generic.
  **Сервелат** = semi-dry smoked cervelat. **Сосиски** = frankfurters/wieners. **Сардельки** = thick boiled
  sausages: bockwurst / knackwurst. **Ветчина** = cooked ham. **Буженина** = baked pork leg/loin cold cut: roast pork counts.
- **Котлета** = minced-meat patty (pork-beef default), fried: meat patty / hamburger patty / Frikadelle / meat loaf
  patty; not chicken, not breaded schnitzel. **Тефтели / фрикадельки** = meatballs (in sauce or plain).
- **Шашлык** alone = pork shashlik (the Russian default): `recipe:shashlik` and grilled pork kebab/skewer records.
- **Тушенка** = canned stewed beef/meat. **Холодец** = meat aspic/jelly: only such a record, else gap.
- **Бефстроганов, гуляш, азу, жаркое, голубцы, плов, …**: dish rule 5 — only a record of that dish.
- **Семга** = Atlantic salmon. **Слабосоленая семга / красная рыба** = lightly salted (cured) salmon: cured/salted
  salmon, gravlax and cold-smoked salmon (lox) count; raw or cooked salmon do not.
- **Селедка** alone = salted herring (as eaten in Russia, from the barrel/jar): salted, pickled or marinated herring
  fillets count; raw herring not. **Сельдь** = herring, raw or plainly cooked (cooked-food rule).
- **Шпроты** = smoked sprats canned in oil. **Печень трески** = canned cod liver. **Красная икра** = salmon roe.
  **Крабовые палочки** = surimi crab sticks.
- **Соленые огурцы** = salted/brined or vinegar pickled cucumbers (any pickle of cucumber).
- **Капуста** alone = white cabbage, raw (plainly cooked counts). **Квашеная капуста** = sauerkraut.
- **Морковь по-корейски** = Korean-style spicy carrot salad: only that, else gap.
- **Свекла** = beetroot raw or boiled (not pickled). **Редька** = black/white radish, daikon counts; small red radish not.
- **Зеленый лук** = spring onion/scallion. **Болгарский перец** = sweet bell pepper, any colour.
- **Кукуруза**: like the DE pilot, sweetcorn kernels canned/cooked/raw count; maize flour/grain not.
  **Кукуруза консервированная** = canned only. **Зеленый горошек** = green peas fresh/frozen/cooked/canned;
  **горошек консервированный** canned only.
- **Грибы** alone = cultivated mushrooms (champignons count). **Грибы жареные** = fried/sautéed mushrooms.
- **Вишня** = sour cherry (Russian default); sweet cherry is **черешня**. **Смородина** alone = blackcurrant default,
  redcurrant also counts. **Черника** = bilberry/blueberry. **Курага** = dried apricots. **Финики** = dates as sold in
  Russia: dried (Deglet/Medjool) count. **Инжир** = fresh fig; dried fig is a different food.
- **Гречка** = buckwheat groats, the kasha: dry groats and boiled buckwheat and `recipe:grechka` all count for plain
  гречка-type queries; **гречка отварная** = boiled only (+ recipe:grechka). **Гречневая крупа** = dry groats
  (boiled also counts per cooked-food rule).
- **Овсянка** alone = oatmeal: rolled oats dry AND oat porridge cooked with water count; porridge with milk only for
  **на молоке**. **Манная каша** = semolina porridge cooked with milk (semolina pudding counts). **Каша** with a grain
  named = that grain's porridge (cooked in water or milk); plain cooked grain counts for buckwheat/millet/oat.
- **Макароны** = dry pasta (durum or generic) raw or plainly cooked; **лапша** = noodles (egg noodles, generic noodles);
  **вермишель** = thin pasta/vermicelli.
- **Картошка** = potato. **Жареная картошка** = pan-fried potatoes (Bratkartoffeln, home fries), not French fries.
- **Горох** = dried split peas. **Фасоль** alone = dried kidney beans (cooked counts).
- **Суп / борщ / щи / солянка / уха / окрошка …**: only a record of that soup. **Куриный суп** = chicken soup (with
  vegetables/noodles counts); **суп с лапшой / куриная лапша** = chicken noodle soup only. **Куриный бульон** = chicken
  broth/stock (as a soup).
- **Пельмени отварные** = pelmeni boiled (recipe:pelmeni). **Вареники** with a filling: only that filling
  (`recipe:vareniki` is the potato one). **Ленивые вареники** = quark dumplings.
- **Блинчики** = thin crepes; `recipe:blini` counts (Russian блины are thin). **Оладьи** = small thick
  yeast/kefir pancakes: pancake records (American-style) count. Filled crepes only with that filling.
- **Сырники / драники / творожная запеканка**: only that dish (potato pancake for драники, quark casserole/cheesecake
  bake for запеканка).
- **Шаурма / шаверма** = shawarma/doner wrap: shawarma, doner/gyro wrap records count.
- **Хачапури** = cheese-filled bread; only that dish, else gap.
- **Винегрет** = beet-potato-pickle salad: only that, else gap. **Селедка под шубой** = layered herring-beet salad:
  only that. **Салат из огурцов и помидоров** = cucumber-tomato salad (with oil or sour cream).
- **Бутерброд с X** = open sandwich bread + X: only a record of a sandwich with X (any bread); bread alone not.
- **Шоколад** alone = milk chocolate (the everyday default; generic chocolate records count). Generic.
- **Конфеты** = chocolate candies/pralines (generic). **Зефир** = zefir/marshmallow-meringue: marshmallow records count.
  **Мармелад** = fruit jelly candy/gummies, NOT orange marmalade. **Пастила** = fruit paste/marshmallow: only that.
- **Печенье** alone = plain sweet biscuits (shortbread/butter/tea biscuits), generic. **Пряники** = glazed gingerbread.
- **Торт** alone = layered cream cake (generic): cream/layer cake, sponge with cream. **Пирожное картошка**, **птичье
  молоко**, **медовик**, **наполеон**: only that, else gap (mille-feuille/cream slice counts for наполеон).
- **Шарлотка** = apple sponge cake: apple cake records count (not apple pie with pastry).
- **Мороженое** alone = vanilla dairy ice cream (generic). **Пломбир** = rich full-fat vanilla ice cream (premium
  ice cream ≥ 12 % fat counts; generic vanilla ice cream too). **Эскимо** = chocolate-coated ice cream bar.
- **Варенье / джем** = jam/preserves (any fruit). **Мед** = honey. **Сахар** = white sugar.
- **Семечки** = sunflower seed kernels, roasted (dry-roasted, salted or not) or raw.
- **Чай / кофе / черный чай / зеленый чай / американо / эспрессо** = the plain infusion (rule 6). **Чай с сахаром** =
  sweetened tea only. **Кофе с молоком** = coffee with milk (café au lait / white coffee; latte counts).
  **Растворимый кофе** = instant coffee AS A DRINK (prepared with water); the powder is a different food.
- **Какао** = cocoa drink made with milk (hot chocolate counts); cocoa powder is a different food.
- **Компот** = drink of fruit stewed in sweetened water: only such a drink, else gap (canned fruit compote is not it).
  **Морс** = sweetened berry drink: cranberry juice drink/cocktail counts. **Кисель** = starch-thickened fruit drink:
  only that, else gap. **Квас** = kvass only.
- **Вода / минеральная вода** = water / mineral water.
- **Вино красное сухое** = dry red wine; **шампанское** = sparkling wine (any). **Водка** = vodka (or generic 40 % spirit).
  **Коньяк** = brandy/cognac. **Светлое пиво** = lager/pale beer.
- **Масло подсолнечное / оливковое** = that oil. **Майонез** = full-fat mayonnaise (light/reduced-fat only if named).
- **Хрен** = prepared horseradish or raw root. **Аджика / ткемали / кабачковая икра / баклажанная икра**: only that
  product (for баклажанная икра, cooked eggplant spread / baba ganoush-type counts), else gap.
- **Протеин** = whey protein powder.

Generic words in this set (cap ~3 %): сыр, колбаса, шоколад, конфеты, печенье, торт, мороженое, пицца, роллы,
суши, йогурт, сливки. Pick the most typical form and say so in `why`.

## kcal reference (fix 4)

The pool line shows `kcal [src]`: the product's merged kcal and the table it came from. `best` must be a
candidate whose kcal source is the cited record's own table (`fdc` for an FDC record, `recipe` for a recipe)
— otherwise the number belongs to another table's record. If the most precise record shows another table's
kcal, choose the best acceptable record whose kcal source equals its own source.

- **Missing canonical record**: when the pool has acceptable candidates but plainly lacks an obvious canonical
  record, you MAY run one `gather.py try` to find it and add it by record id. Put the phrasings in `tried`.

## Additions after the first labelling pass

- **Nuts and seeds** (орехи, арахис, фисташки, кешью, фундук, миндаль, кунжут, семечки): Russians buy them roasted
  as often as raw (фисташки and арахис mostly roasted and salted). A plain query accepts raw AND roasted (dry or oil,
  salted or not); butters/pastes, coated, honey or flavoured nuts are different foods.
- **Shape-only differences in plain pasta** (спагетти, вермишель vs generic wheat pasta) count as the same food when
  no shape-specific record exists.
- **Котлеты куриные**: minced poultry rissoles/patties (not breaded) count.
