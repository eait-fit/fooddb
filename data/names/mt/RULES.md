# Rules for agent-written names (`data/names/mt/*.tsv`)

The name a speaker of the language would TYPE into a food diary — not a word-for-word
rendering of the table's name. Three tab-separated fields: `record_id`, the record's own
name (reader context only; ja/zh for mext/tfda, ru for `recipe:*.ru`), the translation.

## Keep

- **Cooking/state words that change the numbers**: raw, boiled, fried, baked, canned,
  dried, smoked, pickled.
- **"fried without fat"** — it is a different dish for kcal: `жареный без масла`,
  `a la plancha` / `al horno`. Never a bare `жареный` / `frito`.
- **Any qualifier that moves fat or sugar**: lean/fat, with/without skin, syrup vs juice
  pack, reduced-fat, whole vs skim milk, dry vs cooked for pulses and grains.
- `cured` is `солёный` / `curado` — never `вяленый` (dried) or `crudo` (raw).
- **Brands stay as is** (Latin script: `Nasoya`, `Carrabba's`); a dish gets its common
  local name (`Beef stroganoff` → `бефстроганов`).

## Drop

- Table clutter: NFS, grades, trim percentages, "with added solution", pack sizes,
  sampling notes (`(11月取樣)`).
- **`frozen`/`deep-frozen` once a cooking state is given** — freezing does not change
  the served kcal.

## es is Spain usage

`ternera`/`vacuno` not `res`, `patata` not `papa`, `alubia`/`judía` not `frijol`,
`desnatada` not `descremada`, `en conserva` not `enlatado`, `gamba` not `camarón`,
`beicon`/`tocino` per Spain, `bonito`/`caballa` over LatAm fish names.

### es qualifiers that must survive (each splits kcal >10%)

- trim `0"` vs `1/8"`/etc → keep as `sin grasa visible` vs `grasa 1/8"`.
- grade `choice`/`select`/`prime` → keep `(choice)`/`(select)`/`(prime)` when a
  sibling record differs only by it.
- `drained` → `escurrido`; `with added solution` / `pre-basted` → `con salmuera`
  everywhere (not dropped, not `con agua de`).
- `bone-in` vs `boneless` → `con hueso` / `sin hueso`; `steak` vs `roast` →
  `filete` / `asado`; `flat half` vs `point half` vs `whole` → `parte plana` /
  `parte gruesa` / `entero`; cut sub-name (`chuck eye`, `top blade`, `under
  blade`, `Denver cut`, `mock tender`, `country-style`) must stay identifiable.

### es fixed vocabulary

- drumstick = `muslo`/`jamoncito`; thigh = `contramuslo` (one word).
- sirloin = `lomo`/`entrecot`/`chuletón`, never `solomillo` (= tenderloin).
- brisket = `pecho`; `falda` is flank/skirt only. ribeye = `entrecot`;
  T-bone (bone-in) = `chuletón` (`filete` implies boneless).
- beef shank = `morcillo`/`jarrete`, never `rodaballo` (turbot).
- kale = `col kale`; savoy cabbage = `col de Saboya`; never conflate.
- pumpkin = `calabaza`; winter squash = `calabaza de invierno`.
- rutabaga = `colinabo`; kohlrabi = `colirábano` — they differ.
- welsh onion = `cebolleta de invierno`; fruit leather = `piel de fruta`;
  popcorn, air-popped = `palomitas al aire`; popcorn chicken =
  `trocitos de pollo frito`; pork skins/rinds = `cortezas de cerdo`;
  cheeseburger = `hamburguesa con queso`; french dressing = `salsa francesa`;
  trail mix = `mezcla de frutos secos`; pattypan/scallop squash = `patissón`;
  green soybeans = `edamame`; Alaska devilfish = `pulpo` (octopus);
  lingcod keep as `lingcod`; cured dried beef = `cecina de vacuno`.
- Word order: `jamón con agua añadida`, not `con agua de`.

## ru qualifiers that must survive (each splits kcal >10%)

- trim `0"` vs `1/8"` → `без внешнего жира` / `жир 1/8"`; grade tag stays
  `(чойс)`/`(селект)`/`(прайм)` when it is the only difference.
- `drained` → `слитые`; `with added solution`/`pre-basted` → `с рассолом`.
- `bone-in`/`boneless`, `steak`/`roast`, `flat`/`point`/`whole` halves and cut
  sub-names (`верхняя лопатка`, `нижняя лопатка`, `шейная часть`, `мок-тендер`,
  `Денвер`, `кантри-стайл`) must stay identifiable.

