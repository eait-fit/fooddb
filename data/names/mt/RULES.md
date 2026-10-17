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

## FNDDS qualifiers (batch 2c)

Snacks, breakfast starches, pasta/rice dishes, Mexican plate matrix, fruit.

- crackers → `крекеры` / `galletas saladas` (`galletas` where the corpus already
  uses it); saltine → `солёные крекеры` / `galletas saladas` (`galletas de soda`
  when it must split from a sibling); woven wheat → `плетёные` / `trenzadas`;
  water cracker → `пресные` / `de agua`; oyster cracker → `сухие крекеры к супу`
  / `galletas pequeñas para sopa`; sandwich crackers → `крекеры-сэндвичи` /
  `galletas sándwich`.
- popcorn: `air-popped` → `воздушный` / `al aire`; `popped in oil` →
  `жареный в масле` / `hechas en aceite`; `movie theater` → `кинотеатральный` /
  `de cine`; `microwave` → `для микроволновки` / `para microondas`;
  `ready-to-eat` (bagged) → `готовый` / `envasadas`; `kettle` → `сладкий` /
  `dulces`; `light` → `лёгкий` / `ligeras`.
- pretzels: hard → `крендельки` / `pretzels`; soft → `крендели мягкие` /
  `pretzels blandos`; `from frozen` → `из заморозки` / `de congelado`;
  soft ready-to-eat → `готовые` / `recién hechos`.
- FNDDS cereal codes: `O's` → `колечки овсяные` / `aros de avena`; `K's` →
  `рисово-пшеничные хлопья` / `hojuelas de arroz y trigo`; corn squares →
  `кукурузные подушечки` / `cuadritos de maíz`; corn puffs → `кукурузные шарики`
  / `puffs de maíz`; rice crispy → `воздушный рис` / `arroz inflado`;
  shredded wheat → `подушечки из цельной пшеницы` / `almohadillas de trigo`;
  cinnamon toast → `хлопья корица-тост` / `cereales de canela`.
- hot cereal: grits → `кукурузная каша` / `gachas de maíz`; cornmeal mush →
  `мамалыга` / `polenta`; cream of wheat → `манная каша` / `gachas de sémola`;
  oatmeal → `овсянка` / `gachas de avena`; `non-dairy milk` →
  `растительное молоко` / `bebida vegetal`; `instant` → `быстрого приготовления`
  / `instantáneas`.
- pancakes → `оладьи` / `tortitas`; waffle → `вафли` / `gofres`; french toast →
  `французские тосты` / `torrijas` (sticks → `палочки` / `bastones`); crepe →
  `блины` / `crepes`.
- provenance/state suffixes: `restaurant` → `из ресторана` / `de restaurante`;
  `fast food / restaurant` → `(фастфуд)` / `de fast food`; `school` →
  `из школьной столовой` / `de comedor escolar`; `home recipe`/`from fresh` →
  `домашняя` / `casera`; `ready-to-heat` → `готовая к разогреву`, `полуфабрикат`
  where shorter / `lista para calentar`, `precocinado`; `diet frozen meal` →
  `диетическое замороженное блюдо` / `comida dietética congelada`;
  `packaged/dry mix` → `из готовой/сухой смеси` / `de preparado`.
- pizza crust: thin/medium/thick → `на тонком/среднем/толстом тесте` /
  `de masa fina/media/gruesa`; stuffed crust → `с сырным бортиком` /
  `con borde relleno`; whole wheat → `цельнозерновой` / `integral`;
  `from frozen` → `замороженная` / `congelada`.
- Mexican plate matrix: `с`/`con` per component (`тако кукурузный с говядиной` /
  `taco de maíz de vacuno`); burrito bowl → `боул буррито` / `bol de burrito`;
  taco salad → `салат тако` / `ensalada taco`; Puerto Rican dishes keep their
  words (`sorullitos`, `bacalaítos`, `asopao`, `hayacas`) with
  `по-пуэрторикански` / `puertorriqueño` where the source only says the style.
- pasta dishes: sauce → `в томатном/сливочном соусе` / `con salsa de
  tomate/nata`; stuffed shells → `фаршированные ракушки` / `conchas rellenas`;
  egg roll → `эг-ролл` / `rollito de primavera` (fresh rice-paper roll →
  `спринг-ролл свежий` / `rollito de primavera fresco`); turnover/hot pocket →
  `слоёный пирожок` / `empanadilla` (empanada stays `empanada`).
- fruit: applesauce → `яблочное пюре` / `compota de manzana`; fruit salad →
  `фруктовый салат` / `macedonia`; fruit cocktail → `фруктовый коктейль` /
  `macedonia en conserva`; baby food → `детское пюре` / `potito` (`Stage N` →
  `ступень N` / `etapa N`); baby juice → `детский сок` / `zumo infantil`;
  dried currants → `коринка` / `pasas de Corinto`; dried apricots →
  `курага` / `orejones`; ice pop → `фруктовый лёд` / `polo`; sushi roll →
  `ролл` / `maki`; nigiri-style `topped with` → `суши с` / `nigiri de`.
- potato: hash brown → `хэшбраун` / `tortitas de patata fritas`; tater tots →
  `картофельные тоты` / `croquetas de patata`; potato skins →
  `картофельные лодочки` / `barcas de patata`; scalloped → `картофельный гратен`
  / `patatas gratinadas`; home fries → `картофель по-домашнему` /
  `patatas fritas en dados`; es splits `patatas fritas` (fries) from
  `patatas fritas de bolsa` (chips); `peel eaten/not eaten` →
  `с кожурой` / `без кожуры` → `con piel` / `sin piel`.
- NFS/plain twin rows: when `NFS` and `plain` collapse to one name, plain takes
  `классические` / `clásicas` (`попкорн для микроволновки` vs `... классический`);
  a fully generic NFS may take a bare synonym (`фри`, `пюре картофельное`,
  `puré de patatas`, `канталупа`/`cantalupo` when `дыня канталупа` collided).
- Cross-batch collisions fixed by giving the record that OWNS the qualifier its
  qualifier back (1b rule): `fdc:167549` oil-popped → `на масле` / `en aceite`,
  `fdc:169035` restaurant → `из ресторана` / `de restaurante`, `fdc:170291`
  fast food → `(фастфуд)` / `de fast food`.
