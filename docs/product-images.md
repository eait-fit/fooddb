# Product images

Where fooddb should keep pictures of products. The first consumer is the **Review** page
(`/admin/review`): a reviewer who sees a pending value next to the pack can judge it faster. API
customers may get image URLs later. Facts were checked on 2026-10-07 against the official pages
listed under [Sources](#sources), against real OFF data (one daily delta, the head of the full dump,
and the AWS key list), and against the code. What could not be verified is marked **unverified**.

## Summary

- **OFF images are free to hotlink for a reviewer's browser, and OFF documents no rule against it.**
  The only guidance is: do not bulk-download from `images.openfoodfacts.org` (use the AWS dataset),
  and fetch the size you need, not the full image.
- **The daily delta files and the dump carry the data to build the image URLs, but no URLs.** Our
  parser (`fetchers/off.py:118`, `ingest.Record` at `ingest.py:23`) reads none of it today. So the
  13k OFF records already stored have no image reference.
- **OFF images are CC BY-SA 3.0**, separate from the ODbL on the data. The licence is cheap while
  fooddb only shows the image to a logged-in reviewer. It matters when a customer gets the image.
- **Storage cost does not decide anything.** The full OFF layer is about 110 GB of 400 px images
  (170 GB at most). Every object store costs under EUR 7 a month for that. Operations and licence
  decide.
