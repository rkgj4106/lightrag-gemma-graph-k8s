FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache \
    WORKING_DIR=/data/rag_storage

WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

# Download the tokenizer during build so Pods need only access to Ollama.
# This tokenizer measures LightRAG chunks; inference still runs on Gemma.
RUN python -c "import tiktoken; tiktoken.encoding_for_model('gpt-4o-mini')"

COPY app.py index.html graph.js questions.json ./
COPY docs ./docs
RUN mkdir -p /data/rag_storage

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
