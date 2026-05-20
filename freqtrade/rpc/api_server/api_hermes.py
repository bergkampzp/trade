"""Sprint 2 — AI天团 Hermes WebChat adapter.

提供 @mention Agent 对话 + SSE 流式 + 会话管理端点。
集成到 Freqtrade API Server (:20080)。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["hermes"], prefix="/hermes")

# ── Config ────────────────────────────────────────────────────────────
SKILLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "user_data", "skills",
)
HERMES_CONFIG = os.path.expanduser("~/.hermes/config.yaml")
CHROMA_PATH = os.environ.get("CHROMA_PATH", "/var/lib/quant-data/chromadb")
DB_DSN = "host=localhost port=5433 dbname=warehouse user=postgres password=postgres"

# ── Skill Metadata ────────────────────────────────────────────────────
_SKILL_CACHE: list[dict] = []
_SKILL_CACHE_TIME = 0.0


def _parse_skill_md(md_path: str) -> dict | None:
    """Parse SKILL.md YAML frontmatter."""
    try:
        with open(md_path, encoding="utf-8") as f:
            content = f.read()
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                meta = yaml.safe_load(parts[1]) or {}
                meta["_body"] = parts[2].strip()
                meta["_path"] = md_path
                return meta
        return None
    except Exception as e:
        logger.warning(f"Parse skill failed: {md_path}: {e}")
        return None


def _load_skills(force: bool = False) -> list[dict]:
    """Load all skills with caching."""
    global _SKILL_CACHE, _SKILL_CACHE_TIME
    if not force and _SKILL_CACHE and time.time() - _SKILL_CACHE_TIME < 60:
        return _SKILL_CACHE

    # Hardcoded role metadata for AI天团 agents
    ROLE_MAP = {
        "financial-analyst": {"icon": "💰", "color": "#22c55e", "label": "财务分析师",
            "suggestions": [
                "分析安诺其(300152)最近三年的盈利能力",
                "宁德时代(300750)的偿债风险如何？",
                "对比贵州茅台和五粮液的现金流质量",
            ]},
        "valuation-analyst": {"icon": "💎", "color": "#f59e0b", "label": "估值分析师",
            "suggestions": [
                "用DCF方法给安诺其估值",
                "贵州茅台当前PE合理吗？",
                "宁德时代的成长性估值分析",
            ]},
        "ma-advisor": {"icon": "🤝", "color": "#8b5cf6", "label": "M&A并购顾问",
            "suggestions": [
                "分析安诺其收购广州烽云的标的匹配度",
                "设计安诺其收购烽云的交易结构",
                "安诺其收购烽云的合规审核要点有哪些？",
                "烽云科技的尽调风险点分析",
            ]},
        "asset-valuator": {"icon": "📊", "color": "#f97316", "label": "资产评估专家",
            "suggestions": [
                "用三种方法给烽云科技估值",
                "烽云科技的无形资产如何评估？",
                "烽云科技业绩对赌方案设计",
            ]},
        "industry-researcher": {"icon": "🔬", "color": "#06b6d4", "label": "行业研究员",
            "suggestions": [
                "分析数码印花行业的竞争格局",
                "安诺其和烽云的协同效应量化分析",
                "染料行业转IDC算力的行业趋势",
                "工业喷墨打印头的国产替代进程",
            ]},
        "cross-asset-comparison": {"icon": "📈", "color": "#6366f1", "label": "跨资产对比"},
        "factor-deep-dive": {"icon": "🔍", "color": "#a78bfa", "label": "因子深度分析"},
        "macro-briefing": {"icon": "🌐", "color": "#06b6d4", "label": "宏观简报"},
        "news-impact": {"icon": "📰", "color": "#ec4899", "label": "新闻影响分析"},
        "risk-assessment": {"icon": "⚠️", "color": "#ef4444", "label": "风险评估"},
    }

    skills = []
    if os.path.isdir(SKILLS_DIR):
        for name in sorted(os.listdir(SKILLS_DIR)):
            d = os.path.join(SKILLS_DIR, name)
            md = os.path.join(d, "SKILL.md")
            if not os.path.isfile(md):
                continue
            meta = _parse_skill_md(md)
            if meta:
                role = ROLE_MAP.get(name, {"icon": "🤖", "color": "#6366f1", "label": name, "suggestions": []})
                # Extract clean system prompt: body minus first heading
                body = meta.get("_body", "")
                system_prompt = body
                skills.append({
                    "name": name,
                    "label": role["label"],
                    "description": meta.get("description", ""),
                    "icon": role["icon"],
                    "color": role["color"],
                    "tags": meta.get("metadata", {}).get("tags", []),
                    "suggestions": role.get("suggestions", []),
                    "system_prompt": system_prompt,
                })
    _SKILL_CACHE = skills
    _SKILL_CACHE_TIME = time.time()
    return skills


# ── LLM Client ─────────────────────────────────────────────────────────


def _resolve_api_key() -> str:
    """Resolve DeepSeek API key from Hermes config."""
    try:
        with open(HERMES_CONFIG) as f:
            cfg = yaml.safe_load(f)
        key = cfg.get("providers", {}).get("deepseek", {}).get("api_key")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("DEEPSEEK_API_KEY", "")


def _rag_retrieve(query: str, top_k: int = 5) -> list[dict]:
    """Retrieve relevant chunks from ChromaDB."""
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        col = client.get_collection("tiantuan_knowledge_base")
        model = SentenceTransformer("all-MiniLM-L6-v2")
        emb = model.encode([query]).tolist()
        results = col.query(query_embeddings=emb, n_results=top_k)
        chunks = []
        if results.get("documents") and results["documents"][0]:
            for doc, meta, dist in zip(
                results["documents"][0], results["metadatas"][0], results["distances"][0]
            ):
                chunks.append({
                    "text": doc,
                    "source": meta.get("source", ""),
                    "file_name": meta.get("file_name", ""),
                    "score": round(1.0 - dist, 4),
                })
        return chunks
    except Exception as e:
        logger.warning(f"RAG retrieve failed: {e}")
        return []


async def _stream_chat(
    message: str,
    skill_name: str | None,
    session_history: list[dict],
):
    """SSE generator: stream LLM response token by token."""
    import httpx

    api_key = _resolve_api_key()
    if not api_key:
        yield f"data: {json.dumps({'type': 'error', 'message': '未配置 DeepSeek API Key'})}\n\n"
        return

    # Build system prompt from skill
    system_prompt = "你是一个AI天团智能助手，帮助用户分析A股上市公司的财务、估值、战略问题。请用中文回答，使用Markdown格式组织回答。"
    if skill_name:
        skills = _load_skills()
        for s in skills:
            if s["name"] == skill_name:
                system_prompt = s["system_prompt"]
                break

    # RAG context
    chunks = _rag_retrieve(message, top_k=3)
    rag_context = ""
    if chunks:
        rag_context = "\n\n## 参考文档\n" + "\n".join(
            f"- [{c['file_name']}] (相关度: {c['score']:.2f}): {c['text'][:200]}"
            for c in chunks
        )

    # Build messages
    messages = [{"role": "system", "content": system_prompt + rag_context}]
    for h in session_history[-10:]:
        messages.append(h)
    messages.append({"role": "user", "content": message})

    # Stream from DeepSeek
    body = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 2048,
        "stream": True,
        "stream_options": {"include_usage": True},
    }

    # Send RAG citations first
    if chunks:
        for c in chunks:
            yield f"data: {json.dumps({'type': 'citation', 'source': c['source'], 'file_name': c['file_name'], 'text': c['text'][:300], 'score': c['score']})}\n\n"

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                "https://api.deepseek.com/v1/chat/completions",
                json=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            ) as resp:
                if resp.status_code != 200:
                    text = await resp.aread()
                    yield f"data: {json.dumps({'type': 'error', 'message': f'LLM API error: {resp.status_code}'})}\n\n"
                    return

                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            yield f"data: {json.dumps({'type': 'done'})}\n\n"
                            return
                        try:
                            chunk = json.loads(data)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield f"data: {json.dumps({'type': 'text', 'content': content})}\n\n"
                        except json.JSONDecodeError:
                            continue
    except Exception as e:
        logger.exception("SSE stream error")
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


# ── Session DB Helpers ─────────────────────────────────────────────────


def _get_conn():
    import psycopg2
    return psycopg2.connect(DB_DSN)


def _ensure_sessions_table():
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS quant_raw_cn.hermes_sessions (
                id TEXT PRIMARY KEY,
                title TEXT DEFAULT '新对话',
                skill_name TEXT,
                messages JSONB DEFAULT '[]',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f"Ensure sessions table: {e}")


# ── Pydantic Models ────────────────────────────────────────────────────


class SkillInfo(BaseModel):
    name: str
    label: str
    description: str
    icon: str
    color: str
    tags: list[str] = []
    suggestions: list[str] = []


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    skill: Optional[str] = None
    session_id: Optional[str] = None
    attachments: list[str] = []


class NewSessionRequest(BaseModel):
    title: str = "新对话"
    skill: Optional[str] = None


class SessionSummary(BaseModel):
    id: str
    title: str
    skill: Optional[str] = None
    message_count: int = 0
    created_at: str = ""
    updated_at: str = ""


# ── Endpoints ──────────────────────────────────────────────────────────


@router.get("/skills", response_model=list[SkillInfo])
def api_skills():
    """列出所有可用 AI Agent 角色。"""
    skills = _load_skills()
    return [SkillInfo(
        name=s["name"],
        label=s["label"],
        description=s["description"],
        icon=s["icon"],
        color=s["color"],
        tags=s.get("tags", []),
        suggestions=s.get("suggestions", []),
    ) for s in skills]


@router.post("/chat")
async def api_chat(req: ChatRequest):
    """发送消息，返回 SSE 流式响应。"""
    # Load session history
    session_history = []
    if req.session_id:
        try:
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("SELECT messages FROM quant_raw_cn.hermes_sessions WHERE id=%s", (req.session_id,))
            row = cur.fetchone()
            if row and row[0]:
                session_history = row[0]
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"Load session failed: {e}")

    return StreamingResponse(
        _stream_chat(req.message, req.skill, session_history),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/session/new")
def api_session_new(req: NewSessionRequest):
    """创建新会话。"""
    _ensure_sessions_table()
    sid = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO quant_raw_cn.hermes_sessions (id, title, skill_name, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s)""",
            (sid, req.title, req.skill, now, now),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        raise HTTPException(500, f"创建会话失败: {e}")
    return {"session_id": sid, "title": req.title}


