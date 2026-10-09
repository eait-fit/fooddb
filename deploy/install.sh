#!/bin/sh
# Install fooddb with Docker Compose and wait until the API answers.
#   curl -fsSL https://raw.githubusercontent.com/eait-fit/fooddb/main/deploy/install.sh | sh
# Settings (environment):
#   FOODDB_DIR   where the code goes (default ./fooddb)
#   FOODDB_REF   branch or tag to install (default main)
#   FOODDB_SRC   copy the code from this local path instead of GitHub (for testing the installer)
#   FOODDB__DEPLOY__PORT, FOODDB__DEPLOY__BIND, FOODDB__DEPLOY__IMAGE: as in deploy/.env.example
set -eu

REPO=eait-fit/fooddb
DIR=${FOODDB_DIR:-./fooddb}
REF=${FOODDB_REF:-main}
TIMEOUT=900

die() {
    printf 'fooddb install: %s\n' "$*" >&2
    exit 1
}

need() {
    command -v "$1" >/dev/null 2>&1 || die "$1 is missing. $2"
}

need docker "Install Docker: https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || die "docker compose v2 is missing. Install the Compose plugin: https://docs.docker.com/compose/install/"
docker info >/dev/null 2>&1 || die "the Docker daemon is not reachable. Start Docker, or add your user to the docker group."
need curl "Install curl with your package manager."
if [ -z "${FOODDB_SRC:-}" ] && ! command -v git >/dev/null 2>&1; then
    need tar "Install git or tar with your package manager."
fi

random_hex() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex "$1"
    else
        od -An -N"$1" -tx1 /dev/urandom | tr -d ' \n'
    fi
}

fill() {
    if grep -q "^$1=\$" .env; then
        sed -i.bak "s/^$1=\$/$1=$(random_hex "$2")/" .env
        rm -f .env.bak
    fi
}

if [ -f "$DIR/deploy/docker-compose.yml" ]; then
    echo "Using the existing checkout in $DIR."
elif [ -e "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ]; then
    die "$DIR exists and is not a fooddb checkout. Set FOODDB_DIR to another path."
else
    mkdir -p "$DIR"
    if [ -n "${FOODDB_SRC:-}" ]; then
        tar -C "$FOODDB_SRC" --exclude=.git --exclude=deploy/.env -cf - . | tar -C "$DIR" -xf -
    elif command -v git >/dev/null 2>&1; then
        git clone --quiet --depth 1 --branch "$REF" "https://github.com/$REPO.git" "$DIR"
    else
        curl -fsSL "https://github.com/$REPO/archive/$REF.tar.gz" | tar -xz --strip-components=1 -C "$DIR"
    fi
fi

cd "$DIR/deploy"
[ -f .env ] || cp .env.example .env
fill FOODDB__BACKEND__POSTGRES_PASSWORD 24
fill FOODDB__BACKEND__SECRET_KEY 32

echo "Building and starting the stack. The first build takes a few minutes."
docker compose up -d --build

PORT=${FOODDB__DEPLOY__PORT:-$(sed -n 's/^FOODDB__DEPLOY__PORT=//p' .env | tail -1)}
PORT=${PORT:-8000}
URL=http://127.0.0.1:$PORT

printf 'Waiting for %s/healthz. The worker downloads the first data, which takes a few minutes.' "$URL"
waited=0
until [ "$(curl -s -o /dev/null -w '%{http_code}' "$URL/healthz" || true)" = 200 ]; do
    if [ "$waited" -ge "$TIMEOUT" ]; then
        printf '\n'
        die "no answer after $((TIMEOUT / 60)) minutes. See the logs: docker compose -f $DIR/deploy/docker-compose.yml logs -f worker"
    fi
    printf '.'
    sleep 5
    waited=$((waited + 5))
done
printf '\nfooddb is up after %s s.\n\nTry it:\n\n  curl "%s/v1/foods?q=apple+pie&limit=1"\n  docker compose -f %s/deploy/docker-compose.yml exec api fooddb search "apple pie" --limit 1\n' \
    "$waited" "$URL" "$DIR"
