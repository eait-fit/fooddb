# Design

This is the target design. [architecture.md](architecture.md) shows what is built today, with
references to the code. Each section below says what is built and links the issue for the rest.

## The pipeline

```
 1 Open tables ─(on release)─┐
 2 Open Food Facts ─(daily)──┤
 3 Brands / GDSN ─(on push)──┼─► Normalise ─► Observations ─► Checks ─(pass)─► Resolver ─► Nightly snapshot ─► REST · MCP · CLI
 4 Own label reads ─(demand)─┘                                  │                ▲                                   │
         ▲                                                      └─(differs/fails)─► Human review ─(confirmed)┘         │
         └──────────── scan hits a missing or stale row → client asks for a label photo ◄─────────────────────────────┘
```

Every step runs automatically except human review. Review sees only rows that changed or failed a
check (the Robotoff rule from Open Food Facts), about 80 h/month at 1M products.

**Built:** lanes 1 and 2 (FDC Foundation, SR Legacy and Branded, CIQUAL, CoFID, Fineli, Matvaretabellen,
OFF), normalise, observations, checks,
Splink matching (not in the diagram above: it runs between observations and the resolver), the
resolver, the nightly snapshot and its NDJSON export, REST and MCP, and the review queue
(`/v1/review`, two MCP tools, SQLAdmin at `/admin`), API keys with scopes and rate limits, and the
monthly ODbL dump of the OFF layer at `/v1/dumps`, and lane 4: label reads through the model port,
with the photo as evidence and a review page that shows it, and the admin panel (Overview, Jobs, Requests and Users pages, and a request log). The checks run before the insert and set each
value's status. Each merge is logged. A reviewer splits a wrong merge through the API, MCP or
SQLAdmin, and matching never joins the split records again. `fooddb match train` estimates the
Splink weights on the data. **Not built:** a model trained on the full data (the weights are still
hand-set), lane 3, and the eait side of the label-photo loop.

### Intake lanes

