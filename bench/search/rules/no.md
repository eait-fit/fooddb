# Labelling rules for the NO search bench

Same method and output as the DE pilot (`/home/kirill/.cache/bench-de/RULES.md`): everything there holds
unless this file says otherwise. Read that file first; this one adds the Norwegian conventions.

Input: `batches/bK.txt`, one block per query: `## <i> | <q> | en: ... | head: ... | plain: ... | cat: ...`, then
the pool, one line per product: `cK  <source>  <record ids>  <kcal/100 g>  <name>`, sorted by source then name
(Matvaretabellen first), not by rank. Names are English. A Matvaretabellen record also shows its Norwegian name
`{nb: ...}` and, when the product's kcal is not that record's own, `[own kcal N]`.
Output: `labels/bK.jsonl`, one object per query, in input order, every query present:

    {"i": 12, "q": "lompe", "accept": ["c3", "c7"], "best": "c3", "why": "bread: potato lompe, bought"}
    {"i": 40, "q": "X", "accept": [], "best": null, "gap": true, "tried": ["alt 1", "alt 2"], "why": "veg: searched ..."}

Retries for gaps (one at a time, nothing else hits the API):

    cd /home/kirill/.herdr/worktrees/fooddb/bench-6k && set -a; . ~/.config/fooddb/bench.env; set +a; \
      TMPDIR=/home/kirill/.cache/tmp-gate uv run python /home/kirill/.cache/bench-no/gather.py try "alt 1" "alt 2"

Never print or echo the API key; only that command, no other HTTP calls.

## kcal reference (`best`)

- `best` is a Matvaretabellen record whenever one is acceptable (the national table, NLOD). Another table only
  when Matvaretabellen has nothing acceptable: then the best generic core record (fdc SR Legacy/Foundation,
  frida, fineli, cofid, ciqual, bls), never a branded record unless nothing generic is acceptable anywhere.
- The kcal is the CITED record's own: for Matvaretabellen it comes from the table's own dataset (`mvt_own.json`,
  shown as `[own kcal N]` when the product carries another value), so any acceptable Matvaretabellen record may
  be `best`. A product that merges several Matvaretabellen records is cited with all of them.
- Form of `best` as in the pilot: raw/as-bought for an unprepared query; the named preparation for a prepared
  one; as eaten for foods only eaten prepared (lompe, kjøttkaker, ribbe, eggerøre, pommes frites, grøt).

## Norwegian conventions for ambiguous words

Decided by how people in Norway eat and log it.

- kaviar = the tube spread of smoked cod roe (Kalles-type, "Kaviar, av torskerogn"); not sturgeon caviar,
  not lumpfish/capelin roe as a separate food. torskerogn = the roe itself (raw/boiled, canned ok).
- tunfisk = canned tuna, drained, in water or oil; "tunfisk i vann" = in water only. makrell i tomat = the
  canned fillets in tomato sauce. sardiner = canned. Plain fresh fish (torsk, sei, hyse, laks, ørret...):
  raw and plainly cooked (boiled, baked, fried without coating); not breaded, not in a dish, not smoked/salted.
- reker = shrimp (Norwegians buy them cooked in shell): cooked and raw shrimp both accepted; best = cooked.
- klippfisk = salted dried cod, dry or soaked; tørrfisk = unsalted dried cod; lutefisk = lye-soaked cod,
  soaked or boiled.
- kjøttdeig = beef mince (the Norwegian default; pork/blend only when named); karbonadedeig = lean beef mince
  (≤ 5 % fat). Raw and plainly fried both accepted.
- kjøttkaker = Norwegian fried meat cakes (beef), as eaten; "i brun saus" = with gravy (combined record), else
  a gap — not the cakes alone. kjøttboller = meatballs (any common recipe).
- pølse (generic) = the Norwegian emulsion sausage: grill/wiener/frankfurter type, pork/beef; not salami, not
  cured. best = grillpølse. skinke = cured cooked ham cold cut (kokt/røkt); spekeskinke is a different food.