## Glossary traps seen in review

- compote / Kompott = stewed fruit (`тушёные фрукты`, `compota`), never `компот` (the drink)
- sweet cherry = `черешня`, not `вишня`
- drumstick (poultry) = `голень`, not `окорочок`
- nut (generic) = `орехи` / `frutos secos`, never `nueces` (walnuts)
- mixed nuts = `frutos secos`
- No calques of source jargon: `мирепуа` → `суповые овощи`, `печенье шприц` →
  `песочное печенье`. If the foreign word is not in the receiving language's dictionary,
  describe the thing.

## FNDDS qualifiers (batch 2)

- `skin eaten` / `skin not eaten` → `с кожей` / `без кожи`, `con piel` / `sin piel`.
- `fried, coated, skin / coating eaten` → `в панировке с кожей`; `not eaten` →
  `в панировке, без кожи`; `prepared skinless, coating eaten` puts `без кожи`
  BEFORE `в панировке` (word order keeps the two skinless cases apart).
- provenance splits kcal and stays: `from raw` → `(из сырой)` / `desde crudo`,
  `from pre-cooked` → `(из готовой)` / `precocinado`, `from fast food /
  restaurant` → `(фастфуд)` / `de fast food`, `de restaurante`.
- `rotisserie` → `на вертеле` / `al espetón` (never `на гриле`/`a la parrilla`).
- `baked, broiled, or roasted` → `запечённый` / `al horno`; `stewed` →
  `тушёный` / `estofado`; `sauteed` → `обжаренный` / `salteado`.
- `NFS`, `NS as to …` and the water kind of powdered formula are dropped.
- `including/excluding carrots, broccoli, and/or dark-green leafy` →
  `с морковью и брокколи` / `без моркови и брокколи`,
  `con zanahoria y brócoli` / `sin zanahoria ni brócoli` (in every combo dish).
- `infant formula` → `детская смесь` / `leche de fórmula`; ready-to-feed →
  `готовая` / `líquida`; powder → `из порошка` / `en polvo` (the file's
  written form — powdered milk already uses `en polvo`).
- `light` (dairy, dips, ice cream) → `лёгкий`/`нежирный` / `ligero`/`light`;
  `reduced fat` → `нежирный` / `bajo en grasa`; `nonfat, fat free` →
  `обезжиренный` / `desnatado`, `sin grasa`.
- US `2 %` milk → `молоко 2 %` / `leche semidesnatada`; `1 %` keeps the number.
- `reduced sodium` → `с пониженной солью` / `bajo en sodio`.
- luncheon meat → `варёная колбаса` / `fiambre`; ice cream bar → `эскимо` /
  `barrita de helado` (`polo` = ice pop: Creamsicle, Fudgesicle); pudding →
  `пудинг` / `natillas`; `gravy` → `подливка` / `gravy`.
- Cross-source name collisions with >10 % kcal split are resolved by a
  translated qualifier on the record that owns the qualifier (`неподогретая`,
  `en conserva`, `de restaurante`, `de Jersey`) — never an English suffix.

## Process

- One line per record per language; sorted by `record_id`.
- `load_mt` is idempotent: a line removed drops its `food_name` row.
- `tests/test_db.py::test_no_two_records_share_an_mt_name_with_different_kcal` guards the
  class of error where two nutritionally different records collapse to one name.
- meatloaf = `мясной хлеб`, never `хлебом` (bread); breadnut-tree seeds =
  `семена рамона`, breadfruit seeds = `семена хлебного дерева` — different trees.
- welsh onion = `лук-батун`; cornsalad = `полевой салат`/`рапунцель` (маш-салат
  collides with mung `маш`); Alaska devilfish = `осьминог`.
- `бостонские стейки`/`кантри-стайл`/`самобастед`/`сливки-халф-энд-халф` read as
  calques: Boston butt = `свиная шея`/`плечевая часть`, country-style ribs =
  `рёбра по-деревенски`, pre-basted = `с рассолом`, half-and-half =
  `сливки полужирные`, granulated sugar = `сахар-песок`→`сахар`, kasha buckwheat
  raw ≠ `гречка жареная сырая`.
- es: `cuero de fruta`, `frijoles`, `palomitas de pollo`, `vinagreta casera`
  (french dressing), `coctel` are LatAm/calque/wrong-accent — see the es
  vocabulary list above.