1. **Open composition tables**, loaded when each publisher releases: USDA FDC (CC0), CIQUAL, BLS,
   Fineli, Frida, Matvaretabellen (NLOD 2.0), CoFID (OGL), Korea MFDS, Japan MEXT, Taiwan TFDA, and
   others. Built ([#15](https://github.com/eait-fit/fooddb/issues/15)): USDA FDC Foundation, SR
   Legacy and Branded Foods, CIQUAL (Etalab 2.0), CoFID (OGL v3.0, [#36](https://github.com/eait-fit/fooddb/issues/36)), Fineli
   (CC BY 4.0) and Matvaretabellen (NLOD 2.0). FDC Branded and Fineli are off by default. The FDC
   fetcher reads its JSON as a stream. Not built: Frida
   ([#35](https://github.com/eait-fit/fooddb/issues/35)), Korea MFDS
   ([#37](https://github.com/eait-fit/fooddb/issues/37)), Japan MEXT
   ([#38](https://github.com/eait-fit/fooddb/issues/38)), Taiwan TFDA
   ([#39](https://github.com/eait-fit/fooddb/issues/39)) and BLS.
2. **Open Food Facts**: the full dump, then daily deltas. Built: a fresh install takes the newest
   delta, then every delta after it. The full dump is a manual job (`fooddb run off-dump`). Its data is under ODbL (see Licences).
3. **Brands**: a brand upload form in v1. The uploader's brand is checked against the GS1
   company prefix, and a label photo is attached. GDSN data pools come later. Built ([#13](https://github.com/eait-fit/fooddb/issues/13)):
   `POST /v1/brands/uploads` and an HTML form at `/brands/upload`. Each upload becomes the record
   `brand:<gtin14>`. The GS1 verifier is still `none`, so every value of an upload waits for review.
4. **Own label reads**: a vision model reads a label photo into structured nutrition, through
   the model port (below). Photos come from eait users who opt in, from brands, and from customers'
   local runs. Built ([#12](https://github.com/eait-fit/fooddb/issues/12)): `POST /v1/labels` takes a
   photo and queues a read. Each read becomes the observations of the record `label:<sha256>`.

### Normalise

- All values per 100 g or per 100 ml, in canonical units.
- Barcodes stored as GTIN-14 with a validated check digit. Prefixes 02 and 20–29 are store or
  local numbers and are never treated as global keys. The code also refuses the coupon and
  restricted prefixes 04, 05, 98 and 99.
- Food ids take the form `<source>:<code>`.

### Observations

Append-only. Each row records one field value, its source, when it was observed, and the evidence
(source record, photo). Nothing is overwritten, so any served value can be traced back.
Built: a label value names its photo by SHA-256 in `observation.evidence`. For the other sources,
the evidence is the source record. Unchanged values are not stored again, and a
field that disappears from a newer record is stored as withdrawn. Built ([#28](https://github.com/eait-fit/fooddb/issues/28)):
a record seen again at the same `observed_at` can also withdraw a field.

### Checks

- Atwater: stated energy against the energy computed from the macros.
- Sums: sugars ≤ carbohydrate, saturates ≤ fat, and so on.
- Ranges per category, and front-of-pack warning seals against nutrient thresholds (LatAm octagons).

Built: Atwater, sums (with a 0.5 g tolerance), macros over 100 g, negative values, ranges per
category, and seals for Chile, Mexico and Peru ([#11](https://github.com/eait-fit/fooddb/issues/11)).
The API computes the seals on each read, and they hold no value for review. A seal that OFF says
the pack carries, but that the values do not reach, is a failed check. Each failed check names
the fields that it implicates. Only the new values of those fields are `pending`. A reviewer or an
agent accepts or rejects each one, and the decision records who decided and when.

### Resolver

Chooses a winning value per field from trust rank, recency and agreement between sources. A
label read that a reviewer approved always wins. Otherwise a label read outranks a crowd edit,
which outranks an older table value.

Built for nutrient values: an approved label read wins first, and the newest of several wins.
Otherwise a value much older than the newest one loses (default 730 days). Then
the value that most sources agree with wins, then the source rank, then the newest value. FDC
and the national tables share one rank, above OFF. Label reads have a rank above the tables.
For other label reads, agreement still comes before rank, so a label read that is alone loses to
two sources that agree. Brand uploads get no such override.

### Snapshot and serving

- A nightly snapshot, versioned and immutable. The API serves the latest one;
  `?snapshot=YYYY-MM-DD` pins an earlier one for 30 days. Built: one snapshot per UTC day. A day is
  final when it is over. Until then, a rebuild on the same day replaces it. A merge after a build
  keeps the values that the build froze. Records and names are read live, not frozen. Built: the
  export of one day as NDJSON, for consumers that keep a local copy. Not built: the eait job that
  loads it.
- Customers may store what they fetch.
- Responses contain only core data by default. `include=off` adds the OFF layer. Every field
  carries a licence tag. Built: each served field, each barcode and each nutrient value has its
  source and licence. The non-nutrient fields and the barcodes also name their source record.
  Built ([#24](https://github.com/eait-fit/fooddb/issues/24)): every served number is a JSON number.
- Search uses `pg_trgm`. Known limit: short CJK names match poorly.

## Model port

All LLM work, label reads included, goes through one port with two backends:

- **OpenRouter**, used by the hosted pipeline. Models can be switched by config.
- **Local agents** (Claude, Codex, Devin) running on the user's own licence. When customers run the
  CLI or MCP server locally, they can do label reads on their own key, and the results come back
  as observations.

Built ([#12](https://github.com/eait-fit/fooddb/issues/12)) for label reads: `openrouter`,
`claude-cli` and `codex-cli`, plus a `demo` backend. The MCP tool `read_label` runs on stdio with
the user's own Claude or Codex subscription. It can submit the read to a fooddb server, where every
value waits for review. Not built: a Devin backend.

## Stack

Python throughout: uv, FastAPI (whose OpenAPI spec also serves the RapidAPI listing), SQLAlchemy
with Alembic, the official MCP Python SDK, Typer for the CLI, and Splink for matching, run in
process. The review UI is SQLAdmin plus one custom page, **Label reads**, which shows the photo next
to the values read from it and the values served now. Built. Built ([#48](https://github.com/eait-fit/fooddb/issues/48)): the admin panel with the pages Overview, Jobs, Requests and Users, a request log of route templates, and actions as POST forms with a CSRF token. The MCP server has the read tools and
two review tools, over stdio (`fooddb mcp`) and Streamable HTTP at `/mcp`. Built: our own API keys
with the scopes `read`, `contribute`, `review` and `admin`, and a rate limit per key. REST, `/mcp` and the
`/admin` login check them. stdio is local and needs no key. Not built: the RapidAPI listing. The
API already accepts RapidAPI's proxy secret as a `read` key. Built ([#44](https://github.com/eait-fit/fooddb/issues/44)):
a developer portal at `/portal` with email-link sign-in, self-serve read keys and prepaid request
packs through Stripe Checkout. Each keyed read of an account costs one credit.

## Data model

Values per 100 g or per 100 ml, plus the serving size printed on the label. Nutrient codes use FAO
INFOODS tagnames (ENERC, PROCNT, FAT, CHOAVL…). Each value keeps the code of the quantity that its
source states, and no value is converted to another code. Built
([#7](https://github.com/eait-fit/fooddb/issues/7)): carbohydrate is `CHOCDF` (by difference, with
fibre) from FDC and US or Canadian labels, and `CHOAVL` (available, without fibre) from EU, UK,
Australian and similar labels, and from CIQUAL, Fineli and Matvaretabellen. fooddb stores no CoFID carbohydrate, because CoFID gives it
in monosaccharide equivalents. Energy is `ENERC_KCAL`, plus `ENERC_KJ` when the source states kJ.

## Licences

| Source | Licence | Obligation |
|---|---|---|
| USDA FDC | CC0 | none |
| CIQUAL (France) | Licence Ouverte / Etalab 2.0 | attribution, built |
| CoFID (UK) | OGL v3.0 | attribution, built |
| Fineli (Finland) | CC BY 4.0 | attribution, built |
| Matvaretabellen (Norway) | NLOD 2.0 | attribution, built |
| Open Food Facts | ODbL | Share-alike on the derived database. It is kept in its own layer, which we publish monthly as an ODbL dump at `/v1/dumps` ([#14](https://github.com/eait-fit/fooddb/issues/14), built). See [data-licence.md](data-licence.md). |
| Most EU national tables | CC BY / OGL / NLOD | attribution |
| Korea MFDS | public, no usage restriction | none |
| Japan MEXT | cite the source | attribution |

fooddb's code is AGPL-3.0. Its core data has its own terms. See [landscape.md](landscape.md)
for licence traps in nearby open-source projects.

## Packaging

fooddb is its own repo, database and deploy. It is not part of the eait backend, because:

- eait scopes every row to one user, while this catalog is global and needs API keys, rate limits
  and billing. API keys and rate limits are built. Billing goes through RapidAPI and is not built.
- ODbL share-alike stays inside one database with a clear edge.
- Batch ingestion and review must not share CPU, deploys or incidents with meal logging.
- B2B customers need versioned releases and their own uptime commitment.
