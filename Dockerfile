FROM python:3.14-slim

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
# The platform proxy is the only ingress and reaches the app from a private
# 100.64.0.0/10 address, so it must be trusted for X-Forwarded-Proto and
# X-Forwarded-For; otherwise every request looks like plain http from the proxy.
ENV FORWARDED_ALLOW_IPS="*"
EXPOSE 8000
CMD ["fastapi", "run"]
