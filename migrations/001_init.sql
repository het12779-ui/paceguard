-- PaceGuard - SQL Server 2022 schema
--
-- The demo creates its schema from SQLAlchemy metadata for zero-setup. This
-- file is the equivalent DDL for the deployment target DeltaX actually runs
-- (MS SQL Server), including the constraints that do the real work:
--   * tenant-scoped unique keys, so idempotency cannot leak across accounts
--   * filtered indexes for the "open alerts" read path
--   * SYSUTCDATETIME() defaults, because every timestamp is stored in UTC
--
-- Money is BIGINT minor units (paise). Never FLOAT, never MONEY: binary
-- floating point cannot represent 0.10 and SQL Server's MONEY type rounds to
-- four decimal places silently.

CREATE TABLE accounts (
    id            BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_accounts PRIMARY KEY,
    name          NVARCHAR(120)  NOT NULL,
    slug          NVARCHAR(60)   NOT NULL,
    api_key_hash  CHAR(64)       NOT NULL,           -- SHA-256 hex, never the key
    plan          NVARCHAR(30)   NOT NULL CONSTRAINT df_accounts_plan DEFAULT 'growth',
    created_at    DATETIME2(3)   NOT NULL CONSTRAINT df_accounts_created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_accounts_slug UNIQUE (slug)
);

CREATE TABLE campaigns (
    id                  BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_campaigns PRIMARY KEY,
    account_id          BIGINT        NOT NULL,
    external_id         NVARCHAR(80)  NOT NULL,
    name                NVARCHAR(160) NOT NULL,
    channel             NVARCHAR(40)  NOT NULL,
    currency            CHAR(3)       NOT NULL CONSTRAINT df_campaigns_currency DEFAULT 'INR',
    total_budget_cents  BIGINT        NOT NULL,
    pacing_mode         NVARCHAR(20)  NOT NULL CONSTRAINT df_campaigns_mode DEFAULT 'even',
    start_date          DATE          NOT NULL,
    end_date            DATE          NOT NULL,
    status              NVARCHAR(20)  NOT NULL CONSTRAINT df_campaigns_status DEFAULT 'active',
    created_at          DATETIME2(3)  NOT NULL CONSTRAINT df_campaigns_created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT fk_campaigns_account FOREIGN KEY (account_id)
        REFERENCES accounts (id) ON DELETE CASCADE,
    CONSTRAINT uq_campaigns_account_external UNIQUE (account_id, external_id),
    CONSTRAINT ck_campaigns_budget CHECK (total_budget_cents > 0),
    CONSTRAINT ck_campaigns_flight CHECK (end_date >= start_date),
    CONSTRAINT ck_campaigns_mode CHECK (pacing_mode IN ('even', 'front_loaded', 'asap'))
);

CREATE INDEX ix_campaigns_account_status ON campaigns (account_id, status);

CREATE TABLE spend_events (
    id           BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_spend_events PRIMARY KEY,
    account_id   BIGINT        NOT NULL,
    campaign_id  BIGINT        NOT NULL,
    event_uid    NVARCHAR(80)  NOT NULL,
    amount_cents BIGINT        NOT NULL,
    occurred_at  DATETIME2(3)  NOT NULL,
    source       NVARCHAR(40)  NOT NULL CONSTRAINT df_spend_source DEFAULT 'platform_sync',
    CONSTRAINT fk_spend_account FOREIGN KEY (account_id)
        REFERENCES accounts (id) ON DELETE CASCADE,
    CONSTRAINT fk_spend_campaign FOREIGN KEY (campaign_id)
        REFERENCES campaigns (id) ON DELETE CASCADE,
    -- The idempotency guarantee: at-least-once sync cannot double-count spend.
    CONSTRAINT uq_spend_account_event UNIQUE (account_id, event_uid),
    CONSTRAINT ck_spend_amount CHECK (amount_cents > 0)
);

CREATE INDEX ix_spend_campaign_occurred ON spend_events (campaign_id, occurred_at);
CREATE INDEX ix_spend_account_occurred ON spend_events (account_id, occurred_at);

CREATE TABLE alerts (
    id           BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_alerts PRIMARY KEY,
    account_id   BIGINT        NOT NULL,
    campaign_id  BIGINT        NULL,
    kind         NVARCHAR(40)  NOT NULL,
    severity     NVARCHAR(10)  NOT NULL,
    dedupe_key   NVARCHAR(180) NOT NULL,
    message      NVARCHAR(MAX) NOT NULL,
    detail       NVARCHAR(MAX) NULL,
    created_at   DATETIME2(3)  NOT NULL CONSTRAINT df_alerts_created DEFAULT SYSUTCDATETIME(),
    resolved_at  DATETIME2(3)  NULL,
    CONSTRAINT fk_alerts_account FOREIGN KEY (account_id)
        REFERENCES accounts (id) ON DELETE CASCADE,
    CONSTRAINT fk_alerts_campaign FOREIGN KEY (campaign_id)
        REFERENCES campaigns (id) ON DELETE CASCADE,
    CONSTRAINT uq_alerts_account_dedupe UNIQUE (account_id, dedupe_key),
    CONSTRAINT ck_alerts_severity CHECK (severity IN ('warning', 'critical'))
);

-- Filtered index: the dashboard only ever asks for unresolved alerts.
CREATE INDEX ix_alerts_open ON alerts (account_id) WHERE resolved_at IS NULL;

CREATE TABLE audit_log (
    id            BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_audit_log PRIMARY KEY,
    account_id    BIGINT       NOT NULL,
    actor         NVARCHAR(80) NOT NULL,
    action        NVARCHAR(60) NOT NULL,
    entity        NVARCHAR(60) NOT NULL,
    entity_id     BIGINT       NOT NULL,
    before_value  NVARCHAR(80) NULL,
    after_value   NVARCHAR(80) NULL,
    created_at    DATETIME2(3) NOT NULL CONSTRAINT df_audit_created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT fk_audit_account FOREIGN KEY (account_id)
        REFERENCES accounts (id) ON DELETE CASCADE
);

CREATE INDEX ix_audit_account_created ON audit_log (account_id, created_at);
