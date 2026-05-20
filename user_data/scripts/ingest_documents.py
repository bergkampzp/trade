#!/usr/bin/env python3
"""Sprint 1.4 — AI天团 ChromaDB 知识库文档摄取管道.

将 PDF/Word/TXT 文档分块、嵌入、存入 ChromaDB。
支持: 预置目录批量导入 + 单文件上传 + 增量更新 (hash 去重).

用法:
  python ingest_documents.py --dir docs/安诺奇-上市企业辅导/     # 批量导入
  python ingest_documents.py --file /path/to/doc.pdf            # 单文件
  python ingest_documents.py --status                           # 查看状态
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import chromadb
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────
CHROMA_PATH = os.environ.get("CHROMA_PATH", "/var/lib/quant-data/chromadb")
COLLECTION_NAME = "tiantuan_knowledge_base"
EMBED_MODEL = "all-MiniLM-L6-v2"  # 384维, 轻量本地, 中文尚可; 后续可换 bge-large-zh-v1.5

CHUNK_SIZE = 500  # 每块字符数
CHUNK_OVERLAP = 100  # 重叠字符数

SUPPORTED_EXT = {".pdf", ".docx", ".txt", ".md"}


# ── Text Extraction ───────────────────────────────────────────────────


def extract_text(file_path: str) -> Optional[str]:
    """Extract text from a document file."""
    ext = Path(file_path).suffix.lower()

    if ext == ".pdf":
        try:
            import pdfplumber

            text_parts = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
            text = "\n\n".join(text_parts)
            if not text.strip():
                # Try pypdf as fallback
                from pypdf import PdfReader

                reader = PdfReader(file_path)
                text = "\n\n".join(p.extract_text() or "" for p in reader.pages)
            return text.strip() if text.strip() else None
        except Exception as e:
            log.warning(f"PDF extract failed for {file_path}: {e}")
            return None

    elif ext == ".docx":
        try:
            from docx import Document

            doc = Document(file_path)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            log.warning(f"DOCX extract failed for {file_path}: {e}")
            return None

    elif ext in (".txt", ".md"):
        try:
            return Path(file_path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return Path(file_path).read_text(encoding="gbk")
            except Exception:
                return None

    else:
        log.warning(f"Unsupported format: {ext}")
        return None


# ── Chunking ──────────────────────────────────────────────────────────


def chunk_text(text: str, source: str) -> list[dict]:
    """Split text into overlapping chunks with metadata."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "，", ".", ",", " ", ""],
    )

    docs = splitter.create_documents(
        [text],
        metadatas=[{"source": source, "file_name": Path(source).name}],
    )

    chunks = []
    for i, doc in enumerate(docs):
        chunk_id = hashlib.md5(doc.page_content.encode()).hexdigest()[:16]
        chunks.append(
            {
                "id": chunk_id,
                "text": doc.page_content,
                "metadata": {
                    **doc.metadata,
                    "chunk_index": i,
                    "char_start": i * (CHUNK_SIZE - CHUNK_OVERLAP),
                },
            }
        )
    return chunks


# ── ChromaDB Operations ───────────────────────────────────────────────


def get_collection():
    """Get or create the ChromaDB collection."""
    os.makedirs(CHROMA_PATH, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return client, collection


def ingest_file(file_path: str, collection, model) -> int:
    """Ingest a single file. Returns number of chunks added."""
    text = extract_text(file_path)
    if not text:
        log.warning(f"No text extracted from {file_path}")
        return 0

    chunks = chunk_text(text, file_path)
    if not chunks:
        return 0

    # Embed
    texts = [c["text"] for c in chunks]
    ids = [c["id"] for c in chunks]
    metadatas = [c["metadata"] for c in chunks]
    embeddings = model.encode(texts, show_progress_bar=False).tolist()

    # Upsert (idempotent by hash)
    try:
        collection.upsert(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        return len(chunks)
    except Exception as e:
        log.error(f"ChromaDB upsert failed: {e}")
        return 0


def ingest_directory(dir_path: str, collection, model) -> dict:
    """Recursively ingest all supported files in a directory."""
    stats = {"total": 0, "files": 0, "skipped": 0}

    for root, _, files in os.walk(dir_path):
        for fname in sorted(files):
            ext = Path(fname).suffix.lower()
            if ext not in SUPPORTED_EXT:
                continue

            file_path = os.path.join(root, fname)
            n = ingest_file(file_path, collection, model)
            if n > 0:
                log.info(f"  ✅ {fname}: {n} chunks")
                stats["total"] += n
                stats["files"] += 1
            else:
                stats["skipped"] += 1

    return stats


def get_status(collection) -> dict:
    """Return knowledge base stats."""
    count = collection.count()
    return {
        "collection": COLLECTION_NAME,
        "total_chunks": count,
        "embedding_model": EMBED_MODEL,
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "storage_path": CHROMA_PATH,
    }


# ── Main ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="AI天团 知识库文档摄取管道")
    parser.add_argument("--dir", type=str, help="批量导入目录 (递归扫描PDF/DOCX/TXT)")
    parser.add_argument("--file", type=str, help="导入单个文件")
    parser.add_argument("--status", action="store_true", help="查看知识库状态")
    parser.add_argument("--model", type=str, default=EMBED_MODEL, help="嵌入模型名称")
    args = parser.parse_args()

    log.info(f"Loading embedding model: {args.model}")
    model = SentenceTransformer(args.model)

    _, collection = get_collection()

    if args.status:
        status = get_status(collection)
        print("\n📚 知识库状态:")
        for k, v in status.items():
            print(f"  {k}: {v}")
        return

    if args.file:
        log.info(f"Ingesting single file: {args.file}")
        n = ingest_file(args.file, collection, model)
        log.info(f"Done. {n} chunks added.")
        return

    if args.dir:
        log.info(f"Ingesting directory: {args.dir}")
        stats = ingest_directory(args.dir, collection, model)
        log.info(
            f"Done. {stats['files']} files → {stats['total']} chunks ({stats['skipped']} skipped)"
        )
        return

    parser.print_help()


if __name__ == "__main__":
    main()
