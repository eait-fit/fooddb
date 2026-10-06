# Data licence

fooddb's code is under [AGPL-3.0](../LICENSE). The data has its own licences, per source. Every
served field and value carries the licence of its source in its `licence` tag.

| Data | Licence |
|---|---|
| Core data from USDA FoodData Central | CC0-1.0 |
| Core data from CIQUAL (ANSES, France), tagged `etalab-2.0` | [Licence Ouverte / Open Licence 2.0 (Etalab)](https://www.etalab.gouv.fr/licence-ouverte-open-licence/) |
| Core data from Fineli (THL, Finland), tagged `CC-BY-4.0` | [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/) |
| Core data from Matvaretabellen (Mattilsynet, Norway), tagged `NLOD-2.0` | [Norwegian Licence for Open Government Data 2.0](https://data.norge.no/nlod/en/2.0) |
| Core data from MEXT (Japan), tagged `mext-free-use` | Free use, with the source cited. See the [MEXT terms of use](https://www.mext.go.jp/a_menu/syokuhinseibun/index.htm) |
| Other core data | fooddb's own terms |
| The Open Food Facts layer (`off`, tagged `ODbL-1.0`) | [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/) |

## National composition tables

The terms of CIQUAL, Fineli, Matvaretabellen and MEXT ask you to name the source. Each product in the
API and in the snapshot export has an `attribution` list: one entry for each of these sources that
gives a served field. Each entry has the `source`, the `licence` and the `text`. Show the text where
you use the data, or link to it. The texts are:

| Source | Attribution |
|---|---|
| `ciqual` | Anses. Ciqual French food composition table (https://ciqual.anses.fr). Licence Ouverte / Etalab 2.0. |
| `fineli` | Finnish Institute for Health and Welfare (THL), Fineli (https://fineli.fi). CC BY 4.0. |
| `mext` | 日本食品標準成分表（八訂）増補2023年から引用 (Standard Tables of Food Composition in Japan, 8th revised edition, 2023 supplement, Ministry of Education, Culture, Sports, Science and Technology, https://www.mext.go.jp/a_menu/syokuhinseibun/mext_00001.html). |
| `matvaretabellen` | Contains data from Matvaretabellen (https://www.matvaretabellen.no), Norwegian Food Safety Authority, made available under the Norwegian Licence for Open Government Data (NLOD) 2.0. |

fooddb changes this data: it maps the nutrient codes to INFOODS, converts kJ to kcal for Fineli,
and leaves out values that the table gives only as a limit. For MEXT it also drops the class headings
that lead some food names. These licences have no share-alike
obligation.

## The Open Food Facts layer

The `off` layer is derived from [Open Food Facts](https://world.openfoodfacts.org). Open Food Facts
publishes its database under the ODbL 1.0, and its contents under the Database Contents License
1.0. fooddb normalises, checks and matches this data. The result is a derived database, so the ODbL
applies to it too.

Attribution:

> Contains information from Open Food Facts (https://world.openfoodfacts.org), which is made
> available here under the Open Database License (ODbL) 1.0.

## The monthly ODbL dump

fooddb publishes the ODbL part of its data each month, as the ODbL requires:

- `GET /v1/dumps` lists the dumps, newest first. Each manifest has the day, the product count, the
  size, the SHA-256, the licence and the attribution.
- `GET /v1/dumps/{name}` downloads one dump: gzipped NDJSON, one product per line.
- These routes need no API key, also when reads need one. They count against the rate limit.

A dump holds the products of the newest final snapshot day that have an Open Food Facts record.
For each product, it keeps the fooddb product id, the `off:` record ids, and each field and value
tagged `ODbL-1.0`. It holds no other value. The fooddb product id links a line to the API.

## Your obligations

If you use the dump, or OFF data from the API (`include=off`):

- **Attribute.** Show the attribution above where you use the data, or link to it.
- **Share alike.** If you publicly use a database that you derive from this data, offer that
  database under the ODbL 1.0 too.
- **Keep it open.** Do not add technical measures that stop others from using the data under the
  ODbL, unless you also offer an unrestricted copy.

This page is a summary. The [licence text](https://opendatacommons.org/licenses/odbl/1-0/) is
binding.
