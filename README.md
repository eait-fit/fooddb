# fooddb

A food nutrition database that you host yourself. It merges USDA FoodData Central, six national
food tables and Open Food Facts into one dataset. Every value keeps its source and its licence.
You query it through a REST API, an MCP server or a CLI.

[Why fooddb](docs/why-fooddb.md) compares it with Open Food Facts, OpenNutrition and the hosted
nutrition APIs.

## Install and look up a food

You need a Linux or macOS machine with Docker, Docker Compose v2, curl and git or tar.

```bash
curl -fsSL https://raw.githubusercontent.com/eait-fit/fooddb/main/deploy/install.sh | sh
```

The installer builds the stack and waits until the API answers. On the first start, the worker
downloads the sources, which takes 1 to 7 minutes. Then look up an apple pie with one request:

```bash
curl "http://127.0.0.1:8000/v1/foods?q=apple+pie&limit=1"
```

Or with one CLI call:

```bash
docker compose -f fooddb/deploy/docker-compose.yml exec api fooddb search "apple pie" --limit 1
```

Both return the same data, shortened here:

```json
{"items": [{
  "id": 17335,
  "records": ["matvaretabellen:05.131"],
  "name": {"value": "Pie, apple", "source": "matvaretabellen", "licence": "NLOD-2.0", "record": "matvaretabellen:05.131"},
  "per_100": {
    "ENERC_KCAL": {"value": 214.0, "unit": "kcal", "basis": "100g", "source": "matvaretabellen", "licence": "NLOD-2.0"},
    "PROCNT": {"value": 2.6, "unit": "g", "basis": "100g", "source": "matvaretabellen", "licence": "NLOD-2.0"}
  }
}]}
```

Look up a packaged product with `GET /v1/products/{barcode}`. To connect an AI agent, add the MCP
server: `claude mcp add --transport http fooddb http://127.0.0.1:8000/mcp`.

- [docs/deploy.md](docs/deploy.md): TLS, upgrades, backups and API keys
- [docs/usage.md](docs/usage.md): every endpoint, the response shape, MCP, the CLI and local sync

You can also use the hosted instance at [food-api.eait.fit](https://food-api.eait.fit). Get a key
in its [customer portal](https://food-api.eait.fit/portal).

## Contribute

- [CONTRIBUTING.md](CONTRIBUTING.md): the local dev setup (`./dev`), tests and the PR process
- [docs/architecture.md](docs/architecture.md): the parts and the data flow, with diagrams
- [docs/design.md](docs/design.md): the pipeline, the data model and the sources
- [docs/decisions.md](docs/decisions.md): what is settled and what is still open
- [docs/data-licence.md](docs/data-licence.md): the licence of each source and the ODbL rules
- [Issues](https://github.com/eait-fit/fooddb/issues): bugs and planned work
- [SECURITY.md](SECURITY.md): report a vulnerability privately

The code is under [AGPL-3.0](LICENSE). The data keeps the licence of its source.
