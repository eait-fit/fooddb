# Why fooddb

What fooddb does that other food-data options do not, and where it is weaker. The README links here.

## What makes it different

- **Per-field provenance.** Every served value carries its `source`, its `licence` and the source `record` it came from ([`resolve.py`](../src/fooddb/resolve.py)).
- **Per-field trust resolution.** The resolver picks the best value for each nutrient, not for the whole product, by freshness, agreement between sources and source rank.
- **Automatic checks and a review queue.** Energy against the Atwater macros, sugars over carbohydrate and five more checks ([`checks.py`](../src/fooddb/checks.py)) hold a bad value back for a human.
- **Entity matching across sources.** [Splink](https://github.com/moj-analytical-services/splink) joins records of the same product, and a reviewer can split a wrong merge for good.
- **Licence-clean layers.** Government data stays in the core layer, and OFF data stays in its own ODbL layer, so the core is not forced under ODbL. Also, fooddb publishes the OFF layer as a monthly ODbL dump.
- **Reproducible daily snapshots.** Pin any of the last 30 days, or sync a local read-only copy from the NDJSON export. You may store what you fetch.
- **REST, MCP and CLI from one database**, in one image, in about 430 MB of RAM. The production stack of API, worker and Postgres 18 runs on one small Hetzner Cloud VM.

## How it compares

| | fooddb | Open Food Facts server [1] | OpenNutrition and mcp-opennutrition [2] | Raw USDA FDC files [3] | Nutritionix, Edamam, FatSecret [4] |
|---|---|---|---|---|---|
| Runs on your own server | Yes, Docker Compose | Yes, Docker | Yes, local dataset and local MCP | Yes, file download | No. Edamam bars saving data [5]. Nutritionix: unknown |
| Sources merged | USDA FDC and 6 national tables, plus OFF in a separate layer | One crowd-edited source | USDA, CNF, FRIDA, AUSNUT and web sources, reconciled by language models | One (USDA) | Not documented per source |
| Per-field provenance | Yes: source, licence, record | One source only | Partial: the project says "significant gaps in attribution remain" | One source only | Unknown |
| Conflict resolution across sources | Per field: approved label read, freshness, agreement, source rank | None between sources | Language models reconcile values | Not needed | Unknown |
| Quality checks and human review | Yes: 7 checks, review queue, `/admin` | Yes: data-quality checks, crowd edits [6] | Model audit, no review queue documented | No | Unknown |
| MCP server | Built in, stdio and HTTP | No official server [6] | Yes, local | No | Edamam: yes [7]. FatSecret: not mentioned. Nutritionix: unknown |
| Licence of code and data | AGPL-3.0. Data per source, OFF layer ODbL | AGPL-3.0, ODbL | MIT (MCP), ODbL (data) | CC0 [8] | Proprietary. Caching is limited [5] [9] |
| Stack | Python, FastAPI, Postgres 18 | Perl, MongoDB | Node.js | Files | Hosted |

Among the projects in this table that you can run yourself, only fooddb does all four of the following. It merges several government tables with Open Food Facts. It keeps the source and the licence on every value. It resolves conflicts per field. It ships as a database that you run yourself.

fooddb has a much smaller catalog. Production holds 41,848 products. FatSecret states more than 2.3 million food items [9], Open Food Facts states 1.7 million products [1], and mcp-opennutrition states 300,000 items [2].

Sources, checked on 2026-10-08 unless noted. `unknown` means that the vendor page did not answer the question or could not be read.

1. [Open Food Facts server](https://github.com/openfoodfacts/openfoodfacts-server): Perl and MongoDB, AGPL-3.0, Docker setup. Data under ODbL. The repository page states "1.7 million+ products from 150 countries". Overlap and treatment: [docs/landscape.md](landscape.md) (checked 2026-10-04).
2. [OpenNutrition](https://www.opennutrition.app/about) (sources, language-model method, attribution gaps) and [mcp-opennutrition](https://github.com/deadletterq/mcp-opennutrition) (MIT, "runs fully locally", 300,000+ items).
3. [USDA FoodData Central downloads](https://fdc.nal.usda.gov/download-datasets/): CSV and JSON files. The CC0 licence is stated in [docs/data-licence.md](data-licence.md).
4. The three hosted vendors: [Nutritionix](https://www.nutritionix.com/api), [Edamam](https://developer.edamam.com/food-database-api) and [FatSecret](https://platform.fatsecret.com/platform-api). The Nutritionix pages answered HTTP 402 to automated requests, so its cells say `unknown`.
5. [Edamam Food Database API](https://developer.edamam.com/food-database-api): "API customers can cache only the four basic macro nutrient datapoints". The terms bar any request that aims to "collect, scrape or save data".
6. [docs/landscape.md](landscape.md): data-quality checks in `DataQualityFood.pm`, the Robotoff review queue, and "There is no official Open Food Facts MCP server."
7. [Edamam Food MCP](https://developer.edamam.com/mcp-edamam-food): a public MCP server for the Food Database API.
8. [docs/data-licence.md](data-licence.md): USDA FDC is tagged `CC0-1.0`.
9. [FatSecret storable data](https://platform.fatsecret.com/docs/guides/storable-data): "you may not cache any user data for more than 24 hours", except 11 identifiers. The [platform page](https://platform.fatsecret.com/platform-api) states "more than 2.3 million verified food items" and offers no self-hosting.
