FROM python:3.13.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/
RUN apt-get update && apt-get install --no-install-recommends -y git ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /service
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13.12-slim AS runtime
WORKDIR /service
COPY --from=build /service/.venv /service/.venv
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
ENV PATH="/service/.venv/bin:$PATH" PYTHONUNBUFFERED=1
RUN useradd --system --no-create-home service
USER service
CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8080"]
