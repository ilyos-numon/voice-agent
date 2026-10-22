FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PIPELINE_MODE=stub FAQ_PATH=data/faq/sample_faq.json PORT=8765
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY data ./data
RUN uv sync --frozen --no-dev
EXPOSE 8765
CMD ["/srv/.venv/bin/uvicorn", "app.main:app", "--host", "::", "--port", "8765"]
