"""LightRAG + Ollama local lab. CLI: python app.py --help"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from lightrag import LightRAG, QueryParam
from lightrag.llm.ollama import ollama_model_complete
from lightrag.utils import EmbeddingFunc
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)
HOST = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
MODEL = os.getenv("LLM_MODEL", "gemma3:12b")
EMBED = os.getenv("EMBED_MODEL", "bge-m3")
CTX = int(os.getenv("NUM_CTX", "16384"))
TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "900"))
STORAGE = Path(os.getenv("WORKING_DIR", "./rag_storage")).expanduser()
if not STORAGE.is_absolute():
    STORAGE = ROOT / STORAGE

MODES = {"naive", "local", "global", "hybrid", "mix"}
RULES = (
    "Answer in English. Use only facts found in the retrieved documents. "
    "If a relationship involves multiple steps, explain the connection path. "
    "Do not guess telephone numbers, dates, or monetary amounts that are not "
    "provided in the documents; state that they cannot be verified. "
    "If sources are provided, include the document names."
)


async def embed(texts: list[str]) -> np.ndarray:
    # Gemma is used for generation/extraction; bge-m3 is used only for embeddings.
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as client:
        response = await client.post(f"{HOST}/api/embed", json={
            "model": EMBED, "input": texts, "truncate": False,
            "keep_alive": "30m",
        })
        response.raise_for_status()
        vectors = np.asarray(response.json()["embeddings"], dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] != len(texts):
        raise RuntimeError("Ollama did not return a valid embedding array.")
    return vectors


async def check_ollama() -> int:
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            response = await client.get(f"{HOST}/api/tags")
            response.raise_for_status()
            available = {m["name"] for m in response.json().get("models", [])}
        for name in (MODEL, EMBED):
            resolved = name if ":" in name else f"{name}:latest"
            if name not in available and resolved not in available:
                raise RuntimeError(
                    f"Model not found: {name}. "
                    f"Run ollama pull {name} on the Ollama server."
                )
        return int((await embed(["An English sentence for testing connectivity."])).shape[1])
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Ollama connection/embedding failed: {HOST}. "
            f"Check the server URL and models. {exc}"
        ) from exc


async def create_rag() -> LightRAG:
    if CTX < 16384:
        raise RuntimeError("This lab requires NUM_CTX=16384 or higher.")
    dim = await check_ollama()
    STORAGE.mkdir(parents=True, exist_ok=True)
    config_file = STORAGE / "lab_config.json"
    config = {
        "llm_model": MODEL,
        "embedding_model": EMBED,
        "embedding_dim": dim,
        "chunk_token_size": 500,
        "chunk_overlap_token_size": 60,
    }
    if config_file.exists():
        if json.loads(config_file.read_text(encoding="utf-8")) != config:
            raise RuntimeError(
                "The model/chunking settings differ from those of the existing index. "
                "Set WORKING_DIR in .env to a new folder and run ingest."
            )
    else:
        config_file.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    rag = LightRAG(
        working_dir=str(STORAGE),
        llm_model_func=ollama_model_complete,
        llm_model_name=MODEL,
        llm_model_max_async=1,
        default_llm_timeout=int(TIMEOUT),
        default_embedding_timeout=int(TIMEOUT),
        max_parallel_insert=1,
        llm_model_kwargs={
            "host": HOST,
            "timeout": TIMEOUT,
            "options": {
                "num_ctx": CTX,
                "temperature": 0,
                "num_predict": 4096,
            },
            "keep_alive": "30m",
        },
        embedding_func=EmbeddingFunc(
            embedding_dim=dim,
            max_token_size=2048,
            model_name=EMBED,
            func=embed,
        ),
        embedding_func_max_async=1,
        chunk_token_size=500,
        chunk_overlap_token_size=60,
        entity_extract_max_gleaning=1,
        entity_extraction_use_json=False,
        summary_max_tokens=1024,
        addon_params={"language": "English"},
    )
    await rag.initialize_storages()
    return rag


async def ingest(rag: LightRAG) -> dict:
    files = sorted((ROOT / "docs").glob("*.txt"))
    if not files:
        raise RuntimeError("Place UTF-8 .txt documents in the docs folder.")
    manifest_file = STORAGE / "lab_documents.json"
    manifest = (
        json.loads(manifest_file.read_text(encoding="utf-8"))
        if manifest_file.exists()
        else {}
    )
    texts = {p.name: p.read_text(encoding="utf-8-sig") for p in files}
    hashes = {
        name: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for name, text in texts.items()
    }
    for name, digest in hashes.items():
        if name in manifest and manifest[name] != digest:
            raise RuntimeError(
                f"The content of an existing document has changed: {name}. "
                "Run ingest again using a new WORKING_DIR."
            )
    # Avoid LightRAG creating duplicate document failure records on repeated ingestion.
    # Persist each successful file so a later failure does not re-submit earlier files.
    for name, text in texts.items():
        if name in manifest or hashes[name] in manifest.values():
            print(f"Skipped (content already processed): {name}", flush=True)
            continue
        print(f"Processing document: {name}", flush=True)
        await rag.ainsert(text, file_paths=name)
        counts = await rag.doc_status.get_status_counts()
        if any(int(value) for key, value in counts.items() if key != "processed"):
            raise RuntimeError(
                f"Document processing failed or is incomplete: {counts}. "
                "Retry using a new WORKING_DIR."
            )
        manifest[name] = hashes[name]
        temporary = manifest_file.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(manifest_file)
    counts = await rag.doc_status.get_status_counts()
    print("Document processing status:", counts, flush=True)
    # ainsert can record failures instead of raising; never silently report success.
    if any(int(value) for key, value in counts.items() if key != "processed"):
        raise RuntimeError(
            f"Indexing is incomplete: {counts}. Check the LightRAG logs above."
        )
    return counts


async def require_index(rag: LightRAG):
    counts = await rag.doc_status.get_status_counts()
    if not int(counts.get("processed", 0)):
        raise RuntimeError("No index found. Run python app.py ingest first.")


async def ask(rag: LightRAG, question: str, mode: str, context_only=False):
    if mode not in MODES:
        raise ValueError(f"Unsupported mode: {mode}")
    await require_index(rag)
    started = time.perf_counter()
    result = await rag.aquery(question, param=QueryParam(
        mode=mode,
        only_need_context=context_only,
        stream=False,
        top_k=12,
        chunk_top_k=8,
        max_entity_tokens=2000,
        max_relation_tokens=2500,
        max_total_tokens=7000,
        enable_rerank=False,
        include_references=True,
        user_prompt=RULES,
        response_type=(
            "A concise English answer with supporting evidence "
            "and relationship connection paths"
        ),
    ))
    return {
        "mode": mode,
        "seconds": round(time.perf_counter() - started, 2),
        "result": result,
    }


def graph_data():
    import networkx as nx
    paths = list(STORAGE.rglob("*.graphml"))
    if not paths:
        return {
            "nodes": [],
            "edges": [],
            "message": "No graph file is available yet.",
        }
    graph = nx.read_graphml(paths[0])
    return {
        "directed": graph.is_directed(),
        "nodes": [
            {"id": str(n), **dict(d)}
            for n, d in graph.nodes(data=True)
        ],
        "edges": [
            {"source": str(s), "target": str(t), **dict(d)}
            for s, t, d in graph.edges(data=True)
        ],
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    rag = await create_rag()
    app.state.rag = rag
    app.state.lock = asyncio.Lock()
    try:
        yield
    finally:
        await rag.finalize_storages()


app = FastAPI(title="Gemma 3 + LightRAG Lab", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=3000)
    mode: str = "mix"
    context_only: bool = False


@app.get("/", response_class=HTMLResponse)
async def home():
    return (ROOT / "index.html").read_text(encoding="utf-8")


@app.get("/graph.js")
async def graph_script():
    return Response(
        (ROOT / "graph.js").read_text(encoding="utf-8"),
        media_type="application/javascript",
    )


@app.get("/api/questions")
async def questions():
    return json.loads((ROOT / "questions.json").read_text(encoding="utf-8"))


@app.get("/healthz")
async def health():
    # Local process health; a remote Ollama outage must not cause restart loops.
    return {"status": "ok"}


@app.get("/readyz")
async def ready():
    counts = await app.state.rag.doc_status.get_status_counts()
    if not int(counts.get("processed", 0)):
        raise HTTPException(503, "No document index is available yet.")
    return {"status": "ready", "documents": counts}


@app.get("/api/graph")
async def graph():
    return graph_data()


@app.post("/api/ask")
async def web_ask(body: AskRequest):
    if body.mode not in MODES:
        raise HTTPException(400, "Unsupported retrieval mode.")
    if not body.question.strip():
        raise HTTPException(400, "Please enter a question.")
    try:
        async with app.state.lock:
            return await ask(
                app.state.rag,
                body.question.strip(),
                body.mode,
                body.context_only,
            )
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


async def cli(args):
    if args.command == "graph":
        print(json.dumps(graph_data(), ensure_ascii=False, indent=2))
        return
    if args.command == "check":
        dim = await check_ollama()
        print(
            f"Connection successful: {HOST}\n"
            f"Answer generation/relationship extraction: {MODEL}\n"
            f"Embedding: {EMBED}, {dim} dimensions"
        )
        return
    rag = await create_rag()
    try:
        if args.command == "ingest":
            await ingest(rag)
        elif args.command == "ask":
            print(json.dumps(
                await ask(rag, args.question, args.mode, args.context),
                ensure_ascii=False,
                indent=2,
            ))
        elif args.command == "compare":
            for mode in ("naive", "hybrid", "mix"):
                print(json.dumps(
                    await ask(rag, args.question, mode, args.context),
                    ensure_ascii=False,
                    indent=2,
                ), flush=True)
    finally:
        await rag.finalize_storages()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Gemma 3 12B + LightRAG English Lab"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "ingest", "graph"):
        sub.add_parser(name)
    for name in ("ask", "compare"):
        p = sub.add_parser(name)
        p.add_argument("question")
        p.add_argument(
            "--context",
            action="store_true",
            help="Output the retrieved context instead of generating an answer",
        )
        if name == "ask":
            p.add_argument("--mode", choices=sorted(MODES), default="mix")
    args = parser.parse_args()
    try:
        asyncio.run(cli(args))
    except (RuntimeError, ValueError, httpx.HTTPError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)