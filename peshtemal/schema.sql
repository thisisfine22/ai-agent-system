-- Peshtemal Collection — PostgreSQL Agent Schema
-- Database: peshtemal (isolated from other databases on same server)
-- Role: peshtemal (zero cross-database access — verified with permission denied checks)

CREATE SCHEMA IF NOT EXISTS agents;

-- Rolling fact memory — last 20 facts injected into every CTO system prompt
-- Gives the agent persistent memory without storing full conversation history
CREATE TABLE agents.memory (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name  TEXT NOT NULL,              -- cto | marketing-peshtemal | ecommerce | customer
    memory_type TEXT NOT NULL DEFAULT 'fact',
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Task queue — state machine: proposed → approved → in_progress → done
-- Tasks only move to 'approved' when founder replies Y on Telegram
CREATE TABLE agents.tasks (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assigned_to  TEXT NOT NULL,             -- marketing-peshtemal | ecommerce | customer
    status       TEXT NOT NULL DEFAULT 'proposed',
    title        TEXT NOT NULL,
    input_data   JSONB NOT NULL DEFAULT '{}',   -- full instructions for the worker agent
    output_data  JSONB,                          -- results written back by worker agent
    priority     INTEGER DEFAULT 5,             -- 3=high, 5=medium, 8=low
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- Proposals — groups tasks for a single Y/N decision from the founder
CREATE TABLE agents.proposals (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_ids     UUID[] NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | rejected
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    responded_at TIMESTAMPTZ
);

-- Per-task working memory for long-running worker agents
CREATE TABLE agents.task_context (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id    UUID REFERENCES agents.tasks(id),
    agent_name TEXT NOT NULL,
    context    JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Immutable audit log — every action recorded, nothing deleted
CREATE TABLE agents.audit_log (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id    UUID REFERENCES agents.tasks(id),
    agent_name TEXT NOT NULL,
    action     TEXT NOT NULL,
    details    JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX ON agents.tasks(status);
CREATE INDEX ON agents.tasks(assigned_to);
CREATE INDEX ON agents.memory(agent_name, created_at DESC);
CREATE INDEX ON agents.proposals(status);
