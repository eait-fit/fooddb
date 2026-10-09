# fooddb

A food nutrition database that you host yourself. It merges USDA FoodData Central, six national
food tables and Open Food Facts into one dataset. Every value keeps its source and its licence.
You query it through a REST API, an MCP server or a CLI.

[Why fooddb](docs/why-fooddb.md) compares it with Open Food Facts, OpenNutrition and the hosted
nutrition APIs.

## Install and look up a food

You need a Linux server with Docker Compose v2.

```bash
git clone https://github.com/eait-fit/fooddb.git
cd fooddb/deploy
cp .env.example .env
sed -i "s/^FOODDB__BACKEND__POSTGRES_PASSWORD=$/FOODDB__BACKEND__POSTGRES_PASSWORD=$(openssl rand -hex 24)/" .env
sed -i "s/^FOODDB__BACKEND__SECRET_KEY=$/FOODDB__BACKEND__SECRET_KEY=$(openssl rand -hex 32)/" .env
docker compose up -d --build
until curl -sf -o /dev/null http://127.0.0.1:8000/healthz; do sleep 10; done
```

On the first start, the worker downloads the sources. `/healthz` answers 200 when the data is in,
after 1 to 3 minutes. Then search:

```bash
curl "http://127.0.0.1:8000/v1/foods?q=hummus"
```

```json
{"items": [{
  "id": 12582,
  "records": ["matvaretabellen:06.679"],
  "name": {"value": "Hummus", "source": "matvaretabellen", "licence": "NLOD-2.0", "record": "matvaretabellen:06.679"},
  "per_100": {
    "ENERC_KCAL": {"value": 170.0, "unit": "kcal", "basis": "100g", "source": "matvaretabellen", "licence": "NLOD-2.0"},
    "PROCNT": {"value": 5.6, "unit": "g", "basis": "100g", "source": "matvaretabellen", "licence": "NLOD-2.0"}
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