@router.get("/sessions", response_model=list[SessionSummary])
def api_sessions():
    """会话列表。"""
    _ensure_sessions_table()
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, title, skill_name, messages, created_at, updated_at
            FROM quant_raw_cn.hermes_sessions
            ORDER BY updated_at DESC LIMIT 50
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [SessionSummary(
            id=r[0],
            title=r[1],
            skill=r[2],
            message_count=len(r[3]) if r[3] else 0,
            created_at=r[4].isoformat() if hasattr(r[4], 'isoformat') else str(r[4]),
            updated_at=r[5].isoformat() if hasattr(r[5], 'isoformat') else str(r[5]),
        ) for r in rows]
    except Exception as e:
        logger.warning(f"List sessions: {e}")
        return []


@router.get("/session/{sid}")
def api_session_load(sid: str):
    """加载指定会话的完整消息历史。"""
    _ensure_sessions_table()
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, title, skill_name, messages FROM quant_raw_cn.hermes_sessions WHERE id=%s", (sid,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            raise HTTPException(404, "会话不存在")
        return {
            "id": row[0],
            "title": row[1],
            "skill": row[2],
            "messages": row[3] or [],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"加载会话失败: {e}")


@router.delete("/session/{sid}")
def api_session_delete(sid: str):
    """删除会话。"""
    _ensure_sessions_table()
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM quant_raw_cn.hermes_sessions WHERE id=%s", (sid,))
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "deleted", "session_id": sid}
    except Exception as e:
        raise HTTPException(500, f"删除会话失败: {e}")