## Batch 1b additions (PR #126 review)

- **Never a source tag as a qualifier** — no `Foundation`, `USDA`, `NFS`,
  `Frida`, `(tabla nueva)`, `(новая таблица)`, `(США)`, `(EE. UU.)` on the
  translated name. When two records of the same food differ only in kcal and
  collapse to one name, disambiguate with a real qualifier from the source
  name (`минтай сырой (Аляска)` when only the sibling says Alaska) or a natural
  synonym/word-order variant (`соевая мука обезжиренная` vs `мука соевая
  обезжиренная`, `копчёная пикша`, `свежая клубника`, `ahumado de eglefino`,
  `yogur natural de leche entera`).
- **Grade-split sibling groups**: when `choice`/`select`/`prime` tags separate
  siblings, tag ALL of them — `(все категории)`/`(todas)` included.
- US biscuit (the quick bread) = `бисквит(-скон)` / `panecillo de soda` —
  never `bizcocho`/`biscotes` (sponge cake).
- english muffin = `английские маффины` / `muffins ingleses`; american muffin =
  `маффины` / `magdalenas`; american pancakes = `оладьи` / `tortitas`
  (`панкейки` ok on branded items; `блины` is crepes).
- lamb rack = `каре` / `costillar`/`carré` — never `корейка` (that is loin);
  `frenched` is absorbed into `каре`; `denuded` = `зачищенное`; frenched chop =
  `с зачищенной косточкой`.
- lamb shoulder arm = `плечевая часть` (never `рулет` unless netted/rolled);
  lamb flap = `пашина` (never `брюшина`); lamb chump = `огузок`;
  seam/intermuscular fat = `прослойка жира` / `grasa intermuscular`.
- brisket = `грудинка` / `pecho`; point end = `толстая часть` /
  `punta de pecho`; navel end = `брюшная часть` / `extremo naval`;
  `falda` is flank/skirt only.
- stewed fruit: ru = `тушёные` (`припущенные` only for poached fish),
  es = `en compota`; sulfured stays `сернистые`/`sulfitados`.
- species as genitive after the part: `грудка перепела`, `pechuga de codorniz`.
- `proof` → % alcohol: 100 = 50%, 94 = 47%, 86 = 43%, 80 = 40%.
- buttermilk = `на пахте` / `suero de mantequilla` — never `пахтаночный`,
  never `suero de leche`.
- generic `honey nut` = `мёд-орехи` / `frutos secos` (`nueces` = walnuts only).
- veal shank fore+hind = `передняя и задняя` / `morcillo delantero y trasero`.
- Lebanon bologna = `колбаса Лебанон` / `mortadela Lebanon` — Lebanon PA,
  not the country.
- Fish/seafood vocabulary (ru / es): herring = `сельдь`/`arenque`;
  turbot = `калкан`/`rodaballo`; seatrout = `корвина`/`corvina`;
  freshwater drum = `горбыль`; monkfish = `удильщик`/`rape`;
  tilefish = `тайлфиш`/`blanquillo`; Pacific rockfish =
  `окунь тихоокеанский`/`gallineta`; whiting = `мерланг`/`pescadilla`;
  whitefish = `сиг`/`pescado blanco`; yellowtail = `лацеда`/`serviola`;
  ling = `мольва`/`maruca`; lingcod = `линкод`/`lingcod`; ocean pout =
  `тресковый бычок`/`faneca`; freshwater perch = `окунь речной`/`perca de río`;
  freshwater bass = `окунь пресноводный`/`lobina`; channel catfish =
  `сом канальный`/`bagre de canal`; milkfish = `чанос`/`sabalote`;
  shad = `сельдь-алоза`/`sábalo`; cuttlefish = `каракатица`/`sepia`;
  whelk = `морская улитка (велк)`; conch = `морская улитка (стромб)`/`caracola`;
  queen crab (snow crab) = `краб-стригун`/`cangrejo de las nieves`;
  blue crab = `краб голубой`/`cangrejo azul`; Spanish mackerel =
  `скумбрия испанская`/`sierra`; chinook = `чавыча`/`salmón real`;
  chum = `кета`/`salmón keta`; pollock = `минтай`/`abadejo`
  (`сайда` is saithe — a different fish).

## Traps from the batch-2a review

- corned beef = `солонина` (hash, patty, with-potatoes dishes follow);
  the cured-ingredient lines keep `корнед-биф`.