- **Recommendation for now:** store a few bytes of image reference per OFF record, hotlink the 400 px
  image from OFF in the admin, keep label and brand photos where they are. Mirror into an object
  store only when API customers get image URLs. Details in [Recommendation](#recommendation).

## What OFF exposes

### In the files we already read

A real delta (`openfoodfacts_products_1790404855_1790490413.json.gz`, 6,522 products) and the first
25 MB of the full dump (6,588 products) show these image keys. The dump is the same JSON as the
deltas.

| Key | Present | Content |
|---|---|---|
| `images` | yes | The structure below. |
| `last_image_t`, `last_image_dates_tags` | yes | Time of the newest upload. |
| `image_front_url`, `image_*_small_url`, `selected_images` | **no** | These exist only in API v2 answers, where OFF computes them from `images`. |

`images` comes in two shapes, and a parser has to read both:

- **New shape** (6,504 of 6,522 delta products, 1,418 of 6,588 dump-head products):
  `images.selected.<kind>.<lang>` with `rev`, `imgid` and `sizes` (`100`, `200`, `400`, `full`, each
  with width and height), and `images.uploaded.<imgid>` with `uploader`, `uploaded_t` and `sizes`.
  `<kind>` is `front`, `ingredients`, `nutrition` or `packaging`.
- **Old shape** (540 of the 6,588 dump-head products, none in the delta): top-level keys
  `front_<lang>`, `nutrition_<lang>`, and so on, with `rev` and `imgid`, plus numeric keys
  (`"1"`, `"2"`) with `uploader` and `uploaded_t`. No product had both shapes.

### URL scheme

OFF documents the scheme in [How to download product images][dl]. The folder is the barcode padded
to 13 digits and split `3/3/3/rest`; the file of a selected image is `<kind>_<lang>.<rev>.<size>.jpg`:

```
https://images.openfoodfacts.org/images/products/541/006/304/1813/front_fr.3.400.jpg
```

Verified: I built the URL of the front and nutrition image, at all four sizes, for 15 random
products of the delta from `kind`, `lang` and `rev`. All 120 answered 200. For `off:<gtin14>` the
folder comes from the 14 digits with one leading zero removed, the same rule that `review.html`
already applies to the OFF product link. The `rev` changes whenever a contributor re-selects, crops
or rotates, so a URL with a `rev` names one version. Whether OFF deletes old revisions is
**unverified**.

Response headers of the image host: `Link: <http://creativecommons.org/licenses/by-sa/3.0/>;
rel='license'; title='CC-BY-SA 3.0'`, `Access-Control-Allow-Origin: *`, `ETag`, `Last-Modified`, and
**no `Cache-Control`**. From Berlin, time to first byte was 100 to 200 ms (5 requests).

### Size and coverage

15 random delta products (recent edits, so the numbers lean to well-photographed products):

| Size | Front, mean (max) | Nutrition, mean (max) |
|---|---|---|
| 100 px high | 2.6 KB (4.1) | 2.5 KB (4.2) |
| 200 px | 7.7 KB (13.2) | 8.1 KB (14.5) |
| **400 px** | **22.6 KB (42.4)** | **26.1 KB (51.1)** |
| full | 384 KB (2,295) | 483 KB (2,256) |

Share of products with a selected image:

| Sample | Front | Nutrition |
|---|---|---|
| Delta, 6,522 products | 76 % | 55 % |
| Head of the dump, 6,588 products | 26 % | 16 % |

The dump head is ordered by barcode and starts with short, odd codes, so I do not trust it as a
sample of the whole. The AWS key list is firmer: **3,612,280 product folders hold at least one raw
image**. The share with a *selected front or nutrition* image across the whole dump is
**unverified**. The estimates below use the delta rates as the expected case and "both images for
every product" as the ceiling.

### The AWS dataset is raw images only

The bucket `openfoodfacts-images` (eu-west-3) is the sanctioned route for bulk. I read its key list
(`data_keys.gz`, last modified 2026-10-03, 29,972,731 keys): 9,991,449 raw full images
(`<imgid>.jpg`), 9,991,695 raw 400 px images (`<imgid>.400.jpg`) and 9,989,587 OCR files. **There
are no selected images** (`front_fr.3.400.jpg`) in it. The bucket is synced monthly, so recent
uploads can be missing. A selected image is the raw one after the contributor's crop and rotation,
so the raw 400 px image of `imgid` is a close but not identical substitute. For the same 15
products, all 30 raw 400 px images were in the bucket (mean 23.7 KB).

## Terms and licence

| Question | Finding | Source |
|---|---|---|
| Image licence | CC BY-SA 3.0. The data is ODbL and the data contents DbCL. Contributors place their photos under CC BY-SA. | [terms of use][terms], [API intro][api] |
| Attribution | Name the licence and credit Open Food Facts with a link to openfoodfacts.org, a local version or the product page. Also needed for derivative works. | terms of use, "Authorship and attribution" |
| Share alike | "Derivative works must be shared under the same conditions." | terms of use |
| Third-party rights | The licence covers only the photographer's rights. Packaging design, trademarks and people on the pack can carry other rights, and the re-user must check them. | terms of use, "Licence restriction" |
| Hotlinking | **No rule found** in the terms, the API introduction or the image download guide. | pages above |
| Bulk | Up to about 10 images: download from the OFF server. More: use the AWS dataset. Fetch the size you need. On the OFF server, download one image at a time. | [image guide][dl] |
| Rate limits | 15 requests a minute per IP for product reads, 10 for search. They cover `GET /api/v*/product`, not the image host. A custom `User-Agent` of the form `App/Version (email)` is required. | [API intro][api] |

What CC BY-SA 3.0 asks, from the [legal code][ccbysa] (section 4):

- Unchanged work: keep the copyright notices, give the author name if supplied, the title, the URI of
  the work, and a copy or link of the licence. Do not apply "effective technological measures" that
  stop a recipient from using the rights the licence gives.
- Adaptation (a crop, a resize, an overlay): same licence, and the change must be labelled.
- A **Collection** is not an Adaptation. The work inside keeps the licence, and the Collection
  around it need not take it. Whether a food database that links or embeds images is a Collection is
  a legal question, not one I can answer.

The ODbL does not reach the images. Its section 2.4 says the licence does not cover rights in
individual contents. Thus the images stay CC BY-SA whatever the licence of our database, and a
reference to an image is data we derived from OFF (ODbL), while the bytes are not.

## Options

All sizes are 400 px front plus nutrition. Scenarios: **now** is 13k products (0.4 GB, 17k
objects); **full, expected** is 3.5M products at the delta coverage (110 GB, 4.6M objects);
**full, ceiling** is 3.5M products with both images (170 GB, 7M objects). Full size is out of the
question: it would be 0.6 to 1.9 TB.

### a. Store the OFF URL only, hotlink

What is stored: for each OFF record, `kind`, `lang`, `rev` and the uploader name, about 60 bytes
(about 200 MB at 3.5M products). The browser fetches from `images.openfoodfacts.org`.

| | |
|---|---|
| Cost | EUR 0. |
| Operations | None. OFF carries storage, bandwidth and uptime. |
| Backup | Nothing to back up, the reference is re-derivable from OFF. |
| Admin latency | 100 to 200 ms for the first byte, a page of 25 cards is about 1.2 MB. The browser caches by `ETag`. |
| Licence | We distribute no bytes. The reviewer's browser gets them from OFF. |
| Risks | OFF can break, move or remove an image, and the card then shows nothing. The browser sends the reviewer's IP (and, unless told not to, the referrer) to OFF. |
| Needs | An image field in `ingest.Record` and the parser. For the 13k records already stored: a backfill (below). |

Backfill. The deltas rotate after about two weeks, and the 13k records were read from them. The
only complete source is the 13 GB dump. For just the products that have pending values, the API
works: `GET /api/v2/product/{code}?fields=images`, throttled under 15 a minute, cached in the
database after the first read.

### b. Mirror the selected images into object storage

Prices from the providers' own pages, checked 2026-10-07. A Hetzner price row marked (secondary)
comes from news reports, because the Hetzner pages build their price tables with JavaScript that
I could not read.

| Store | Storage | Egress | Requests | Monthly, now | Monthly, full expected / ceiling | One-off PUTs, expected / ceiling |
|---|---|---|---|---|---|---|
| Cloudflare R2 | USD 0.015/GB, 10 GB free ([R2][r2]) | free | Class A USD 4.50/M, B USD 0.36/M, 1M and 10M free | 0 | USD 1.50 / 2.40 | USD 16 / 27 |
| Backblaze B2 | USD 6.95/TB, 10 GB free ([B2][b2]) | free up to 3x stored, then USD 0.01/GB | Class A, B, C free | 0 | USD 0.7 / 1.1 | 0 |
| Hetzner Object Storage | EUR 6.49 a month base, includes 1 TB storage and 1 TB egress (secondary: [heise][heise] for the launch price EUR 4.99, [bex.co][bex] for the April 2026 rise) | 1 TB included; traffic inside `eu-central` free ([docs][hz-os]) | S3 operations free | EUR 6.49 | EUR 6.49 / 6.49 | 0 |
| AWS S3 Standard, Frankfurt | USD 0.0245/GB ([price list][s3]) | USD 0.09/GB after 100 GB a month free ([data transfer][s3dt]) | PUT USD 5.40 per million, GET USD 0.43 per million | USD 0.01 | USD 2.70 / 4.17 | USD 25 / 38 |

Operational notes:

- The one-off PUT cost is small next to the time. Fetching 4.6M images from `images.openfoodfacts.org`
  at 5 a second takes 10 days, and OFF asks for one request at a time. The AWS bucket is fast and
  concurrent but has raw images only, and 4.6M objects of selected crops are not in it.
- A key such as `off/<gtin14>/<kind>_<lang>.<rev>.400.jpg` needs no hashing: the `rev` already names a
  version. Under it the mirror is a cache of a public source. It needs no backup and can be rebuilt.
- R2's `r2.dev` URL is rate-limited and "for development purposes only". Production needs a custom
  domain on Cloudflare ([public buckets][r2pub]), which also gives caching.
- Hetzner Object Storage has a 50 million object limit per bucket ([product page][hz-os-page]), far
  above our need.
- The ieat-app runbook already describes an R2 bucket for restic backups
  (`ieat-app/docs/DEPLOY.md`, "Off the box: restic → R2"), so a Cloudflare account and a credential
  pattern exist. Whether the offsite backup is switched on is **unverified**.

### c. Local disk on the VPS, next to the label photos

The code is `labels/photos.py` generalised: content-addressed, atomic write, one directory.

| | |
|---|---|
| Fit | Now: 0.4 GB, no problem. Full: 110 to 170 GB. The eait runbook sizes the box at a Hetzner CX22 with a 40 GB disk (`ieat-app/docs/DEPLOY.md:19`); the real disk is **unverified**, and the host is shared with Tailscale, a gateway and a host Postgres (`deploy/iac/README.md`). It does not fit without a volume. |
| Cost | A Hetzner Volume is about EUR 0.057/GB a month after the April 2026 rise (secondary: [Hetzner price notice summary][bex]), so EUR 6 to 10 for 110 to 170 GB. |
| Backup | **Hetzner Backups and Snapshots do not include Volumes**, and Hetzner offers no backup for Volumes ([docs][hz-vol]). The existing `backup.sh` tars the whole photo volume every night, which would grow from MB to 100 GB. A mirror needs no backup, so it must stay out of that tar. |
| Latency | Best: same host. |
| Licence | We distribute the bytes only if we serve them, same as any mirror. |

It works for a few thousand images and fails on scale and on backup scope. It adds nothing over (a)
until images are needed beyond the admin.

### d. Postgres `bytea` or large objects

Rejected, with numbers:

- 13k products add about 0.4 GB, twice the 210 MB that the whole database held after the first boot
  (`docs/deploy.md`). The full layer adds 110 to 170 GB, about 500 to 800 times that.
- Every image above 2 KB goes to TOAST, 4.6 to 7M rows of out-of-line values that `pg_dump` copies
  every night. The documented backup is one `pg_dump -Fc`, and a restore replays all of it.
- The data is re-derivable and public, so nothing is gained from the transactional storage of
  Postgres. `shared_buffers` and WAL carry the load of every image read and write.
- The ieat-app runbook makes the same point for its own photos (`bytes` in `meal_photos`, about 200 KB
  each): "move `bytes` to R2 ... and keep `meal_photos` as metadata".

### Label and brand photos that we own

`label:<sha>` and `brand:<gtin14>` photos are different data. They are **evidence**: each label value
names its photo in `observation.evidence`, and a reviewer needs it to judge the read. They cannot be
re-derived, and they belong to a contributor, not to OFF. Their licence is `LicenseRef-fooddb`.

- Keep them on local disk now. The store is three functions (`store`, `load`, `_path` in
  `photos.py`), already backed up by the ieat-app tar, and the admin route
  (`admin.py:213`) already checks the login.
- Move them to the same bucket only when (1) the nightly tar becomes the main backup cost, or (2) a
  second API replica needs the same files. Use a **private** bucket, content-addressed under the
  SHA-256 as today, and short-lived signed URLs or an app proxy. A mirror of OFF images and the
  photos then sit in different buckets: one public and rebuildable, one private and backed up.
- `photos.store` writes the uploaded bytes unchanged, so **EXIF (GPS position, device) is kept**.
  This is harmless while only a reviewer sees the file. Strip EXIF before any photo is served to a
  customer.
- A brand photo may only be shown to customers if the upload terms say so. They do not today
  (**unverified**; I did not find upload terms in the docs).

## Serving

### In the admin, now

| Way | Fits |
|---|---|
| Direct `<img src>` to OFF | Yes for OFF images. Add `loading="lazy"` and `referrerpolicy="no-referrer"`, so OFF does not learn the admin URL. The admin sets `Referrer-Policy` only on the API and the portal (`api.py:242`, `portal.py:24`). The repo sets no CSP, so no `img-src` rule blocks it. |
| Proxy through the app (as `/admin/review/photo/{sha}`) | Needed for private photos. For OFF images it adds a hop, code and load on our host, and the requests still go to OFF, now from one IP. |
| Signed URLs | Needed only for a private bucket. Not needed while the files are on local disk behind the admin login. |
| Public bucket on a custom domain | The shape for a mirror. Nothing secret in it. |

On the card, show the images the way the card shows its source link (`review.html`): the front image
for identity, the nutrition image for the numbers, each linking to the full OFF product page, with
the credit "Open Food Facts, CC BY-SA 3.0" under it. This also makes the admin comply with the
attribution rule at no cost.

### If API customers get images

Follow the existing licence-tag decision (2026-10-05): each served field is `{value, source,
licence, record}`. An image is the same:

```json
{"kind": "front", "lang": "fr", "url": "...", "source": "off", "licence": "CC-BY-SA-3.0",
 "author": "kiliweb", "record": "off:03168930010883", "attribution": "Open Food Facts, openfoodfacts.org/product/3168930010883"}
```

- **Only with `include=off`**, like the OFF values. A default answer then has no CC BY-SA content.
- The ODbL dump may include the image *reference* (it is ODbL data). It must not include bytes.
- **Do not put the images behind API keys or credits.** Section 4(a) forbids effective technological
  measures on the work that restrict a recipient's use. A paid wall around a copy of CC BY-SA files
  is at least a risk. Return a public URL, uncharged. This is **a question for legal review**.
- What customers must do, to be written into [data-licence.md](data-licence.md): show the credit and
  the licence, keep it with the image, and share any *modified* image (crop, overlay, compression
  that changes pixels) under CC BY-SA. Their app, their own data and the images used unchanged are
  not affected, by the Collection rule. They must also check third-party rights on the pack,
  which OFF leaves to the re-user.
- Two ways to deliver, in order of legal risk: (1) return OFF's own URL, so we distribute nothing.
  Customers' end users then hit OFF, against its bulk guidance, and a popular app would load OFF.
  (2) return our mirror's URL. We distribute, we carry the attribution and the load, and we control
  availability.

## Recommendation

**For the admin Review page (now):**

1. Add the image reference to the OFF record at ingest: from `images.selected.front` and
   `images.selected.nutrition` (new shape) or `front_<lang>` and `nutrition_<lang>` (old shape), take
   `lang`, `rev`, and the uploader of `imgid`. About 60 bytes a record, no new service.
2. Show the 400 px front and nutrition images on OFF-record cards, hotlinked from
   `images.openfoodfacts.org`, lazy, with `referrerpolicy="no-referrer"` and the credit line.
3. For the 13k records already stored, fetch `fields=images` from the API for a product when its
   card first needs it, under the 15 a minute limit and with our `User-Agent`, and store the result.
   A full-dump reload backfills the rest.
4. Leave `label:` and `brand:` photos on local disk.

Cost: EUR 0 a month, no new infrastructure, no backup change, and no bytes distributed by us.

**Switch to a mirror when** API customers are to receive image URLs, or earlier if hotlinks to OFF
fail visibly (broken cards), or if answers must be reproducible by `?snapshot=` (a hotlink changes
when a contributor re-selects an image). Then:

- Store: **Cloudflare R2 with a custom domain**, public bucket, key `off/<gtin14>/<kind>_<lang>.<rev>.400.jpg`.
  Reason: zero egress, USD 1.50 to 2.40 a month at full scale, an R2 credential pattern already
  documented in ieat-app (in use is unverified), and caching from the custom domain. The alternative is Hetzner Object
  Storage at EUR 6.49 flat, to stay in one EU provider with the VPS and avoid a second vendor, at
  about 4 times the cost. B2 is the cheapest at about USD 1 but has no edge cache and its egress is
  free only up to 3x stored data. Do not use S3: it is the dearest and has no advantage for us.
- Fill: lazily. The first API read of a product that returns an image copies it from OFF, one request
  at a time. Do not bulk-crawl `images.openfoodfacts.org`. For a bulk start, use the AWS raw 400 px
  image by `imgid` and accept uncropped images, or ask OFF.
- Backup: none. It is a cache of a public source.
- Licence: tag each image as above, publish the credit text in `data-licence.md`.

## Decisions for Kirill

1. **Legal: CC BY-SA on images that we serve to customers.** Is a food database that returns
   image URLs a Collection or an Adaptation under CC BY-SA 3.0? Is an API-key wall around a mirror of
   the images a "technological measure"? This extends item 2 of "Open" in
   [decisions.md](decisions.md) (legal review of ODbL reach and OFF photos). No customer image
   before the answer. The admin needs no ruling.
2. **Cost: the object store**, only at the switch. The numbers say R2 (cheapest with an edge cache)
   or Hetzner (one vendor, EUR 6.49 flat). It is a choice of vendor spread, not of money.
3. **Whether to mirror at all**, or to give customers OFF's own URLs. The second distributes
   nothing and costs nothing, and it pushes load to OFF and breaks when OFF changes.
4. **Brand and label photos for customers**: whether the upload terms may allow showing them, and
   whether to strip EXIF at upload now, which is cheap and has no downside.

## Not verified

- Hetzner storage prices (Object Storage EUR 6.49, Volumes EUR 0.057/GB): the Hetzner pages render
  prices with JavaScript, and the HTML I fetched has none. Both come from news reports. Check
  hetzner.com before deciding. The price of extra Object Storage beyond 1 TB after the April 2026
  rise is not known to me.
- Whether OFF's image host rate-limits. I made about 160 requests at 2 to 3 a second over a few
  minutes with no error, which is not a test.
- Whether OFF deletes old `rev` files, and the full-dump share of products with a selected front
  or nutrition image.
- The real disk size, free space and backup settings of the production VPS. I did not touch it.
- Presigned URL support and limits per provider.
- Legal conclusions above. They are a reading of the texts, not legal advice.

## Sources

[terms]: https://world.openfoodfacts.org/terms-of-use
[api]: https://openfoodfacts.github.io/openfoodfacts-server/api/
[dl]: https://openfoodfacts.github.io/openfoodfacts-server/api/how-to-download-images/
[aws]: https://openfoodfacts.github.io/openfoodfacts-server/api/aws-images-dataset/
[ccbysa]: https://creativecommons.org/licenses/by-sa/3.0/legalcode
[odbl]: https://opendatacommons.org/licenses/odbl/1-0/
[r2]: https://developers.cloudflare.com/r2/pricing/
[r2pub]: https://developers.cloudflare.com/r2/buckets/public-buckets/
[b2]: https://www.backblaze.com/cloud-storage/pricing
[s3]: https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonS3/current/eu-central-1/index.json
[s3dt]: https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSDataTransfer/current/eu-central-1/index.json
[hz-os]: https://docs.hetzner.com/storage/object-storage/overview/
[hz-os-page]: https://www.hetzner.com/storage/object-storage/
[hz-vol]: https://docs.hetzner.com/cloud/volumes/overview/
[heise]: https://www.heise.de/en/news/Alternative-to-Amazon-S3-Hetzner-offers-object-storage-10189226.html
[bex]: https://bex.co/blog/2026/08/16/hetzner-2026-price-shocks-owning-hardware-pitch

- Open Food Facts: [terms of use][terms]; [API introduction][api] (licences, rate limits,
  `User-Agent`); [How to download product images][dl]; [AWS images dataset][aws].
- [CC BY-SA 3.0 legal code][ccbysa]; [ODbL 1.0][odbl] (sections 2.4, 4.4, 4.5).
- Prices: [R2][r2], [B2][b2], [S3 price list for eu-central-1][s3] (storage, requests) and
  [data transfer][s3dt] (price lists read as JSON), [Hetzner Object Storage docs][hz-os] and
  [product page][hz-os-page] (limits, included quota), [Hetzner Volumes][hz-vol] (no backups).
  Secondary for Hetzner prices: [heise][heise], [bex.co][bex].
- Measured: the OFF delta `openfoodfacts_products_1790404855_1790490413.json.gz`, the first 25 MB of
  `openfoodfacts-products.jsonl.gz`, `data_keys.gz` of the AWS bucket (2026-10-03), 120 image
  requests to `images.openfoodfacts.org` and 30 to the AWS bucket, by a script with the
  `User-Agent` `fooddb-research/0.1`.
- In the repo: `src/fooddb/fetchers/off.py`, `src/fooddb/ingest.py`, `src/fooddb/labels/photos.py`,
  `src/fooddb/admin.py:213`, `src/fooddb/templates/review.html`, [decisions.md](decisions.md),
  [data-licence.md](data-licence.md), [deploy.md](deploy.md). In ieat-app: `docs/DEPLOY.md`,
  `deploy/backup.sh`, `deploy/iac/README.md`.
