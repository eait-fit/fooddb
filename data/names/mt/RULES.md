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