- country fried = `жареный в панировке` / `empanado frito`; pot roast =
  `тушёный` / `estofado`; fresh side pork = `бекон несолёный` (uncured).
- cheese dip ≠ cheese sauce: dip → `сырный соус-дип` / `salsa de queso
  para mojar` so it does not collide with `сырный соус` / `salsa de queso`.
- shellfish = `морепродукты` (crustaceans included), not `моллюски`;
  clams = `вонголе`; guisada dish = `тушёный (гуисада)` / `guisado` —
  the es adjective agrees (`vacuno/cerdo guisado`).
- chipped (dried beef) = `ломтиками`, never `стружка` (wood shavings);
  liver paste/pate = `печёночный паштет`; frankfurter = `сосиска для
  хот-догов`; reconstituted (milk) = `восстановленное`; welsh rarebit =
  `гренки с сырным соусом`; licuado = `молочно-фруктовый коктейль`;
  gefilte fish = `гефилте фиш`; watercress = `кресс водяной`;
  cordon bleu = `кордон блю`.
- es: `buey` is ox, never a beef-food word (`ternera`/`vacuno`); whiting =
  `pescadilla`, not `merlán`; escargot = `caracoles`; custard = `crema
  inglesa` (`crema pastelera` is thicker pastry cream); dumplings =
  `bolitas de masa`; hot chocolate = `chocolate a la taza`; light cream =
  `nata para cocinar`; starchy vegetables = `tubérculos`; ready-to-eat =
  `listo para consumir`; thuringer = `salchicha de Turingia`; Salisbury
  steak is a patty → `hamburguesa Salisbury`; wild fauna → `silvestre`;
  porcupine balls = `albóndigas con arroz "puerco espín"` (rice quills,
  not porcupine meat); scallopini = `escalopes de ternera`.
- Do not invent fat qualifiers the source lacks: cottage cheese with
  vegetables is `творог с овощами` / `requesón con verduras` — the lowfat
  sibling is a different record.

## FNDDS qualifiers (batch 2b)

