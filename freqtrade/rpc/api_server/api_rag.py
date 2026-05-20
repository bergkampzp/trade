"""Sprint 1.5 — AI天团 RAG API.

提供知识库检索 + 文档上传 + 状态查询端点。
集成到现有的 Freqtrade FastAPI (:20080)。
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import chromadb
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer


logger = logging.getLogger(__name__)

router = APIRouter(tags=["rag"])

# ── Config ────────────────────────────────────────────────────────────
CHROMA_PATH = os.environ.get("CHROMA_PATH", "/var/lib/quant-data/chromadb")
COLLECTION_NAME = "tiantuan_knowledge_base"
EMBED_MODEL = "all-MiniLM-L6-v2"

# Lazy init
_collection = None
_model = None
SUPPORTED_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _get_collection():
    global _collection
    if _collection is None:
        os.makedirs(CHROMA_PATH, exist_ok=True)
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )
    return _collection


def _get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


# ── Import extract/chunk from ingest script ────────────────────────────


def _extract_text_from_bytes(content: bytes, filename: str) -> Optional[str]:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        import io

        import pdfplumber

        text_parts = []
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
            text = "\n\n".join(text_parts)
            if not text.strip():
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(content))
                text = "\n\n".join(p.extract_text() or "" for p in reader.pages)
            return text.strip() if text.strip() else None
        except Exception:
            return None

    elif ext == ".docx":
        import io

        from docx import Document

        try:
            doc = Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception:
            return None

    elif ext in (".txt", ".md"):
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return content.decode("gbk")
            except Exception:
                return None

    return None


def _add_document(text: str, source: str, collection) -> int:
    import hashlib

    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=100,
        separators=["\n\n", "\n", "。", "，", ".", ",", " ", ""],
    )
    docs = splitter.create_documents(
        [text], metadatas=[{"source": source, "file_name": Path(source).name}]
    )

    model = _get_model()
    ids, texts, metadatas, embeddings = [], [], [], []
    for i, doc in enumerate(docs):
        chunk_id = hashlib.md5(doc.page_content.encode()).hexdigest()[:16]
        ids.append(chunk_id)
        texts.append(doc.page_content)
        metadatas.append({**doc.metadata, "chunk_index": i})
        embeddings.append(model.encode(doc.page_content).tolist())

    if ids:
        collection.upsert(ids=ids, documents=texts, embeddings=embeddings, metadatas=metadatas)
    return len(ids)


# ── Pydantic Models ────────────────────────────────────────────────────


class RAGQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="检索查询")
    top_k: int = Field(default=5, ge=1, le=20, description="返回结果数")


class RAGChunk(BaseModel):
    text: str
    source: str
    file_name: str
    chunk_index: int
    score: float  # cosine distance (lower = more similar)


class RAGQueryResponse(BaseModel):
    query: str
    chunks: list[RAGChunk]


class RAGStatusResponse(BaseModel):
    collection: str
    total_chunks: int
    embedding_model: str


# ── Endpoints ──────────────────────────────────────────────────────────


@router.post("/rag/query", response_model=RAGQueryResponse)
def api_rag_query(req: RAGQueryRequest):
    """检索知识库，返回最相关的文档片段。"""
    try:
        col = _get_collection()
        model = _get_model()
        emb = model.encode([req.query]).tolist()
        results = col.query(query_embeddings=emb, n_results=req.top_k)
    except Exception as e:
        logger.exception("RAG query failed")
        raise HTTPException(500, f"检索失败: {e}")

    chunks = []
    if results["documents"] and results["documents"][0]:
        for doc, meta, dist in zip(
            results["documents"][0], results["metadatas"][0], results["distances"][0]
        ):
            chunks.append(
                RAGChunk(
                    text=doc,
                    source=meta.get("source", ""),
                    file_name=meta.get("file_name", ""),
                    chunk_index=meta.get("chunk_index", 0),
                    score=round(dist, 4),
                )
            )

    return RAGQueryResponse(query=req.query, chunks=chunks)


@router.post("/rag/upload")
async def api_rag_upload(file: UploadFile = File(...)):
    """上传文档到知识库。支持 PDF/DOCX/TXT/MD/XLSX。"""
    if file.content_type and file.content_type not in SUPPORTED_TYPES:
        raise HTTPException(400, f"不支持的文件类型: {file.content_type}")

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(400, "文件最大 50MB")

    text = _extract_text_from_bytes(content, file.filename or "upload")
    if not text:
        raise HTTPException(400, "无法提取文件文本内容")

    try:
        col = _get_collection()
        n = _add_document(text, file.filename or "upload", col)
    except Exception as e:
        logger.exception("RAG upload failed")
        raise HTTPException(500, f"文档索引失败: {e}")

    return {
        "status": "ok",
        "file_name": file.filename,
        "file_size": len(content),
        "chunks_added": n,
    }


@router.get("/rag/status", response_model=RAGStatusResponse)
def api_rag_status():
    """查询知识库状态。"""
    try:
        col = _get_collection()
    except Exception:
        return RAGStatusResponse(
            collection=COLLECTION_NAME, total_chunks=0, embedding_model=EMBED_MODEL
        )

    return RAGStatusResponse(
        collection=COLLECTION_NAME,
        total_chunks=col.count(),
        embedding_model=EMBED_MODEL,
    )
