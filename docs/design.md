# Design

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

### Intake lanes

1. **Open composition tables**, loaded when each publisher releases: USDA FDC (CC0), CIQUAL, BLS,
   Fineli, Frida, Matvaretabellen (NLOD 2.0), CoFID (OGL), Korea MFDS, Japan MEXT, Taiwan TFDA, and others.
2. **Open Food Facts**: the full dump, then daily deltas. Its data is under ODbL (see Licences).
3. **Brands**: a brand upload form in v1. The uploader's brand is checked against the GS1
   company prefix, and a label photo is attached. GDSN data pools come later.
4. **Own label reads**: a vision model reads a label photo into structured nutrition, through
   the model port (below). Photos come from eait users who opt in, from brands, and from customers'
   local runs.

### Normalise

- All values per 100 g or per 100 ml, in canonical units.
- Barcodes stored as GTIN-14 with a validated check digit. Prefixes 02 and 20–29 are store or
  local numbers and are never treated as global keys.
- Food ids take the form `<source>:<code>`.

### Observations

Append-only. Each row records one field value, its source, when it was observed, and the evidence
(source record, photo). Nothing is overwritten, so any served value can be traced back.

### Checks

- Atwater: stated energy against the energy computed from the macros.
- Sums: sugars ≤ carbohydrate, saturates ≤ fat, and so on.
- Ranges per category, and front-of-pack warning seals against nutrient thresholds (LatAm octagons).

### Resolver

Chooses a winning value per field from trust rank, recency and agreement between sources. A
verified label read outranks a crowd edit, which outranks an older table value.

### Snapshot and serving

- A nightly snapshot, versioned and immutable. The API serves the latest one;
  `?snapshot=YYYY-MM-DD` pins an earlier one for 30 days.
- Customers may store what they fetch.
- Responses contain only core data by default. `include=off` adds the OFF layer. Every field
  carries a licence tag.
- Search uses `pg_trgm`. Known limit: short CJK names match poorly.

## Model port

All LLM work, label reads included, goes through one port with two backends:

- **OpenRouter**, used by the hosted pipeline. Models can be switched by config.
- **Local agents** (Claude, Codex, Devin) running on the user's own licence. When customers run the
  CLI or MCP server locally, they can do label reads on their own key, and the results come back
  as observations.

## Stack

Python throughout: uv, FastAPI (whose OpenAPI spec also serves the RapidAPI listing), SQLAlchemy
with Alembic, the official MCP Python SDK, Typer for the CLI, and Splink for matching, run in
process. The review UI is SQLAdmin plus one custom page.

## Data model

Values per 100 g or per 100 ml, plus the serving size printed on the label. Nutrient codes use FAO
INFOODS tagnames (ENERC, PROCNT, FAT, CHOAVL…).

## Licences

| Source | Licence | Obligation |
|---|---|---|
| USDA FDC | CC0 | none |
| Open Food Facts | ODbL | Share-alike on the derived database. It is kept in its own layer, which we publish monthly as an ODbL dump. |
| Most EU national tables | CC BY / OGL / NLOD | attribution |
| Korea MFDS | public, no usage restriction | none |
| Japan MEXT | cite the source | attribution |

fooddb's code is AGPL-3.0. Its core data has its own terms. See [landscape.md](landscape.md)
for licence traps in nearby open-source projects.

## Packaging

fooddb is its own repo, database and deploy. It is not part of the eait backend, because:

- eait scopes every row to one user, while this catalog is global and needs API keys, rate limits
  and billing.
- ODbL share-alike stays inside one database with a clear edge.
- Batch ingestion and review must not share CPU, deploys or incidents with meal logging.
- B2B customers need versioned releases and their own uptime commitment.
