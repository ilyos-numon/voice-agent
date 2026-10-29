FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
ARG WARM_MODELS=1
RUN useradd -m -u 1000 user
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1 PORT=8765 \
    PATH=/srv/.venv/bin:$PATH \
    HOME=/home/user \
    HF_HOME=/home/user/.cache/huggingface \
    DEMO_MODE=1 \
    DEMO_TRUSTED_PROXY_HOPS=1 \
    LLM_BACKEND=qwen \
    AGENT_SUMMARY_DEFAULT=1 \
    STT_BACKEND=whisper \
    TTS_BACKEND=supertonic \
    RETRIEVER_BACKEND=bm25 \
    FAQ_PATH=data/faq/faq.jsonl
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra stt --extra tts --no-install-project
COPY app ./app
COPY data ./data
COPY scripts/warm_models.py ./scripts/warm_models.py
RUN uv sync --frozen --no-dev --extra stt --extra tts
RUN mkdir -p "$HF_HOME" && chown -R user:user /home/user
USER user
RUN if [ "$WARM_MODELS" = "1" ]; then python scripts/warm_models.py; fi
EXPOSE 8765
CMD ["/srv/.venv/bin/uvicorn", "app.main:app", "--host", "", "--port", "8765", "--no-server-header", "--no-access-log", "--no-proxy-headers"]
