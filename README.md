# Autonomous AI Agent Infrastructure

A production-grade multi-agent system built on a Mac Mini home server — designed to run a real e-commerce business autonomously with human-in-the-loop approval gates.

## Overview

This system replaces the operational overhead of running a Shopify-based e-commerce brand by deploying a hierarchy of specialized AI agents that handle email marketing, content creation, SEO, and customer workflows — all requiring explicit human approval before execution.

**Stack:** Python 3.12 · Claude claude-opus-4-6/Sonnet · PostgreSQL 16 · Telegram Bot API · Anthropic Tool Use · asyncpg · aiohttp · launchd

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     PERSONAL DEVICE                         │
│                  Telegram (iOS/Android)                     │
│              Human approval: Y / N only                     │
└──────────────────────────┬──────────────────────────────────┘
                           │ Telegram Bot API (outbound only)
┌──────────────────────────▼──────────────────────────────────┐
│                      MAC MINI SERVER                        │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                   bot.py (async)                    │   │
│  │         python-telegram-bot 20.x · polling          │   │
│  │                                                     │   │
│  │  ┌──────────────┐    ┌────────────────────────┐    │   │
│  │  │ Auth layer   │    │  Y/N approval handler  │    │   │
│  │  │ user_id gate │    │  writes to PostgreSQL   │    │   │
│  │  └──────────────┘    └────────────────────────┘    │   │
│  └──────────────────────────┬────────────────────────┘   │
│                             │                             │
│  ┌──────────────────────────▼────────────────────────┐   │
│  │              CTO Agent (Claude claude-opus-4-6)         │   │
│  │                                                   │   │
│  │  Tools:  read_context · create_task               │   │
│  │          send_proposal · check_tasks              │   │
│  │                                                   │   │
│  │  Model strategy:                                  │   │
│  │    Round 0    → claude-opus-4-6 (strategic)            │   │
│  │    Rounds 1-N → claude-sonnet-4-6 (tool execution)     │   │
│  │    429 error  → gpt-4o-mini (fallback)            │   │
│  │                                                   │   │
│  │  Rolling 20-message window                        │   │
│  │  Max 12 tool rounds per request                   │   │
│  └──────────────────────────┬────────────────────────┘   │
│                             │                             │
│  ┌──────────────────────────▼────────────────────────┐   │
│  │           PostgreSQL 16 (agents schema)           │   │
│  │                                                   │   │
│  │  agents.memory       — rolling fact store         │   │
│  │  agents.tasks        — proposed → approved →      │   │
│  │                         in_progress → done        │   │
│  │  agents.proposals    — pending Y/N approvals      │   │
│  │  agents.task_context — agent working memory       │   │
│  │  agents.audit_log    — full action history        │   │
│  └──────────────────────────┬────────────────────────┘   │
│                             │                             │
│  ┌──────────────────────────▼────────────────────────┐   │
│  │              Task Runner (polling 60s)            │   │
│  │                                                   │   │
│  │  Picks up status='approved' tasks only            │   │
│  │  Routes to worker agents by assigned_to field     │   │
│  └──────┬──────────────┬──────────────┬─────────────┘   │
│         │              │              │                   │
│  ┌──────▼───┐  ┌───────▼──┐  ┌───────▼──┐              │
│  │marketing │  │ecommerce │  │ customer │              │
│  │  agent   │  │  agent   │  │  agent   │              │
│  │(Sonnet)  │  │(Sonnet)  │  │(Sonnet)  │              │
│  └──────────┘  └──────────┘  └──────────┘              │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │         Watchdog (launchd, every 60s)           │   │
│  │   Monitors bot.py + task_runner.py              │   │
│  │   Alerts owner via Telegram if anything fails   │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

### 1. Human-in-the-loop is non-negotiable
Every task proposal requires explicit `Y` approval before it touches any external system. The approval handler writes directly to PostgreSQL — it cannot be bypassed by the agent. Worker agents only see tasks with `status='approved'`.

