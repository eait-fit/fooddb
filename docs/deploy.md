# Deploy fooddb

This runbook installs fooddb on one server with Docker Compose. The stack is in
[`deploy/docker-compose.yml`](../deploy/docker-compose.yml). It has four services:

| Service | What it does |
|---|---|
| `db` | Postgres 18. The data is in the `fooddb_pgdata18` volume. |
| `migrate` | Applies the fooddb and pq migrations, then stops. It runs on every `up`. |
| `api` | The REST API on port 8000 inside the container. It reads the ODbL dumps from the `fooddb_dumps` volume. |
| `worker` | The pq job worker: fetches, matching, the nightly snapshot and the monthly ODbL dump into `fooddb_dumps`. |

The `api` and `worker` services start only after `migrate` succeeds.

## Requirements

- A Linux server (a VPS is sufficient) with 2 CPUs and 2 GB of memory or more.
- Docker Engine with the Compose v2 plugin (`docker compose version` must work).
- About 1 GB of free disk for the image and the data of the first boot. The image is
  490 MB. The database was 210 MB after a first boot with FDC and Open Food Facts only. CIQUAL,
  Matvaretabellen and MEXT add about 8,000 foods. Their size was not measured.
- Outbound HTTPS to `fdc.nal.usda.gov`, `static.openfoodfacts.org`, `ciqual.anses.fr`,
  `www.matvaretabellen.no` and `www.mext.go.jp`. With Fineli on, also to the host of `FOODDB__BACKEND__FINELI_URL`.
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
   sed -i "s/^FOODDB__BACKEND__SECRET_KEY=$/FOODDB__BACKEND__SECRET_KEY=$(openssl rand -hex 32)/" .env
   ```

   Git ignores `deploy/.env`. Do not commit it. `FOODDB__BACKEND__SECRET_KEY` keys the stored
   API key hashes and signs the login cookie of `/admin`. Without it, no API key works and the API
   does not serve `/admin`. A new secret retires every API key. The other settings in the file
   are optional.

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

1. It downloads USDA FoodData Central Foundation and SR Legacy, CIQUAL (France) and
   Matvaretabellen (Norway). These are small tables of generic foods.
2. It runs Splink matching.
3. It builds the first snapshot. This snapshot has the values of these tables only.
4. It downloads the newest Open Food Facts delta file.
5. It runs Splink matching again.
6. It builds the snapshot again. Now the snapshot has Open Food Facts values too.

On a test server, `/healthz` changed to 200 after 70 seconds. On a slow network, it can take
3 minutes. Wait for the 200:

```bash
until curl -sf -o /dev/null http://127.0.0.1:8000/healthz; do sleep 10; done
curl -s http://127.0.0.1:8000/healthz
```

Two sources are off at first boot, and `/healthz` does not watch them while they are off:

- **FDC Branded Foods** (US branded products with barcodes). The download is a zip of about
  200 MB. It has about 3 GB of JSON, which the worker reads as a stream. The tempfile needs about
  200 MB of free disk, and the database grows by much more. The size was not measured. To switch
  it on, set `FOODDB__BACKEND__FETCH_FDC_BRANDED=true` and restart the worker. The worker then
  fetches it at once and every week. One load can take hours, and the worker runs no other task
  during that time. A task has a limit of six hours.
- **Fineli** (Finland). fineli.fi refuses automated downloads with a Cloudflare challenge
  (checked on 2026-10-06). Put a copy of the open data zip (basic package 1) where the worker can
  reach it. Then set `FOODDB__BACKEND__FINELI_URL` to it and `FOODDB__BACKEND__FETCH_FINELI=true`.

`/healthz` can change to 200 before steps 5 and 6 end. Until then, Open Food Facts products
can have an empty `per_100`. The second `snapshot:` line in `docker compose logs worker` shows
that step 6 is complete.

Do a test of the API:

```bash
curl "http://127.0.0.1:8000/v1/foods?q=hummus"
curl "http://127.0.0.1:8000/v1/products/00000000010177?include=off"
docker compose exec worker fooddb status
```

## API keys

fooddb has its own API keys. The API keeps only an PBKDF2-HMAC-SHA256 of a key, under `FOODDB__BACKEND__SECRET_KEY`. It shows the key
one time, when you create it. A key has one or more scopes:

| Scope | Gives access to |
|---|---|
| `read` | All the `GET` data routes, the snapshot export, and the MCP read tools. |
| `contribute` | `read`, plus `POST /v1/labels` (label photos) and `GET /v1/labels/{task}`. |
| `review` | `contribute`, plus `/v1/review` and the MCP tools `review_queue` and `decide_review`. |
| `admin` | `review`, plus the login to `/admin`. |

Writes, the review queue and `/admin` always need a key. Reads need a key only when
`FOODDB__BACKEND__REQUIRE_KEY_FOR_READS` is `true`. The default is `false`, so the read API stays
public. `/livez` and `/healthz` never need a key. `fooddb mcp` on stdio is local and needs no key.

1. Make the first admin key:

   ```bash
   docker compose exec api fooddb keys create --name ops --scope admin
   ```

   Copy the `fdb_…` token that the command prints. You cannot get it again. Keep it in a password
   manager. To log in to `/admin`, put the token in the password field. The username is not used.

2. Make a key for each client, with only the scopes that it needs:

   ```bash
   docker compose exec api fooddb keys create --name eait --scope read --rate-limit 600
   docker compose exec api fooddb keys create --name review-agent --scope review
   docker compose exec api fooddb keys create --name eait-labels --scope contribute
   ```

3. A client sends the key in the `Authorization: Bearer fdb_…` header, or in `X-API-Key`. An MCP
   client sends the same header to `/mcp`.

To see the keys and their last use, and to revoke a key:

```bash
docker compose exec api fooddb keys list
docker compose exec api fooddb keys revoke eait
```

A revoked key stops working on the next request. This is also true in an open `/admin` session.

**Rate limits.** Each key can send `FOODDB__BACKEND__RATE_LIMIT_PER_MINUTE` requests per minute
(default 60). `--rate-limit` sets a different limit for one key. Reads without a key have the same
limit per client IP address. Above the limit, the API answers 429 with a `Retry-After` header. The
counters are in Postgres, so all API replicas share them.

**RapidAPI.** Set `FOODDB__BACKEND__RAPIDAPI_PROXY_SECRET` to the proxy secret of your RapidAPI
listing. A request with the same `X-RapidAPI-Proxy-Secret` header then counts as a `read` key.
RapidAPI meters its own customers, so fooddb does not rate-limit these requests.

## Selling access

The developer portal at `/portal` sells prepaid packs of API requests. One pack is 100,000 requests
for EUR 29.99, paid once. The credits do not expire. There is no free tier. A user signs in with an
email link, makes read keys, and pays through Stripe Checkout. Each read request with such a key
costs one credit. At zero credits the API answers 402. Keys that you make with `fooddb keys create`
have no account and are never charged. Requests through RapidAPI are not charged either.

1. Set `FOODDB__BACKEND__REQUIRE_KEY_FOR_READS=true`, `FOODDB__BACKEND__SECRET_KEY` and
   `FOODDB__BACKEND__PUBLIC_URL` in `deploy/.env`.
2. Verify a sender domain in Resend. Set `FOODDB__BACKEND__RESEND_API_KEY` and
   `FOODDB__BACKEND__MAIL_FROM` on the host.
3. In the Stripe dashboard, open Developers, then Webhooks, and add an endpoint. Set the URL to
   `https://<host>/v1/stripe/webhook` and the event to `checkout.session.completed`. Copy the
   signing secret into `FOODDB__BACKEND__STRIPE_WEBHOOK_SECRET`. fooddb refuses an event whose
   signature does not match.