@router.post("/session/{sid}/append")
async def api_session_append(sid: str, message: dict):
    """追加消息到会话历史（前端在对话结束后调用）。"""
    _ensure_sessions_table()
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT messages FROM quant_raw_cn.hermes_sessions WHERE id=%s", (sid,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "会话不存在")
        msgs = (row[0] or [])
        msgs.append(message)
        cur.execute(
            "UPDATE quant_raw_cn.hermes_sessions SET messages=%s, updated_at=NOW() WHERE id=%s",
            (json.dumps(msgs, ensure_ascii=False), sid),
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok", "message_count": len(msgs)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"追加消息失败: {e}")


@router.post("/upload")
async def api_upload(file: UploadFile = File(...)):
    """上传文件并索引到知识库。"""
    SUPPORTED = {
        "application/pdf", "text/plain", "text/markdown",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    if file.content_type and file.content_type not in SUPPORTED:
        raise HTTPException(400, f"不支持的文件类型: {file.content_type}")

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(400, "文件最大 50MB")

    # Extract text
    text = None
    fn = file.filename or "upload"
    if fn.lower().endswith(".pdf"):
        import io
        import pdfplumber
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                text = "\n\n".join(p.extract_text() or "" for p in pdf.pages)
        except Exception as e:
            raise HTTPException(400, f"PDF提取失败: {e}")
    else:
        text = content.decode("utf-8", errors="replace")

    if not text or not text.strip():
        raise HTTPException(400, "无法提取文本内容")

    # Index to ChromaDB
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        client = chromadb.PersistentClient(path=CHROMA_PATH)
        col = client.get_or_create_collection("tiantuan_knowledge_base")
        model = SentenceTransformer("all-MiniLM-L6-v2")

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500, chunk_overlap=100,
            separators=["\n\n", "\n", "。", "，", ". ", " ", ""],
        )
        docs = splitter.create_documents([text])
        ids, texts, metadatas, embeddings = [], [], [], []
        import hashlib
        for i, doc in enumerate(docs):
            cid = hashlib.md5(doc.page_content.encode()).hexdigest()[:16]
            ids.append(cid)
            texts.append(doc.page_content)
            metadatas.append({"source": fn, "file_name": fn, "chunk_index": i})
            embeddings.append(model.encode(doc.page_content).tolist())

        if ids:
            col.upsert(ids=ids, documents=texts, embeddings=embeddings, metadatas=metadatas)

        return {
            "status": "ok",
            "file_name": fn,
            "file_size": len(content),
            "chunks_added": len(ids),
        }
    except Exception as e:
        logger.exception("Upload/index failed")
        raise HTTPException(500, f"索引失败: {e}")


# ── Sprint 4: M&A 并购分析流水线 ──────────────────────────────────────


class MAAnalysisRequest(BaseModel):
    acquirer: str = Field("300152", description="收购方股票代码")
    target: str = Field("", description="标的公司名称")
    stage: str = Field("full", description="分析阶段: screening|due-diligence|valuation|structure|compliance|full")


class MAAnalysisParams(BaseModel):
    """M&A 分析注入的上下文字段。"""
    acquirer_name: str = ""
    acquirer_financials: str = ""
    acquirer_price: str = ""
    target_docs: list[str] = []
    stage: str = "full"


@router.post("/ma/analyze")
async def api_ma_analyze(req: MAAnalysisRequest):
    """M&A 并购全流程分析 — SSE 流式返回。"""
    import httpx

    # Load M&A advisor skill
    all_skills = _load_skills()
    ma_skill = None
    for s in all_skills:
        if s["name"] == "ma-advisor":
            ma_skill = s
            break
    if not ma_skill:
        raise HTTPException(500, "M&A advisor skill not found")

    # Gather financial data for acquirer
    acquirer_financials = ""
    acquirer_name = ""
    acquirer_price = ""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        # Financial summary
        cur.execute(
            """SELECT report_date, report_type, total_revenue, net_profit, total_assets,
                      shareholders_equity, roe, gross_margin, debt_ratio
               FROM quant_raw_cn.financial_metrics
               WHERE stock_code=%s ORDER BY report_date DESC LIMIT 8""",
            (req.acquirer,),
        )
        rows = cur.fetchall()
        if rows:
            # Stock name from financial_metrics
            cur2 = conn.cursor()
            cur2.execute("SELECT DISTINCT stock_name FROM quant_raw_cn.financial_metrics WHERE stock_code=%s LIMIT 1", (req.acquirer,))
            name_row = cur2.fetchone()
            acquirer_name = name_row[0] if name_row else req.acquirer
            cur2.close()

            acquirer_financials = "## 收购方财务数据\n\n| 报告期 | 类型 | 营收(万) | 净利润(万) | 总资产(万) | ROE(%) | 毛利率(%) | 负债率(%) |\n|--------|------|----------|-----------|-----------|--------|----------|----------|\n"
            for r in rows:
                acquirer_financials += (
                    f"| {r[0]} | {r[1] or '-'} | {r[2]/10000:.0f} | {r[3]/10000:.0f} | "
                    f"{r[4]/10000:.0f} | {r[5]:.1f} | {r[6]:.1f} | {r[7]:.1f} |\n"
                )
        # Latest price
        cur.execute(
            "SELECT trade_date, close FROM quant_raw_cn.akshare_daily WHERE stock_code=%s ORDER BY trade_date DESC LIMIT 1",
            (req.acquirer,),
        )
        price_row = cur.fetchone()
        if price_row:
            acquirer_price = f"最新收盘价: ¥{price_row[1]:.2f} (日期: {price_row[0]})"
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f"Financial data query failed: {e}")

    # Gather RAG context for target
    target_docs = []
    if req.target:
        chunks = _rag_retrieve(f"{acquirer_name} {req.target} 收购 并购 估值 方案", top_k=10)
        target_docs = [c["text"] for c in chunks]

    # Build system prompt
    rag_context = ""
    if target_docs:
        rag_context = "\n\n## 📚 参考文档 (来自知识库)\n" + "\n---\n".join(
            f"**[文档 {i+1}]** {doc[:800]}" for i, doc in enumerate(target_docs[:8])
        )

    system_prompt = ma_skill["system_prompt"] + f"""

## 📊 当前分析上下文

**收购方**: {acquirer_name} (股票代码: {req.acquirer})
{acquirer_price}

{acquirer_financials}

{rag_context}

## 📋 任务

请按照你的五维度分析框架，对收购方({acquirer_name})收购标的({req.target or '请从文档中识别'})进行{'全流程' if req.stage == 'full' else req.stage + '阶段'}分析。

注意：
1. 所有财务数据引用自上述表格
2. 标的方信息引用自上述参考文档 (标注 [文档N])
3. 估值时使用实际财务数据，不可编造
4. 合规判断需具体，引用相关法规
"""

    api_key = _resolve_api_key()
    if not api_key:
        raise HTTPException(500, "未配置 DeepSeek API Key")

    async def _stream():
        body = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请对 {acquirer_name} 收购 {req.target or '标的公司'} 进行{'全流程M&A并购' if req.stage == 'full' else req.stage + '阶段'}分析。"},
            ],
            "temperature": 0.3,
            "max_tokens": 4096,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        # Send context info first
        yield f"data: {json.dumps({'type': 'context', 'acquirer': acquirer_name, 'price': acquirer_price, 'docs': len(target_docs)})}\n\n"

        try:
            async with httpx.AsyncClient(timeout=180) as client:
                async with client.stream(
                    "POST",
                    "https://api.deepseek.com/v1/chat/completions",
                    json=body,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                ) as resp:
                    if resp.status_code != 200:
                        yield f"data: {json.dumps({'type': 'error', 'message': f'LLM API error: {resp.status_code}'})}\n\n"
                        return

                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                                return
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield f"data: {json.dumps({'type': 'text', 'content': content})}\n\n"
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            logger.exception("MA stream error")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Sprint 3: 会话管理增强 ─────────────────────────────────────────────


class RenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)


@router.put("/session/{sid}/rename")
def api_session_rename(sid: str, req: RenameRequest):
    """重命名会话。"""
    _ensure_sessions_table()
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE quant_raw_cn.hermes_sessions SET title=%s, updated_at=NOW() WHERE id=%s",
            (req.title, sid),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "会话不存在")
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "renamed", "session_id": sid, "title": req.title}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"重命名失败: {e}")