### 2. Model tiering for cost efficiency
- **Claude claude-opus-4-6** handles the first reasoning round (strategic thinking, context reading)
- **Claude Sonnet** handles subsequent tool execution rounds (cheaper, faster)
- **GPT-4o-mini** serves as a 429 fallback — never leaves the user without a response

### 3. Tool use over MCP for reliability
Native Anthropic tool definitions (`read_context`, `create_task`, `send_proposal`, `check_tasks`) instead of stdio MCP servers. MCP requires URL-based servers for the Anthropic API — native tools give full control over execution and error handling.

### 4. Isolated PostgreSQL access
The `peshtemal` PostgreSQL role has zero access to other databases on the same server. Verified with permission denied checks. The bot uses asyncpg directly for writes (not MCP) to ensure transactional integrity.

### 5. API scope minimization
- **Klaviyo:** No `write_customers`, no `write_orders` — read-only on customer data
- **Shopify:** No `write_customers`, no `write_orders` — agent can update products and content only
- **Telegram:** Single authorized user ID checked on every incoming message

### 6. Memory architecture
A Haiku-powered fact extractor runs after every conversation turn. It extracts one business-relevant fact and writes it to `agents.memory`. The system prompt for every new request includes the last 20 facts — giving the CTO agent persistent memory without storing full conversation history.

---

## Task Lifecycle

```
User message → CTO Agent reads context files
             → CTO calls create_task() → PostgreSQL: status='proposed'
             → CTO calls send_proposal() → PostgreSQL: proposals table
             → Bot sends proposal to Telegram
             → User replies Y
             → Bot writes status='approved' to tasks + proposals
             → Task Runner polls every 60s
             → Task Runner picks up approved task
             → Worker agent executes
             → Result sent back to Telegram
```

---

## Security Model

| Layer | Control |
|---|---|
| Telegram | Single `user_id` allowlist — all other messages silently dropped |
| PostgreSQL | Isolated role, no cross-database access, asyncpg direct writes |
| Shopify API | Scoped to read customers, write products/content only |
| Klaviyo API | Scoped to flows/templates/lists — no customer data writes |
| GitHub | Deploy key scoped to single repo, no personal Mac access |
| Network | PostgreSQL not exposed to network — SSH tunnel only |
| Secrets | `.env` gitignored, chmod 600, never in version control |

---

## Infrastructure

- **Server:** Mac Mini (Apple Silicon), always-on
- **Process management:** launchd plists with auto-restart
- **Networking:** Tailscale for secure remote access
- **Backups:** rclone to Google Drive (nightly)
- **Monitoring:** Watchdog bot with Telegram alerts
- **Deployment:** GitHub SSH deploy key + git pull cron (15 min)

---

## Agent Roster

| Agent | Model | Responsibilities |
|---|---|---|
| CTO | Claude claude-opus-4-6 → Sonnet | Strategy, task creation, proposals |
| marketing-peshtemal | Claude Sonnet | Instagram/Pinterest content, scheduling |
| ecommerce | Claude Sonnet | Shopify SEO, product pages, conversion |
| customer | Claude Sonnet | Klaviyo flows, email sequences, segments |

---

## What This Replaces

| Manual task | Agent |
|---|---|
| Writing Klaviyo email flows | customer agent |
| Updating Shopify product descriptions | ecommerce agent |
| Writing Instagram captions and scheduling | marketing agent |
| Monitoring store performance | ecommerce agent |
| Building email segments | customer agent |

---

## Status

- ✅ CTO bot live on Telegram
- ✅ Tool use working (read_context, create_task, send_proposal, check_tasks)
- ✅ PostgreSQL task queue operational
- ✅ Memory system (Haiku extractor → rolling fact store)
- ✅ Y/N approval flow end-to-end
- ✅ GitHub backup
- 🔄 Task runner (in progress)
- 🔄 Worker agents (in progress)
- 🔄 launchd auto-restart (in progress)
- 🔄 Watchdog monitoring (in progress)
