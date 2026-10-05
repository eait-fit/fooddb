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

**Built:** lanes 1 and 2 (FDC Foundation and SR Legacy, OFF), normalise, observations, checks,
Splink matching (not in the diagram above: it runs between observations and the resolver), the
resolver, the nightly snapshot and its NDJSON export, REST and MCP, and the review queue
(`/v1/review`, two MCP tools, SQLAdmin at `/admin`), and API keys with scopes and rate limits. The checks run before the insert and set each
value's status. **Not built:** the review page with the photo
([#12](https://github.com/eait-fit/fooddb/issues/12)), lanes 3 and 4, and the label-photo loop.

### Intake lanes

1. **Open composition tables**, loaded when each publisher releases: USDA FDC (CC0), CIQUAL, BLS,
   Fineli, Frida, Matvaretabellen (NLOD 2.0), CoFID (OGL), Korea MFDS, Japan MEXT, Taiwan TFDA, and others. Built: USDA FDC Foundation and SR Legacy. The rest:
   [#15](https://github.com/eait-fit/fooddb/issues/15).
2. **Open Food Facts**: the full dump, then daily deltas. Built: a fresh install takes the newest
   delta, then every delta after it. The full dump is a manual job (`fooddb run off-dump`). Its data is under ODbL (see Licences).
3. **Brands**: a brand upload form in v1. The uploader's brand is checked against the GS1
   company prefix, and a label photo is attached. GDSN data pools come later. Not built: [#13](https://github.com/eait-fit/fooddb/issues/13).
4. **Own label reads**: a vision model reads a label photo into structured nutrition, through
   the model port (below). Photos come from eait users who opt in, from brands, and from customers'
   local runs. Not built: [#12](https://github.com/eait-fit/fooddb/issues/12).

### Normalise

- All values per 100 g or per 100 ml, in canonical units.
- Barcodes stored as GTIN-14 with a validated check digit. Prefixes 02 and 20–29 are store or
  local numbers and are never treated as global keys. The code also refuses the coupon and
  restricted prefixes 04, 05, 98 and 99.
- Food ids take the form `<source>:<code>`.

### Observations

Append-only. Each row records one field value, its source, when it was observed, and the evidence
(source record, photo). Nothing is overwritten, so any served value can be traced back.
Built without the photo: evidence is the source record only
([#12](https://github.com/eait-fit/fooddb/issues/12)). Unchanged values are not stored again, and a
field that disappears from a newer record is stored as withdrawn.

### Checks

- Atwater: stated energy against the energy computed from the macros.
- Sums: sugars ≤ carbohydrate, saturates ≤ fat, and so on.
- Ranges per category, and front-of-pack warning seals against nutrient thresholds (LatAm octagons).

Built: Atwater, sums (with a 0.5 g tolerance), macros over 100 g, and negative values. Not built:
ranges and seals ([#11](https://github.com/eait-fit/fooddb/issues/11)). Each failed check names
the fields that it implicates. Only the new values of those fields are `pending`. A reviewer or an
agent accepts or rejects each one, and the decision records who decided and when.

### Resolver

Chooses a winning value per field from trust rank, recency and agreement between sources. A
verified label read outranks a crowd edit, which outranks an older table value.

Built: a fixed source rank (FDC before OFF), then the newest value. Agreement and the
crowd-versus-old-table rule are not built ([#5](https://github.com/eait-fit/fooddb/issues/5)).

### Snapshot and serving

- A nightly snapshot, versioned and immutable. The API serves the latest one;
  `?snapshot=YYYY-MM-DD` pins an earlier one for 30 days. Built: one snapshot per UTC day. A day is
  final when it is over. Until then, a rebuild on the same day replaces it. A merge after a build
  keeps the values that the build froze. Records and names are read live, not frozen. Built: the
  export of one day as NDJSON, for consumers that keep a local copy. Not built: the eait job that
  loads it.
- Customers may store what they fetch.
- Responses contain only core data by default. `include=off` adds the OFF layer. Every field
  carries a licence tag. Built for nutrient values only
  ([#4](https://github.com/eait-fit/fooddb/issues/4)).
- Search uses `pg_trgm`. Known limit: short CJK names match poorly.

## Model port

All LLM work, label reads included, goes through one port with two backends:

- **OpenRouter**, used by the hosted pipeline. Models can be switched by config.
- **Local agents** (Claude, Codex, Devin) running on the user's own licence. When customers run the
  CLI or MCP server locally, they can do label reads on their own key, and the results come back
  as observations.

Not built: [#12](https://github.com/eait-fit/fooddb/issues/12).

## Stack

Python throughout: uv, FastAPI (whose OpenAPI spec also serves the RapidAPI listing), SQLAlchemy
with Alembic, the official MCP Python SDK, Typer for the CLI, and Splink for matching, run in
process. The review UI is SQLAdmin plus one custom page. Built: everything except the custom photo
page ([#12](https://github.com/eait-fit/fooddb/issues/12)). The MCP server has the read tools and
two review tools, over stdio (`fooddb mcp`) and Streamable HTTP at `/mcp`. Built: our own API keys
with the scopes `read`, `review` and `admin`, and a rate limit per key. REST, `/mcp` and the
`/admin` login check them. stdio is local and needs no key. Not built: the RapidAPI listing. The
API already accepts RapidAPI's proxy secret as a `read` key.

## Data model

Values per 100 g or per 100 ml, plus the serving size printed on the label. Nutrient codes use FAO
INFOODS tagnames (ENERC, PROCNT, FAT, CHOAVL…). Built: the code stores `ENERC_KCAL` and `CHOCDF`
(carbohydrate by difference), not `ENERC` and `CHOAVL`. Which set is canonical is open
([#7](https://github.com/eait-fit/fooddb/issues/7)).

## Licences

| Source | Licence | Obligation |
|---|---|---|
| USDA FDC | CC0 | none |
| Open Food Facts | ODbL | Share-alike on the derived database. It is kept in its own layer, which we publish monthly as an ODbL dump ([#14](https://github.com/eait-fit/fooddb/issues/14), not built). |
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