Following the batch-2 section (PR #127): same mixed-dish qualifiers. New here:

- Sandwich bread: `on white bun`/`on wheat bun` → `на белой/пшеничной булочке` /
  `en pan blanco`/`en pan de trigo` for burgers and sloppy joes; `on white/wheat
  bread` → `на белом/пшеничном хлебе` / `en pan blanco`/`en pan de trigo` for
  sliced-bread sandwiches. Where a record family offers BOTH bun and bread
  (hot dogs), the bun becomes `panecillo` to keep the names apart.
- `sandwich or sub, restaurant` → `(ресторан)` / `de restaurante`;
  `from school cafeteria` → `из школьной столовой` / `de comedor escolar`.
- patty size `1 small/medium/large` → `маленькая/средняя/большая котлета` /
  `pequeña`/`mediana`/`grande`; `slider` → `мини-` / `mini`.
- Omelet matrix: `made with margarine/oil/butter/animal fat/cooking spray` →
  `на маргарине/масле/сливочном масле/животном жире/с кулинарным спреем`,
  `en margarina/aceite/mantequilla/grasa animal/con spray de cocinar`;
  `no added fat` → `без масла` / `sin grasa`. `dark-green vegetables` →
  `зелёные овощи` / `verduras verdes` (never `зелень` — that is herbs).
- Beans `from dried` / `from canned` → `из сухой` / `консервированная`,
  `de secas` / `en conserva`; `fat added` / `no added fat` →
  `с жиром` / `без масла`, `con grasa` / `sin grasa`. When the FNDDS
  record is the cooked dish and a canned sibling exists, add `cocidas`.
- `Pie` vs `Cake` vs `Cheesecake` must not collapse in es: pie → `tarta`/`pastel`,
  cake → `tarta`/`bizcocho`, cheesecake → `tarta de queso`; if two still share a
  name, split with a real qualifier (`americana`, `sencilla`).
- Fast-food/dessert vocabulary: `biscuit` (US) → `бисквит`/`panecillo de soda`
  (collided with sponge `бисквит` → `бисквит-скон`); `croutons` → `гриссини`-only
  for the soft kind; `crisp`/`cobbler` stay Latin-ish (`крисп`/`коблер`,
  `crisp`/`cobbler`); `breadsticks` soft = `хлебные палочки`/`palitos de pan`,
  hard = `гриссини`-family/`picos de pan`.
- `trail mix` → `микс орехов и сухофруктов` / `mezcla de frutos secos (y fruta)`.
- Brands and their product names stay Latin: `Whopper`, `Big Mac`, `McDouble`,
  `Quarter Pounder`, `Nutella`, `Spam`, `Pocky`, cereal/nutrition-bar brands
  (`Nature Valley`, `Quaker`, `Clif`, `PowerBar`, …) — `McDonald's` spelled out.

## FNDDS qualifiers (batch 2d)

Cooked-vegetable form matrix, coffee/tea/soft drinks, alcohol, candy, baby food,
ingredient rows.

- Cooked-veg form matrix: `fresh, cooked` drops `fresh` (the default); `frozen,
  cooked` → `замороженная приготовленная` / `congelada cocida`; `canned, cooked` →
  `консервированная приготовленная` / `en conserva cocida`; `NS as to form` keeps
  the bare name. Keep `свежие`/`frescos` only when the bare name would collide
  with an NS row carrying no fat tag (tomatoes).
- `cooked with butter or margarine` → `со сливочным маслом или маргарином` /
  `con mantequilla o margarina` (never shortened to `с маслом` — it would read
  as oil).
- FNDDS ingredient rows (`as ingredient`, `for use with/on`) → `X (ингредиент
  для Y)` / `X (ingrediente para Y)`.
- Coffee: `brewed` → `кофе заварной` / `café de filtro`; `instant` →
  `растворимый` / `instantáneo`, `reconstituted` → `разведённый` / `preparado`
  (dry powder vs made-up drink split kcal, keep both); `frozen` →
  `кофе-фраппе` / `café granizado` (`frozen mocha` → `мокко-фраппе` /
  `granizado de moka`); `iced` → `со льдом` / `con hielo`, `iced latte` →
  `латте со льдом` / `latte frío`; `decaffeinated` → `без кофеина` /
  `descafeinado`; `nonfat` → `обезжиренный` / `desnatado`; `non-dairy milk` →
  `на растительном молоке` / `con bebida vegetal`; `flavored` →
  `ароматизированный` / `con sabor`; `pre-lightened` → `с добавленным молоком` /
  `con leche añadida` (vs `cafe con leche` which keeps `с молоком` /
  `con leche`); `pre-sweetened with sugar` → `с сахаром` / `con azúcar`,
  `with low calorie sweetener` → `с подсластителем` / `con edulcorante`;
  `bottled/canned` → `в бутылке` / `embotellado`.
- Tea: `hot, leaf` drops the brew word (`чай чёрный`/`té negro`); `iced,
  instant` → `чай со льдом растворимый` / `té frío instantáneo`; `iced, brewed`
  → `чай со льдом` / `té frío`; `iced, bottled` → `в бутылке` / `embotellado`;
  `dry` → `порошок` / `en polvo`; `diet` → `диетический` / `light`;
  hibiscus → `каркаде` / `té de hibisco`; kombucha/bubble tea stay
  `комбуча`/`kombucha`, `баббл-ти`/`té de burbujas`.
- Soft drinks: `diet` → `диетическая` / `light` (Spain usage, never `de dieta`
  on cola-family; `de dieta` only where `light` collides); `pepper type` →
  `типа Dr Pepper` / `tipo Dr Pepper`; `caffeine free` → `без кофеина` /
  `sin cafeína`, `caffeine containing` → `с кофеином` / `con cafeína`.
- Juice drinks vs flavor drinks: `juice drink` → `соковый напиток` /
  `bebida de zumo`; `fruit flavored drink` (no juice) → `напиток фруктовый` /
  `bebida de frutas`; `40-50% juice beverage` → `напиток` без `соковый`;
  `powdered` → `из порошка` / `de polvos` (reconstituted) vs `порошок` /
  `en polvo` (not reconstituted); `with high vitamin C` → `с витамином С` /
  `con vitamina C`.
- Alcohol: cocktail names stay the established forms (`мохито`/`mojito`,
  `маргарита`/`margarita`, `пина колада`/`piña colada`, `Cuba libre` for rum and
  cola, `Whisky con cola`); `hard cider` → `сидр`/`sidra`; `hard seltzer` →
  `алкогольный селтцер`/`seltzer con alcohol`; wine `light` → `лёгкое`/`ligero`.
- Candy: `chocolate candy` → `шоколадные конфеты` / `bombones`; `dark` →
  `из тёмного шоколада` / `de chocolate negro`; `hard candy` → `леденцы` /
  `caramelos duros`; `gummy` → `мармеладные конфеты` / `gominolas`;
  `peanut brittle` → `грильяж` / `crocante de cacahuete`; `candy shell` →
  `шоколадные драже` / `grageas`; `licorice` → `лакричные конфеты` / `regaliz`;
  `taffy` → `ириски` / `taffy`; `cotton candy` → `сахарная вата` /
  `algodón de azúcar`; `fruit leather` → `фруктовая пастила` / `piel de fruta`;
  generic `Candy, NFS` → `конфеты` / `golosinas` when `caramelos` is taken.
- Jams/desserts: `jelly` (spread) → `джем-желе` / `jalea` vs `gelatin dessert`
  → `желе` / `gelatina` (different kcal, never one name); `marmalade` →
  `мармелад цитрусовый` / `mermelada de cítricos`; `popsicle`/`freezer pop` →
  `фруктовый лёд` / `polo` (+ `в тюбике`/`de tubo`); `snow cone` →
  `снежный конус` / `cono de nieve`; `Italian ice` → `итальянский лёд` /
  `granizado italiano`; `icing` → `глазурь` / `glaseado`; `topping` →
  `топпинг` / `topping`.
- Nutritional drinks/powders: brand stays Latin inside `питательный напиток X` /
  `bebida nutricional X` and `питательная смесь порошковая X` /
  `mezcla nutricional en polvo X`; `high protein` → `высокобелковый` /
  `alta en proteína`; `sports drink` → `спортивный напиток` / `bebida
  deportiva`; `energy drink` → `энергетический напиток` / `bebida energética`.
- New vocabulary: greens (generic) → `зелень листовая` / `verduras de hoja`;
  collards → `листовая капуста` / `berza`; sweet potato → `батат` / `boniato`
  (`тоты` → `тоты`/`croquetas`, `фри` → `фри`/`frito`); lima beans → `фасоль
  лима` / `judías de Lima`; blackeyed peas → `вигна` / `carillas`; hominy →
  `кукуруза хомини` / `maíz pozolero`; water chestnut → `водяной орех` /
  `castaña de agua`; chayote → `чайот` / `chayote`; nopal cactus → `опунция` /
  `nopal`; Chinese broccoli → `кай-лан` / `kai-lan`; radicchio → `радиккио` /
  `radicchio`; snow peas → `горошек стручковый` / `tirabeques`; Puerto Rican
  dishes → `мофонго`/`mofongo`, `пастелон`/`pastelón`, `пастелес`/`pasteles`,
  `софрито`/`sofrito`; baby food → `детское пюре` / `potito` + `этап N` /
  `etapa N` (`ступень` is mechanical); toddler meal → `детский обед` /
  `comida infantil`.
- Collision lessons: FNDDS vs FDC same-English-name records with >10 % kcal got
  a real qualifier or word-order variant (`бебida de aloe`,
  `café instantáneo preparado con agua` — check the existing forms before
  adding another). When the corpus headword itself is taken but a sibling
  pair needs one name, either keep the headword on both and vary only the
  state word (`ботва свекольная свежая`/`сырая`, `радиккио свежий`/`сырой`,
  `hojas de remolacha crudas`/`frescas`, `col china fresca`, `nabos frescos`,
  `стручковая зелёная фасоль свежая`, `репа свежая`, `brócoli fresco`,
  `champiñones frescos`, `шампиньоны свежие`) or move the whole pair to the
  real second name (`рапини`/`rapini`, `кай-лан`/`brócoli kai-lan`).
  `rum and cola` → `ром с колой` in ru (Cuba libre only in es); cocktails
  take the bare canonical name, `коктейль`/`cóctel` only where the bare name
  is kcal-taken (daiquiri, piña colada).
- More vocabulary: `drippings` → `жир с жаркого` / `grasa de asado` (never
  `вытопки`/`chicharrones` — those are cracklings); generic FNDDS mushrooms →
  `шампиньоны` / `champiñones` (Asian keeps `грибы азиатские` /
  `setas asiáticas`); watercress → `кресс водяной` / `berros`; mixed salad
  greens → `салатный микс`, other `mixed` → `ассорти`; acai blend juice →
  `сок-ассорти с асаи`; es `cooked` → `cocido` always (never `cocinado`);
  powdered-reconstituted drinks → `en polvo` (never `de polvos`); `diet` →
  `light` (`de dieta` only where `light` collides with a sibling row).
