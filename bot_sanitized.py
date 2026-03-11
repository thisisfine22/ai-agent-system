"""
CTO Agent Bot — Sanitized for portfolio review.
Production version connects to PostgreSQL, Telegram, and Anthropic APIs.
All credentials loaded from .env (never committed to version control).
"""

import os
import asyncio
import json
import logging
import asyncpg
import aiohttp
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

BOSTON_TZ    = ZoneInfo("America/New_York")
MAX_TOOL_ROUNDS = 12
ROLLING_MEMORY  = 20

# ── Tool definitions passed to Anthropic API ──────────────────────────────────
# Claude can call these natively — no MCP server required.
TOOLS = [
    {
        "name": "read_context",
        "description": "Read a business context file (brand voice, product catalog, priorities, strategy)",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "enum": ["brand-voice.md", "product-catalog.md", "current-priorities.md", "platform-strategy.md"],
                }
            },
            "required": ["filename"],
        },
    },
    {
        "name": "create_task",
        "description": "Write a task to PostgreSQL with status='proposed'. Stays proposed until owner approves with Y.",
        "input_schema": {
            "type": "object",
            "properties": {
                "assigned_to": {"type": "string", "enum": ["marketing", "ecommerce", "customer"]},
                "title":       {"type": "string"},
                "input_data":  {"type": "object"},
                "priority":    {"type": "integer", "default": 5},
            },
            "required": ["assigned_to", "title", "input_data"],
        },
    },
    {
        "name": "send_proposal",
        "description": "Create a proposal record linking task IDs. Owner receives Y/N prompt on Telegram.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_ids": {"type": "array", "items": {"type": "string"}},
                "summary":  {"type": "string"},
            },
            "required": ["task_ids", "summary"],
        },
    },
    {
        "name": "check_tasks",
        "description": "Query the task queue filtered by status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["proposed", "approved", "in_progress", "done", "failed", "rejected", "all"],
                    "default": "all",
                }
            },
        },
    },
]

# ── Model tiering strategy ────────────────────────────────────────────────────
# Round 0: claude-opus-4-6 (strategic reasoning, context synthesis)
# Rounds 1+: claude-sonnet-4-6 (tool execution, cheaper)
# On 429: gpt-4o-mini fallback (never leave user without response)

async def call_claude(messages: list, system: str, anthropic_key: str) -> tuple[str, list]:
    current    = messages.copy()
    tool_round = 0

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
        while tool_round <= MAX_TOOL_ROUNDS:
            model = "claude-opus-4-6" if tool_round == 0 else "claude-sonnet-4-6"

            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01"},
                json={"model": model, "max_tokens": 1000, "system": system,
                      "tools": TOOLS, "messages": current},
            ) as resp:
                if resp.status == 429:
                    return await call_openai_fallback(current, system), current
                data = await resp.json()

            content     = data.get("content", [])
            tool_blocks = [b for b in content if b.get("type") == "tool_use"]
            text        = " ".join(b.get("text","") for b in content if b.get("type") == "text").strip()

            if not tool_blocks:
                current.append({"role": "assistant", "content": content})
                return text, current

            # Execute tools and feed results back
            current.append({"role": "assistant", "content": content})
            tool_results = []
            for tb in tool_blocks:
                result = await execute_tool(tb["name"], tb["input"])
                tool_results.append({"type": "tool_result", "tool_use_id": tb["id"], "content": result})
            current.append({"role": "user", "content": tool_results})
            tool_round += 1

    return "Max tool rounds reached.", current

# ── Y/N approval writes directly to PostgreSQL ────────────────────────────────
# Agent cannot bypass — approval is handled in bot.py, not by Claude.

async def handle_approval(approve: bool, db_url: str) -> str:
    conn     = await asyncpg.connect(db_url)
    proposal = await conn.fetchrow(
        "SELECT id, task_ids FROM agents.proposals WHERE status='pending' ORDER BY created_at DESC LIMIT 1"
    )
    if not proposal:
        await conn.close()
        return "No pending proposals."

    status = "approved" if approve else "rejected"
    for task_id in proposal["task_ids"]:
        await conn.execute(f"UPDATE agents.tasks SET status='{status}' WHERE id=$1::uuid", task_id)
    await conn.execute(f"UPDATE agents.proposals SET status='{status}', responded_at=NOW() WHERE id=$1", proposal["id"])
    await conn.close()
    return "✅ Approved — task runner picks up within 60s." if approve else "❌ Rejected."

# ── Haiku-powered memory extraction ──────────────────────────────────────────
# After every turn, a fast/cheap Haiku call extracts one business fact.
# Stored in agents.memory, injected into every future system prompt.

async def extract_and_save_fact(conversation: str, db_url: str, anthropic_key: str):
    async with aiohttp.ClientSession() as s:
        async with s.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01"},
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 150,
                "system": "Extract ONE key business fact in one sentence. Reply SKIP if nothing worth saving.",
                "messages": [{"role": "user", "content": conversation[-2000:]}],
            },
        ) as resp:
            data = await resp.json()
            fact = data["content"][0]["text"].strip()
            if not fact.startswith("SKIP"):
                conn = await asyncpg.connect(db_url)
                await conn.execute(
                    "INSERT INTO agents.memory (agent_name, memory_type, content) VALUES ('cto', 'fact', $1)", fact
                )
                await conn.close()
