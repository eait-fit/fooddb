# fooddb: one image, three roles: `fooddb serve` (API), `fooddb worker` (pq jobs), `fooddb migrate`.
FROM python:3.14.8-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY data ./data
RUN uv sync --frozen --no-dev

FROM python:3.14.8-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170
RUN useradd --system --uid 10001 --home /app fooddb
WORKDIR /app
COPY --from=build --chown=fooddb /app /app
# The ODbL dumps and label photo volumes mount here; a fresh named volume takes this owner.
RUN install -d -o fooddb /app/dumps /app/photos
# The sha /version reports; the release workflow and `make update` pass it as a build arg.
ARG GIT_SHA=
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 FOODDB__BACKEND__API_HOST=0.0.0.0 FOODDB__BACKEND__API_PORT=8000 FOODDB__BACKEND__GIT_SHA=${GIT_SHA}
USER fooddb
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"FOODDB__BACKEND__API_PORT\"]}/livez', timeout=4)"
CMD ["fooddb", "serve"]