- ribbe = Christmas pork belly with rind, roasted (raw belly also accepted). pinnekjøtt = salted dried lamb ribs,
  raw-cured or steamed. fenalår = cured dried leg of lamb.
- geitost = brown whey cheese with goat milk (ekte geitost AND the cow/goat Gudbrandsdal type, which Norwegians
  call geitost too). mysost = brown whey cheese of cow milk (fløtemysost). brunost (existing) = any brown cheese.
  prim = the soft whey spread (prim, prim lett both ok). gulost = hard yellow cheese (Norvegia, Jarlsberg,
  Gouda type). lettost = reduced-fat hard cheese.
- rømme = any plain sour cream; best = seterrømme 35 % (the classic). lettrømme = 18 % (or lighter) only;
  seterrømme = 35 % only.
- kesam/kvarg = quark (1 % and 7 % both accepted for kvarg; kesam = Kesam records, any fat).
- saft / solbærsaft = the drink as poured, diluted ("drikkeklar"); the undiluted concentrate is not the same
  state. juice (generic) = orange juice. eplemost = cloudy apple juice (apple juice accepted).
- kakao = hot cocoa made with milk, the drink; not cocoa powder. kaffe/te plain = infusion, nothing added.
- brus = sugar-sweetened soft drink (any flavour, cola included); cola = regular cola; sukkerfri brus = sugar-free.
- kålrabi = kålrot, the swede/rutabaga (Norwegian usage; the table's own name is "Kålrot, kålrabi"), NOT the
  German kohlrabi. surkål = the Norwegian cooked sweet-sour cabbage; fermented sauerkraut is a different food.
- paprika = fresh sweet pepper (any colour), not the spice. chili = fresh chili pepper, not the dish or powder.
- salat = lettuce leaves raw (any lettuce), not a mixed salad dish. sopp = mushrooms raw (champignon is the
  default).
- mais = sweet corn kernels: raw, frozen, boiled and canned all accepted (Norwegians buy it canned or frozen);
  best = canned. mais på boks = canned only. maiskolbe = sweet corn on the cob, boiled or raw.
- melon = sweet melon (honeydew/cantaloupe/galia), not watermelon. kirsebær = sweet or sour cherries raw;
  moreller = sweet cherries only.
- dadler = dried dates (fresh also accepted). rosiner, svisker, tørkede aprikoser = dried. Frozen unsweetened
  fruit/veg = same state as raw.
- Nuts: plain query = raw or roasted, salted or not; not honey-roasted, chocolate-coated, nut butter.
  best = raw for mandler, valnøtter, hasselnøtter; roasted salted for peanøtter, cashew, pistasj, nøtteblanding.
- grøt (generic) = oat or rice porridge; best = havregrøt (the everyday one). havregrøt = with water or milk;
  risgrøt = with milk.
- pannekaker = Norwegian thin pancakes, plain. vafler = Norwegian waffles, plain. sveler = sveler.
- taco = the Norwegian Friday taco (tortilla/shell with minced-meat filling); any meat taco record.
- pizza = generic pizza (any everyday topping, frozen pizza ok) — generic word, best = the table's pizza.
- toast = toasted ham-and-cheese sandwich. kebab = döner kebab served in pita/bread (meat alone not accepted).
- pølse i brød / pølse med lompe: a combined record only, else a gap (pilot rule 5).
- Generic words (ost, brød, kake, kjeks, sjokolade, iskrem, smågodt, grøt, pizza, juice): accept the everyday
  forms named in `why`; best = sjokolade → milk chocolate; iskrem → vanilla cream ice; kjeks → plain sweet biscuit;
  kake → plain sponge/pound cake; smågodt → mixed sweets/wine gums.
- Alcohol: the type named; a generic spirit 40 % record is accepted for vodka/gin/akevitt/whisky only when the
  pool has no record of that type. gløgg = mulled wine (with alcohol); non-alcoholic gløgg not accepted.
  lettøl = Norwegian light beer (≤ 2.5 % ABV); alkoholfritt øl = ≤ 0.7 %.
- English queries (salmon, whole milk) behave like their Norwegian equivalent.