4. Create a restricted key (Developers, API keys, Create restricted key). Give it write permission
   for Checkout Sessions only, and nothing else. Set it as `FOODDB__BACKEND__STRIPE_SECRET_KEY`.
5. Optional: create a Product and a Price in Stripe, and set `FOODDB__BACKEND__STRIPE_PRICE_ID`.
   Without it, fooddb sends the price of EUR 29.99 inline. With it, the tax behaviour is the one
   on that Price. Create the Price with `tax_behavior` set (`inclusive`), and give its Product a tax
   code.
6. Optional: turn on Stripe Tax, add your registrations, and set
   `FOODDB__BACKEND__STRIPE_AUTOMATIC_TAX=true`. Stripe then calculates the tax on each session,
   and Checkout always asks for the billing address, because Stripe Tax needs the location.
   Stripe collects tax only where you have an active registration. Until your live account has one,
   a live sale collects no VAT.
7. Enable customer receipts in the Stripe email settings. Stripe sends them, not fooddb.
8. Run `docker compose up -d`, then open `https://<host>/portal` and buy one pack in Stripe test
   mode first.

If you enable a delayed payment method such as SEPA debit, also subscribe the endpoint to
`checkout.session.async_payment_succeeded`. fooddb adds the credits when the payment clears.

The webhook ignores every session that did not come from the portal. A paid session adds credits
once, even if Stripe delivers the event twice. To give credits or a free account by hand:

