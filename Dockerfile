FROM python:3.14-slim

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY parse_apis ./parse_apis
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
# Trust X-Forwarded-Proto/-For only from the platform proxy's own network
# (RFC 6598 shared address space). Without this every request looks like plain
# http from the proxy; with "*" any direct caller could instead spoof its
# apparent address and scheme.
ENV FORWARDED_ALLOW_IPS="100.64.0.0/10"
EXPOSE 8000
CMD ["fastapi", "run"]
