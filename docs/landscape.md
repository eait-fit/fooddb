# Open-source landscape

What already exists in open source, and what fooddb takes from it, builds itself, or competes with.
Stars and push dates were checked on 2026-10-04.

## Summary

- **No open-source project does what fooddb does:** merge government tables, Open Food Facts and
  label reads into one dataset, with per-field provenance and per-field trust resolution.
- **Open Food Facts is the closest project.** It is both a data source and a competitor.
- **Every food MCP server found is a thin wrapper over one or two sources.** The MCP layer has
  value only because of the data behind it.
- **The only strong open label extractor is non-commercial.** This is why fooddb reads labels with
  a general vision model through the model port.

## Open-source competitors

| Project | Licence (code / data) | Activity | Overlap with fooddb | How we treat it |
|---|---|---|---|---|
| [Open Food Facts server](https://github.com/openfoodfacts/openfoodfacts-server) (Product Opener) | AGPL-3.0 / ODbL | 1166★, active | Branded products, GDSN import (`GS1.pm`), energy vs macros and other data checks (`DataQualityFood.pm`), CIQUAL links, REST API | A data source and a competitor. It is one crowd-edited source, edited at whole-product level, with no trust between sources. Read its check list as a spec. Do not fork it: Perl, AGPL, MongoDB. |
| [Robotoff](https://github.com/openfoodfacts/robotoff) | AGPL-3.0 | 114★, active | Nutrition extraction from photos, a human validation queue | A pattern for our review queue. Do not embed it. |
| [OpenNutrition](https://www.opennutrition.app) | – / ODbL | 300k+ items | Generic foods merged from USDA, CNF (Canada), Frida (Denmark), AUSNUT (Australia) | The closest competitor for generic foods. Using it would put our generic layer under ODbL, so we ingest the government tables directly. |
| [mcp-opennutrition](https://github.com/deadletterq/mcp-opennutrition) | MIT / ODbL | 207★ | The most popular food MCP server | The direct competitor to our MCP server. |
| [EuroFIR](https://www.eurofir.org) | membership, paid | – | Aggregates European national tables | A commercial competitor for generic foods in Europe. No open code. |
| OpenFoodRepo (foodrepo.org) | – / CC BY 4.0 | shut down | Swiss branded products | Gone. The site redirects to Open Food Facts. |

### Community MCP servers

About 14 found. Each covers one or two sources and does no merging, no provenance tracking and no
quality checks.

| Server | Data |
|---|---|
| [openfoodfacts-mcp-server (noot-app)](https://github.com/noot-app/openfoodfacts-mcp-server) | The OFF Parquet dump, run locally. The closest to our architecture. |
| [nutri-mcp](https://github.com/charliezstong/nutri-mcp) | OFF, USDA and Nutritionix, queried live with no merge |
| [domdomegg/openfoodfacts-mcp](https://github.com/domdomegg/openfoodfacts-mcp), [cyanheads/openfoodfacts-mcp-server](https://github.com/cyanheads/openfoodfacts-mcp-server) | The OFF API |
| [food-data-central-mcp-server](https://github.com/jlfwong/food-data-central-mcp-server) | The USDA FDC API |
| [ciqual-mcp](https://github.com/plemio/ciqual-mcp), [indian-food-nutrition-mcp](https://github.com/krishnabhat/indian-food-nutrition-mcp), [cn-food-mcp](https://github.com/ruffood/cn-food-mcp) | One national table each (France, India, China) |

There is no official Open Food Facts MCP server.

### Apps that could become customers

These apps all use OFF and USDA data. None of them curates its own verified database.

| App | Licence | Activity |
|---|---|---|
| [Grocy](https://github.com/grocy/grocy) | MIT | 9.5k★ |
| [SparkyFitness](https://github.com/CodeWithCJ/SparkyFitness) | MIT-style | 6.2k★ |
| [wger](https://github.com/wger-project/wger) | AGPL-3.0 | 7k★ |
| [Mealie](https://github.com/mealie-recipes/mealie) | AGPL-3.0 | 13.4k★ |
| [OpenNutriTracker](https://github.com/simonoppowa/OpenNutriTracker) | GPL-3.0 | 2.6k★ |
| [waistline](https://github.com/davidhealey/waistline) | GPL-3.0 | 747★ |

## Build vs reuse

| Pipeline stage | Decision | What we use |
|---|---|---|
| Open tables intake | Build, one importer per source | Bulk files: USDA FDC (CC0), CIQUAL, BLS and others. The existing FDC wrappers only call the rate-limited online API. |
| Open Food Facts intake | Reuse its outputs | The full dump plus the daily delta files (`static.openfoodfacts.org/data/delta/`), or the Parquet dataset on Hugging Face. The [openfoodfacts-python](https://github.com/openfoodfacts/openfoodfacts-python) SDK (MIT) if we need one. |
| Brand upload, GDSN | Build | OFF's `GS1.pm` field mapping, read as a spec only |
| Label reads | Build on the model port | A general vision model through OpenRouter or a local agent. Use the OFF label datasets (CC BY-SA) as the test set for measuring accuracy. |
| Normalise, GTIN-14 | Build | A short function with tests. The GS1 check digit is about ten lines. |
| Nutrient vocabulary | Reuse | FAO INFOODS tagnames (ENERC, PROCNT, FAT, CHOAVL…). FoodOn IDs (CC BY 4.0) as a cross-reference column. |
| Checks | Build | OFF's `DataQualityFood.pm` read as a spec |
| Entity matching | Reuse | [Splink](https://github.com/moj-analytical-services/splink) (MIT, 2.4k★, has a Postgres backend) |
| Per-field trust resolver | **Build: no open-source equivalent. This is the core we own.** | – |
| Review queue | Build | SQLAdmin plus one custom page. Robotoff and nutripatrol as references for the pattern. |
| Search | Reuse | Postgres `pg_trgm` |
| Serving | Reuse | FastAPI, the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), Typer |

## Licence traps

- **ODbL:** copying OFF or OpenNutrition rows into core tables puts the whole database under ODbL.
  Keep OFF data in its own layer, which per-field provenance makes possible.
- **AGPL:** fooddb is AGPL-3.0 itself, so AGPL code (Robotoff, OFF server modules, ParadeDB) can be reused when it's worth it. Our changes to it are published under the same licence. Permissive dependencies are still preferred.
- **Non-commercial:** OFF's `nutrition-extractor` model is CC-BY-NC-SA, so it cannot be used.
- **Commons Clause:** Tandoor forbids selling it.