```bash
docker compose exec api fooddb accounts list
docker compose exec api fooddb accounts grant someone@example.com 100000
docker compose exec api fooddb accounts set-unlimited someone@example.com
```

`/admin` shows the accounts and the purchases, read-only. Its **Users** page also grants credits,
sets an account to unlimited and revokes keys. The **Jobs**, **Requests** and **Overview** pages show
the queue, the request log and the platform counts.

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

   Caddy sends the client address in `X-Forwarded-For`. The API uses it for the rate limit of
   reads without a key.

   Optional hardening: `/admin` needs an admin key, but you can also keep it off the internet.
   Add these two lines before `reverse_proxy`. Then open `/admin` through an SSH tunnel to port 8000.

   ```caddy
   	@admin path /admin /admin/*
   	respond @admin 403
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
| `FOODDB__BACKEND__SECRET_KEY` | none | Keys the API key hashes and signs the `/admin` login cookie. Without it, no API key works and the API does not serve `/admin`. A new secret retires every key. |
| `FOODDB__BACKEND__REQUIRE_KEY_FOR_READS` | `false` | `true`: reads need an API key too. See [API keys](#api-keys). |
| `FOODDB__BACKEND__RATE_LIMIT_PER_MINUTE` | `60` | Requests per minute per key, and per client IP for reads without a key. |
| `FOODDB__BACKEND__RAPIDAPI_PROXY_SECRET` | none | A request with this `X-RapidAPI-Proxy-Secret` header counts as a `read` key. |
| `FOODDB__BACKEND__PUBLIC_URL` | none | The public address of the API, for example `https://food-api.eait.fit`. The sign-in mails and the Stripe return links point there. The portal does not trust the `Host` header. |
| `FOODDB__BACKEND__RESEND_API_KEY` | none | The Resend key that mails the sign-in links. Set it on the server yourself. |
| `FOODDB__BACKEND__MAIL_FROM` | none | The sender of those mails, for a domain that Resend verifies. |
| `FOODDB__BACKEND__MAIL` | `resend` with a key | `log`: write the mails, with their sign-in links, to the server log. For development only. |
| `FOODDB__BACKEND__STRIPE_SECRET_KEY` | none | A Stripe restricted key that creates Checkout Sessions. Set it on the server yourself. |
| `FOODDB__BACKEND__STRIPE_WEBHOOK_SECRET` | none | The signing secret of the Stripe webhook endpoint. Without it, the webhook answers 503. |
| `FOODDB__BACKEND__STRIPE_PRICE_ID` | none | A Stripe price for one pack. Without it, fooddb sends a price of EUR 29.99 inline. |
| `FOODDB__BACKEND__STRIPE_AUTOMATIC_TAX` | `false` | `true`: Stripe Tax calculates the tax on each Checkout session. |
| `FOODDB__BACKEND__STRIPE_TAX_BEHAVIOR` | `inclusive` | `inclusive` or `exclusive`: whether the inline price includes tax. Any other value makes the purchase answer 503. Not used with `STRIPE_PRICE_ID`. |
| `FOODDB__BACKEND__STRIPE_TAX_CODE` | `txcd_10000000` | The Stripe tax code of the inline product. Not used with `STRIPE_PRICE_ID`. |
| `FOODDB__BACKEND__CREDITS_PER_PACK` | `100000` | The credits that one paid pack adds. |
| `FOODDB__BACKEND__STALE_AFTER_DAYS` | `730` | A nutrient value older than the newest one by more days than this loses its trust rank. |
| `FOODDB__BACKEND__REQUEST_LOG_DAYS` | `30` | The days that the request log keeps its rows. The worker deletes older rows every day at 03:15 UTC. |
| `FOODDB__BACKEND__DUMP_KEEP` | `3` | The number of monthly ODbL dumps to keep. |
| `FOODDB__BACKEND__LLM_API_KEY` | none | The OpenRouter key for label reads. Set it on the server yourself. Without it, label reads are demo reads, and every value waits for review. |
| `FOODDB__BACKEND__LLM_MODEL` | `qwen/qwen3-vl-235b-a22b-instruct` | The OpenRouter vision model. Our account reaches only x-ai and Chinese-vendor models. |
| `FOODDB__BACKEND__LABEL_READER` | `openrouter` with a key, else `demo` | The backend of the model port on the server. |
| `FOODDB__BACKEND__LABEL_CONFIDENCE_FLOOR` | `0.9` | A label read below this confidence has every value pending review. |
| `FOODDB__BACKEND__PHOTO_DIR` | `/app/photos` | Where the API stores label photos and the worker reads them. Compose sets it to the `photos` volume. Outside Compose, the default is `photos` in the working directory. |
| `FOODDB__BACKEND__FETCH_FDC_BRANDED` | `false` | `true`: fetch FDC Branded Foods at once and every week. See [First boot](#first-boot). |
| `FOODDB__BACKEND__FETCH_FINELI` | `false` | `true`: fetch Fineli at once and every week, from `FOODDB__BACKEND__FINELI_URL`. |
| `FOODDB__BACKEND__FINELI_URL` | `https://fineli.fi/fineli/content/file/47` | The Fineli open data zip, or a copy of it. |
| `FOODDB__BACKEND__DUMP_DIR` | `/app/dumps` | Where the worker writes the ODbL dumps and the API reads them. Compose sets it to the `dumps` volume. Outside Compose, the default is `dumps` in the working directory. |

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
- The export is a read. Give the consumer its own `read` key, with a `--rate-limit` that is
  sufficient for its sync. See [API keys](#api-keys).

## Label photos

`POST /v1/labels` stores each photo once, under its SHA-256, in the `fooddb_photos` volume. The
worker reads it with the model in `FOODDB__BACKEND__LABEL_READER`. A photo is at most 10 MiB, and
only JPEG, PNG and WebP pass. Back up the `fooddb_photos` volume with the database: each label
value names its photo in `observation.evidence`, and the review page at `/admin/labels` shows it.

1. Set `FOODDB__BACKEND__LLM_API_KEY` in `deploy/.env` on the server. Do not put it in a
   repository or a chat.
2. Run `docker compose up -d`.
3. Make a `contribute` key for each client that sends photos. See [API keys](#api-keys).

A read below `FOODDB__BACKEND__LABEL_CONFIDENCE_FLOOR` waits for review in full. Check the
**Label reads** page in `/admin` for these reads.

## ODbL dumps

The worker writes the ODbL dump of the Open Food Facts layer on the 1st of each month, at 04:00
UTC. It dumps the newest final snapshot day to the `fooddb_dumps` volume, and keeps the newest
`FOODDB__BACKEND__DUMP_KEEP` dumps. The API serves them at `/v1/dumps` with no API key, also when
reads need one. The ODbL requires this. [data-licence.md](data-licence.md) has the terms.

- To write a dump now: `docker compose exec worker fooddb dump odbl`.
- The dump reads about 7000 products per second. The worker stops a task after 1 hour. With the
  full OFF dump loaded (about 4 million products), that rate gives about 10 minutes. If a slow
  disk or a small database cache makes the job last more than 1 hour, run
  `docker compose exec worker fooddb dump odbl` from a host cron job on the 1st of each month.
- A stopped run leaves a `.part` file. The next run replaces it. The API never serves it.

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
