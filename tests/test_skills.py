#!/usr/bin/env python3
"""SP4 Skills 系统 — 单元测试。

运行: cd /home/zp/work/trade/freqtrade/.worktrees/quant-mvp &&
       /home/zp/work/trade/freqtrade/.venv/bin/python -m pytest tests/test_skills.py -v
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest


# Add project to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from freqtrade.rpc.api_server.api_quant import (
    _list_skills,
    _load_skill,
    _parse_skill_metadata,
)


# ── YAML Frontmatter 解析测试 ──


def test_parse_valid_skill():
    """解析有效的 SKILL.md YAML frontmatter"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("""---
name: test-skill
description: "A test skill for unit testing"
version: 1.0.0
metadata:
  portable_runtime: true
  tags: [test, unit]
---
# Test Skill

## Purpose
This is a test skill.
""")
        f.flush()
        meta = _parse_skill_metadata(f.name)
        os.unlink(f.name)

    assert meta is not None
    assert meta["name"] == "test-skill"
    assert meta["description"] == "A test skill for unit testing"
    assert meta["version"] == "1.0.0"
    assert meta["metadata"]["portable_runtime"] is True
    assert meta["metadata"]["tags"] == ["test", "unit"]
    assert "# Test Skill" in meta["_body"]


def test_parse_no_frontmatter():
    """解析无 frontmatter 的文件返回 None"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("# Just a markdown file\nNo YAML frontmatter here.")
        f.flush()
        meta = _parse_skill_metadata(f.name)
        os.unlink(f.name)

    assert meta is None


def test_parse_invalid_yaml():
    """解析无效 YAML 返回 None"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("""---
name: [unclosed
---
body""")
        f.flush()
        meta = _parse_skill_metadata(f.name)
        os.unlink(f.name)

    assert meta is None


def test_parse_empty_file():
    """解析空文件返回 None"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("")
        f.flush()
        meta = _parse_skill_metadata(f.name)
        os.unlink(f.name)

    assert meta is None


# ── Skill 加载测试 ──


def test_load_valid_skill():
    """加载真实 factor-deep-dive Skill"""
    meta = _load_skill("factor-deep-dive")
    assert meta is not None
    assert meta["name"] == "factor-deep-dive"
    assert "因子深度分析" in meta["description"]
    assert meta["version"] == "1.0.0"
    assert "Portable Runtime Contract" in meta["_body"]
    # 检查 references
    refs = meta.get("references", [])
    assert isinstance(refs, list)


def test_load_all_skills():
    """所有 5 个 Skills 都能成功加载"""
    skill_names = [
        "factor-deep-dive",
        "macro-briefing",
        "cross-asset-comparison",
        "risk-assessment",
        "news-impact",
    ]
    for name in skill_names:
        meta = _load_skill(name)
        assert meta is not None, f"Failed to load skill: {name}"
        assert meta["name"] == name
        assert len(meta["description"]) > 0
        assert len(meta["_body"]) > 100, f"Skill {name} body too short"


def test_load_nonexistent_skill():
    """加载不存在的 Skill 返回 None"""
    assert _load_skill("nonexistent-skill") is None


def test_list_skills():
    """Skills 列表包含所有 5 个 Skills"""
    skills = _list_skills()
    names = {s["name"] for s in skills}
    assert "factor-deep-dive" in names
    assert "macro-briefing" in names
    assert "cross-asset-comparison" in names
    assert "risk-assessment" in names
    assert "news-impact" in names
    assert len(skills) >= 5  # 可能还有 _anthropic-ref 被过滤掉


# ── Guarrails/Quality Checklist 验证 ──


def test_skills_have_required_sections():
    """所有 Skills 包含必需的章节"""
    required_sections = ["Purpose", "Outputs", "Execution Workflow", "Guardrails"]
    for name in ["factor-deep-dive", "macro-briefing", "risk-assessment"]:
        meta = _load_skill(name)
        body = meta["_body"]
        for section in required_sections:
            assert section in body, f"Skill {name} missing section: {section}"


def test_skills_have_quality_checklist():
    """所有 Skills 包含 Quality Checklist"""
    for name in ["factor-deep-dive", "risk-assessment"]:
        meta = _load_skill(name)
        assert "Quality Checklist" in meta["_body"], f"Skill {name} missing Quality Checklist"


# ── API 端点测试 ──


@pytest.fixture
def api_client():
    """FastAPI TestClient for quant API."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from freqtrade.rpc.api_server.api_quant import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_skills_endpoint(api_client):
    """GET /quant/skills 返回 Skills 列表"""
    resp = api_client.get("/quant/skills")
    assert resp.status_code == 200
    data = resp.json()
    assert "skills" in data
    assert len(data["skills"]) >= 5


def test_skill_detail_endpoint(api_client):
    """GET /quant/skills/factor-deep-dive 返回详情"""
    resp = api_client.get("/quant/skills/factor-deep-dive")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "factor-deep-dive"
    assert "body" in data
    assert len(data["body"]) > 100


def test_skill_not_found(api_client):
    """GET /quant/skills/nonexistent 返回 404"""
    resp = api_client.get("/quant/skills/nonexistent")
    assert resp.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
