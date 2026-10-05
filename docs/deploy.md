# Deploy fooddb

This runbook installs fooddb on one server with Docker Compose. The stack is in
[`deploy/docker-compose.yml`](../deploy/docker-compose.yml). It has four services:

| Service | What it does |
|---|---|
| `db` | Postgres 18. The data is in the `fooddb_pgdata18` volume. |
| `migrate` | Applies the fooddb and pq migrations, then stops. It runs on every `up`. |
| `api` | The REST API on port 8000 inside the container. |
| `worker` | The pq job worker: fetches, matching and the nightly snapshot. |

The `api` and `worker` services start only after `migrate` succeeds.

## Requirements

- A Linux server (a VPS is sufficient) with 2 CPUs and 2 GB of memory or more.
- Docker Engine with the Compose v2 plugin (`docker compose version` must work).
- About 1 GB of free disk for the image and the data of the first boot. The image is
  490 MB. The database is 210 MB after the first boot.
- Outbound HTTPS to `fdc.nal.usda.gov` and `static.openfoodfacts.org`.
- For TLS: a DNS name with an A record that points to the server, and open ports 80 and 443.

The optional full Open Food Facts dump needs much more disk. See
[Load the full Open Food Facts dump](#load-the-full-open-food-facts-dump).

## Install

1. Get the code:

   ```bash
   git clone https://github.com/eait-fit/fooddb.git
   cd fooddb/deploy
   ```

   Run all the other commands in this runbook from the `deploy/` directory.

2. Create the settings file:

   ```bash
   cp .env.example .env
   sed -i "s/^FOODDB__BACKEND__POSTGRES_PASSWORD=$/FOODDB__BACKEND__POSTGRES_PASSWORD=$(openssl rand -hex 24)/" .env
   ```

   Git ignores `deploy/.env`. Do not commit it. The other settings in the file are optional.

3. Build the image and start the stack:

   ```bash
   docker compose up -d --build
   ```

4. Make sure that all the services are up:

   ```bash
   docker compose ps
   ```

   `db` and `api` show `healthy`. `migrate` is not in the list, because it stopped after it
   applied the migrations.

## First boot

The first boot fills the database without help. The worker does these jobs in this sequence:

1. It downloads USDA FoodData Central Foundation and SR Legacy.
2. It runs Splink matching.
3. It builds the first snapshot. This snapshot has FDC values only.
4. It downloads the newest Open Food Facts delta file.
5. It runs Splink matching again.
6. It builds the snapshot again. Now the snapshot has Open Food Facts values too.

On a test server, `/healthz` changed to 200 after 70 seconds. On a slow network, it can take
3 minutes. Wait for the 200:

```bash
until curl -sf -o /dev/null http://127.0.0.1:8000/healthz; do sleep 10; done
curl -s http://127.0.0.1:8000/healthz
```

`/healthz` can change to 200 before steps 5 and 6 end. Until then, Open Food Facts products
can have an empty `per_100`. The second `snapshot:` line in `docker compose logs worker` shows
that step 6 is complete.

Do a test of the API:

```bash
curl "http://127.0.0.1:8000/v1/foods?q=hummus"
curl "http://127.0.0.1:8000/v1/products/00000000010177?include=off"
docker compose exec worker fooddb status
```

## TLS with Caddy

The API port is open on `127.0.0.1` only. Put a TLS reverse proxy in front of it. This example
uses [Caddy](https://caddyserver.com/docs/install), which gets and renews the certificate
without more configuration.

1. Install Caddy on the server.
2. Replace `fooddb.example.com` with your DNS name and put this in `/etc/caddy/Caddyfile`:

   ```caddy
   fooddb.example.com {
   	reverse_proxy 127.0.0.1:8000
   }
   ```

3. Load the new configuration:

   ```bash
   sudo systemctl reload caddy
   ```

4. Make sure that the API answers over HTTPS:

   ```bash
   curl https://fooddb.example.com/healthz
   ```

If Caddy runs in a container on a Docker network, it cannot reach `127.0.0.1` of the host.
In that case, set `FOODDB__DEPLOY__BIND` in `deploy/.env` to an address that the Caddy container
can reach. Do not publish the port on a public interface.

## Settings

All the settings are in `deploy/.env`:

| Variable | Default | Meaning |
|---|---|---|
| `FOODDB__BACKEND__POSTGRES_PASSWORD` | none, necessary | The password of the `fooddb` database user. |
| `FOODDB__DEPLOY__IMAGE` | `fooddb:latest` | The image name. Set it to use a published image. |
| `FOODDB__DEPLOY__BIND` | `127.0.0.1` | The host address where Compose publishes the API port. |
| `FOODDB__DEPLOY__PORT` | `8000` | The host port of the API. |
| `FOODDB__BACKEND__MATCH_THRESHOLD` | `0.95` | The Splink match probability that merges two products. |

After you change `deploy/.env`, apply the change:

```bash
docker compose up -d
```

## Health and logs

fooddb has two health endpoints:

- `/livez` returns 200 when the API process runs and can read the database. The container health
  check uses it.
- `/healthz` returns 200 when all the data is fresh, and 503 when one source is stale. The
  JSON body shows the last successful run and the maximum age of each fetcher and of the snapshot.

Point your uptime monitor at `/healthz`. A 503 means that a fetch or the snapshot failed, or
that the worker is stopped.

Read the logs:

```bash
docker compose logs -f worker      # fetches, matching, snapshots
docker compose logs -f api
docker compose exec worker fooddb status   # row counts, the last 5 fetch runs, the job queue
```

## Consumer sync

A service that keeps its own copy of the catalog reads the snapshot export. The README has the
steps: [Sync a local copy](../README.md#sync-a-local-copy). For the operator:

- The export of a large day is long. With the full OFF dump it has about 4 million lines. Give the
  consumer's HTTP client a long read timeout. Caddy streams the response and needs no change.
- Run the consumer's sync after the nightly snapshot (02:30 UTC). Sync the newest day where
  `final` is `true`: that is yesterday's snapshot.
- To make a file instead, run `docker compose exec api fooddb export --day 2026-10-04 --out
  /tmp/2026-10-04.ndjson.gz`, then copy the file out of the container.
- The export has no authentication yet, like the rest of the API
  ([#10](https://github.com/eait-fit/fooddb/issues/10)).

## Upgrade

1. Make a backup. See [Back up](#back-up).
2. Get the new code:

   ```bash
   git pull
   ```

3. Build the new image and start the stack again:

   ```bash
   docker compose up -d --build
   ```

A new major version of Postgres cannot read the data of the previous one. The volume name carries
the major version (`pgdata18`), so a new major starts with a new, empty volume. To keep your data,
make a backup before the upgrade and restore it after. See [Back up](#back-up) and
[Restore](#restore).

The `migrate` service applies the new migrations before the `api` and `worker` services start.
If a migration fails, `api` and `worker` do not start. Read the cause with
`docker compose logs migrate`.

## Back up

Write a compressed dump of the database to the host:

```bash
docker compose exec -T db pg_dump -U fooddb -Fc fooddb > fooddb-$(date +%F).dump
```

The dump after the first boot is 2 MB. Copy the dump to a different machine. To make a backup
every night, add the command to a cron job on the host.

## Restore

This procedure replaces all the data in the database with the dump.

1. Stop the API and the worker:

   ```bash
   docker compose stop api worker
   ```

2. Delete the database and create an empty one:

   ```bash
   docker compose exec -T db dropdb -U fooddb --force fooddb
   docker compose exec -T db createdb -U fooddb fooddb
   ```

3. Load the dump:

   ```bash
   docker compose exec -T db pg_restore -U fooddb -d fooddb --no-owner < fooddb-2026-10-05.dump
   ```

4. Start the stack:

   ```bash
   docker compose up -d
   ```

The fetchers in the dump are already marked as done. Thus the worker does not fill the
database again after a restore.

## Load the full Open Food Facts dump

This step is optional. Without it, the Open Food Facts layer has only the products from the
daily delta files after the first boot. The full dump adds about 4 million products.

The download is about 13 GB. The worker reads it as a stream, so the download does not go to
disk. But the database becomes much larger. The size was not measured. Make sure that the
server has a large amount of free disk before you start. Watch the free disk during the load.

The load takes hours, which is more than the per-task timeout of the worker. Thus run it in its
own container:

```bash
docker compose run -d --name fooddb-off-dump worker fooddb run off-dump
docker logs -f fooddb-off-dump
```

After the load, the daily delta files keep the layer current. A second run of `off-dump` does
nothing until Open Food Facts publishes a new dump.

## Stop and remove

```bash
docker compose down      # stop the stack, keep the data
docker compose down -v   # stop the stack and DELETE the data volume
```

## Troubleshooting

**The build fails with `dns error` or `No route to host` in `uv sync`.** The default Docker
bridge network on the server has no outbound access. Build the image on the host network, then
start the stack without a build:

```bash
docker build --network host -t fooddb:latest ..
docker compose up -d
```

**`docker compose` stops with `set FOODDB__BACKEND__POSTGRES_PASSWORD in deploy/.env`.** The
`deploy/.env` file is missing, or `FOODDB__BACKEND__POSTGRES_PASSWORD` is empty. Do step 2 of
[Install](#install) again.

**`/healthz` returns 503.** Examine the `fetchers` object in the response body. Find the source
that has `"fresh": false`, then read `docker compose logs worker` for its last error.
