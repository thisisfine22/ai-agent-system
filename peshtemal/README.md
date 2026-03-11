# Peshtemal Collection — Autonomous AI Agent System

A production-grade multi-agent infrastructure built to run a Turkish textile e-commerce brand autonomously — with zero daily involvement from the founder.

**The business:** Peshtemal Collection sells beach towels, bath towels, kitchen towels, blankets, and bathrobes on Shopify. Physical market sales average $2K+/day. Online revenue was near zero despite having an active store, a real customer list, and Klaviyo installed but dormant.

**The solution:** A hierarchy of AI agents that handle Klaviyo email flows, Shopify SEO, Instagram/Pinterest content, and market intelligence — all requiring explicit founder approval before execution.

**Stack:** Python 3.12 · Claude claude-opus-4-6/Sonnet/Haiku · PostgreSQL 16 · Telegram Bot API · Anthropic Tool Use · asyncpg · aiohttp · Shopify Admin API · Klaviyo API · launchd · Tailscale

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     FOUNDER'S PHONE                         │
│                  Telegram (iOS/Android)                     │
│              Human approval: Y / N only                     │
└──────────────────────────┬──────────────────────────────────┘
                           │ Telegram Bot API (outbound only)
┌──────────────────────────▼──────────────────────────────────┐
│                  MAC MINI (always-on server)                 │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                   bot.py (async)                     │  │
│  │         python-telegram-bot 20.x · polling           │  │
│  │  Single user_id allowlist — all others dropped       │  │
│  │  Y/N approval writes directly to PostgreSQL          │  │
│  └──────────────────────────┬───────────────────────────┘  │
│                             │                               │
│  ┌──────────────────────────▼───────────────────────────┐  │
│  │              CTO Agent (Claude claude-opus-4-6)           │  │
│  │                                                      │  │
│  │  Tools: read_context · create_task                   │  │
│  │         send_proposal · check_tasks                  │  │
│  │                                                      │  │
│  │  Round 0    → claude-opus-4-6  (strategic reasoning)      │  │
│  │  Rounds 1+  → claude-sonnet-4-6 (tool execution)          │  │
│  │  On 429     → gpt-4o-mini  (fallback)                │  │
│  │  Max 12 tool rounds · Rolling 20-message window      │  │
│  └──────────────────────────┬───────────────────────────┘  │
│                             │                               │
│  ┌──────────────────────────▼───────────────────────────┐  │
│  │          PostgreSQL 16 — agents schema               │  │
│  │  memory · tasks · proposals · task_context · audit   │  │
│  └──────────────────────────┬───────────────────────────┘  │
│                             │                               │
│  ┌──────────────────────────▼───────────────────────────┐  │
│  │       Task Runner (polls every 60s for 'approved')   │  │
│  └──────────┬──────────────┬──────────────┬─────────────┘  │
│             │              │              │                  │
│  ┌──────────▼──┐  ┌────────▼───┐  ┌──────▼──────┐         │
│  │  marketing  │  │ ecommerce  │  │  customer   │         │
│  │  -peshtemal │  │   agent    │  │    agent    │         │
│  │ Instagram   │  │ Shopify    │  │  Klaviyo    │         │
│  │ Pinterest   │  │ SEO/pages  │  │  flows      │         │
│  └─────────────┘  └────────────┘  └─────────────┘         │
│                                                             │
│  Watchdog (launchd) · rclone backup · git pull cron        │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

### 1. Human-in-the-loop is absolute
Every task stays `proposed` in PostgreSQL until the founder replies Y on Telegram. The approval handler is in `bot.py`, not accessible to Claude. Worker agents only query for `status='approved'` tasks.

### 2. Model tiering for cost efficiency
Opus for strategic reasoning (round 0), Sonnet for tool execution (rounds 1+), GPT-4o-mini as a 429 fallback. The founder never gets silence regardless of rate limits.

### 3. Native tool use over MCP
Four Anthropic tool definitions instead of stdio MCP servers. The Anthropic API requires URL-based MCP — native tools give full control over DB writes, error handling, and execution flow.

### 4. Scoped API access (security by design)
- **Shopify:** `read_customers` + `read_orders` only. Agent writes products and content, never touches customer data or orders.
- **Klaviyo:** `read_profiles` only. Agent builds flows and segments, never modifies customer records.
- **Telegram:** Single `user_id` allowlist. All other senders are silently dropped.

### 5. Isolated PostgreSQL
The `peshtemal` role has zero access to any other database on the same server. Verified explicitly. Bot uses asyncpg direct writes for transactional integrity.

### 6. Haiku-powered persistent memory
After every conversation turn, Claude Haiku extracts one business fact and writes it to `agents.memory`. The last 20 facts are injected into every system prompt — persistent memory without storing full conversation history.

---

## Task Lifecycle

```
Founder message
  → CTO reads context files (brand voice, catalog, priorities, strategy)
  → CTO calls create_task()    → PostgreSQL: status='proposed'
  → CTO calls send_proposal()  → PostgreSQL: proposals table
  → Founder gets Y/N on Telegram
  → Founder replies Y
  → Bot: status='approved' in tasks + proposals
  → Task Runner picks up within 60s
  → Worker agent executes (Shopify / Klaviyo / content APIs)
  → Results written to agents.tasks.output_data
  → Founder notified on Telegram
```

---

## Security Model

| Layer | Control |
|---|---|
| Telegram | Single `user_id` allowlist — all others silently dropped |
| PostgreSQL | Isolated `peshtemal` role, no cross-database access |
| Shopify API | Read customers/orders · Write products/content only |
| Klaviyo API | Write flows/templates · Read profiles only |
| GitHub | Deploy key scoped to `peshtemalcollection` repo only |
| Network | PostgreSQL not exposed — SSH tunnel only |
| Secrets | `.env` gitignored, chmod 600, never in version control |

---

## Agent Roster

| Agent | Model | Domain |
|---|---|---|
| CTO | claude-opus-4-6 → Sonnet | Strategy, proposals, task creation |
| marketing-peshtemal | Sonnet | Instagram, Pinterest, content scheduling |
| ecommerce | Sonnet | Shopify SEO, product pages, conversion |
| customer | Sonnet | Klaviyo flows, email sequences, segments |

---

## Build Status

- ✅ CTO bot live on Telegram
- ✅ Native tool use (read_context, create_task, send_proposal, check_tasks)
- ✅ PostgreSQL task queue with full state machine
- ✅ Haiku memory extractor → rolling fact store
- ✅ Y/N approval flow verified end-to-end
- ✅ Scoped Shopify + Klaviyo API keys
- ✅ GitHub backup with deploy key
- 🔄 Task runner
- 🔄 Worker agents
- 🔄 launchd auto-restart
- 🔄 Watchdog monitoring
- 🔄 rclone nightly backup
