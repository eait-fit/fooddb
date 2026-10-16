# Labelling rules for the US search bench

Same method and output as the DE pilot (`/home/kirill/.cache/bench-de/RULES.md`): everything there holds
unless this file says otherwise. Read that file first; this one adds the US conventions.

Input: `batches/bK.txt`, one block per query: `## <i> | <q> | alt: ... | head: ... | cat: ...`, then the pool,
one line per product: `cK  <source>  <record ids>  <kcal/100 g>  <name>`, sorted by source then name, not rank.
Output: `labels/bK.jsonl`, one object per query, in input order, every query present:

    {"i": 12, "q": "bagel", "accept": ["c3", "c7"], "best": "c3", "why": "bread: plain bagel"}
    {"i": 40, "q": "X", "accept": [], "best": null, "gap": true, "tried": ["alt 1", "alt 2"], "why": "veg: searched ..."}

Retries for gaps (one at a time, nothing else hits the API):

    cd /home/kirill/.herdr/worktrees/fooddb/bench-6k && set -a; . ~/.config/fooddb/bench.env; set +a; \
      TMPDIR=/home/kirill/.cache/tmp-gate uv run python /home/kirill/.cache/bench-us/gather.py try "alt 1" "alt 2"

## kcal reference (`best`)

- `best` is a USDA FDC record whenever one is acceptable: SR Legacy, Foundation or FNDDS (generic names,
  "Beef, ground, ...", "Bread, white, ..."), never a branded record (UPPER-CASE brand names, "ACME, ...").
  Among generic FDC records prefer SR Legacy / Foundation for single foods and FNDDS for mixed dishes
  (FNDDS is what the US actually eats as dishes). Another table only when FDC has nothing acceptable.
- The kcal must be the cited record's own: assemble refuses a `best` whose product took its kcal from another
  source. If it refuses, pick another acceptable record as `best`. A product holding several FDC records
  (SR Legacy + Foundation of one food) is cited with all of them (`USDA FDC 172234/326698 ...`).
- Branded `best` only when no generic record in ANY table is acceptable (decided after labelling: peanut
  butter cups, rice crispy treats, protein shake, protein bar, chicken burrito, egg and cheese sandwich).
- Form of `best`: as in the pilot (raw/as-bought for an unprepared query; the named preparation for a prepared
  one; as eaten for foods only eaten prepared), with these US exceptions, which follow the 23 existing US cases:
  rice, pasta, noodles, quinoa, couscous, barley, grits: COOKED (Americans log cooked cups);
  oats and cold cereal: DRY (logged by the dry measure); legumes: cooked/canned-drained.

## Acceptance (same food, same state)

- Branded FDC records are acceptable when they are plainly the same food with nothing added (plain frozen peas,
  plain whole milk). Flavoured, filled, "with sauce" branded records are not.
- Meat, fish, potatoes, cooking vegetables, grains, legumes, plain query: raw/dry AND plainly cooked (boiled,
  baked, roasted, grilled, broiled, pan-fried without coating). Not breaded, battered, in sauce, or a dish.
- Any cut/variety of the named food, any fat level unless the query names one ("lean ground beef" = 90 % lean
  or leaner; "93% lean" = 93/7 only; "nonfat"/"low fat"/"2%" bind).

## US conventions for ambiguous words

- tuna = canned tuna (light or white, water or oil, drained); fresh/frozen tuna is "tuna steak".
- canned salmon / sardines = canned; smoked salmon = lox/smoked, any species.
- sweet corn = kernels raw or boiled (not canned, not creamed); canned corn = canned; corn on the cob = cooked
  sweet corn (on or off the cob, boiled), not raw.
- dates = dried dates (how they are sold in the US: Deglet Noor, Medjool); medjool dates = Medjool only.
- raisins, prunes, dried cranberries/apricots/mango = dried; the fresh fruit is a different food.
- nuts: plain nut query accepts raw, dry-roasted and oil-roasted, salted or not; not honey-roasted, candied,
  chocolate-covered, or nut butter. best = raw for almonds, walnuts, pecans; dry roasted for peanuts,
  cashews, pistachios, mixed nuts (how they are sold).
- sweetened condensed milk ≠ evaporated milk.
- biscuit = the American quick-bread biscuit, not a cookie/British biscuit.
- chips = potato chips; tortilla chips are their own query. fries/french fries = as eaten (fried, oven-heated,
  fast food), not frozen uncooked.
- jelly = fruit jelly (spread); jello = gelatin dessert.
- soda / cola = regular, sugar-sweetened cola; diet soda = sugar-free cola only.
- coffee/tea/espresso/cold brew = plain brewed (no milk, no sugar). sweet tea = sweetened iced black tea.
  iced tea = unsweetened brewed tea (sweet tea is the separate query).
- latte/cappuccino = with milk (whole milk when the fat is unstated), unsweetened.
- bacon = pork bacon, cooked (as eaten); raw bacon not accepted. turkey bacon likewise cooked.
- ham = cured ham (sliced, roasted, deli), not fresh pork leg. deli turkey = sliced luncheon turkey breast.
- turkey = roasted turkey meat (Thanksgiving); raw turkey meat also acceptable, not deli, not ground.
- hot dog = the frankfurter (beef, pork or mixed), without bun. hamburger/cheeseburger = the sandwich with bun,
  single patty, any toppings; not the patty alone.
- steak (generic) = a grilled/broiled or raw beef steak cut (sirloin, ribeye, strip, T-bone, flank...);
  best = top sirloin.
- burrito (generic) = burrito with meat (and usually beans); a bean-only burrito is "bean burrito".
- tacos = beef taco (hard or soft); chili = chili con carne with beans.
- pancakes/waffles/french toast = plain, prepared, without syrup.
- gravy = brown/beef/turkey/chicken gravy, not sausage/cream gravy (that is "biscuits and gravy").
- hot sauce = vinegar-based hot pepper sauce (Louisiana style), not sriracha, not buffalo wing sauce.
- mayo/mayonnaise = regular, not light. ranch/italian dressing = regular, not fat-free/light.
- vegetable oil = soybean, canola, corn, or "vegetable oil" blend; not olive, not coconut.
- generic words (cheese, ice cream, steak, soda, pudding, donut, smoothie): accept the everyday forms named in
  `why`; best = the most typical (cheese → cheddar; ice cream → vanilla; pudding → vanilla or chocolate
  ready-to-eat; donut → cake or yeast, plain/glazed; smoothie → fruit smoothie).
