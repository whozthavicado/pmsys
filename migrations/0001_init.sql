-- 0001: esquema inicial (spec 1.0.0, sección (c)).
-- Los PRAGMA journal_mode y foreign_keys de la spec no van aquí (ADR-0004): son del bootstrap y de la
-- fábrica de conexiones de infra.db, no del esquema.

CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, sha256 TEXT NOT NULL
);

CREATE TABLE markets (
  market_id       TEXT PRIMARY KEY,                -- Gamma id
  condition_id    TEXT NOT NULL UNIQUE,
  event_id        TEXT,
  slug            TEXT,
  question        TEXT NOT NULL,
  rules_text      TEXT NOT NULL,
  rules_sha       TEXT NOT NULL,
  category        TEXT NOT NULL CHECK (category IN ('a','b','c','d','other')),
  tags_json       TEXT NOT NULL DEFAULT '[]',
  yes_token_id    TEXT NOT NULL,
  no_token_id     TEXT NOT NULL,
  neg_risk        INTEGER NOT NULL CHECK (neg_risk IN (0,1)),
  end_date_utc    TEXT,
  active          INTEGER NOT NULL CHECK (active IN (0,1)),
  closed          INTEGER NOT NULL CHECK (closed IN (0,1)),
  uma_status      TEXT,
  outcome         TEXT CHECK (outcome IN ('YES','NO','VOID')),
  resolved_at     TEXT,
  first_seen_at   TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  raw_json        TEXT NOT NULL
);
CREATE INDEX ix_markets_open      ON markets (active, closed, end_date_utc);
CREATE INDEX ix_markets_category  ON markets (category, end_date_utc);
CREATE INDEX ix_markets_event     ON markets (event_id);
CREATE INDEX ix_markets_unsettled ON markets (closed, outcome) WHERE outcome IS NULL;

CREATE TABLE clob_params (
  condition_id   TEXT NOT NULL REFERENCES markets(condition_id),
  fetched_at     TEXT NOT NULL,
  min_order_size REAL NOT NULL,
  tick_size      REAL NOT NULL,
  fee_rate       REAL,
  fee_exponent   REAL,
  taker_only     INTEGER,
  raw_json       TEXT NOT NULL,
  PRIMARY KEY (condition_id, fetched_at)
);

CREATE TABLE rules_specs (
  market_id        TEXT NOT NULL REFERENCES markets(market_id),
  rules_sha        TEXT NOT NULL,
  parser_version   TEXT NOT NULL,
  spec_json        TEXT NOT NULL,
  ambiguity_det    INTEGER NOT NULL CHECK (ambiguity_det BETWEEN 0 AND 10),
  ambiguity_llm    INTEGER CHECK (ambiguity_llm BETWEEN 0 AND 10),
  ambiguity_final  INTEGER NOT NULL CHECK (ambiguity_final BETWEEN 0 AND 10),
  created_at       TEXT NOT NULL,
  PRIMARY KEY (market_id, rules_sha, parser_version)
);

CREATE TABLE book_snapshots (
  token_id TEXT NOT NULL, ts TEXT NOT NULL,
  best_bid REAL, best_ask REAL,
  depth_json TEXT NOT NULL,                        -- top 20 niveles por lado
  PRIMARY KEY (token_id, ts)
);

CREATE TABLE price_points (
  token_id TEXT NOT NULL,
  t        INTEGER NOT NULL,                       -- unix s UTC
  p        REAL NOT NULL CHECK (p BETWEEN 0 AND 1),
  PRIMARY KEY (token_id, t)
) WITHOUT ROWID;

CREATE TABLE evidence (
  evidence_id   TEXT PRIMARY KEY,                  -- sha256(url_norm|excerpt)
  url           TEXT NOT NULL,
  url_sha       TEXT NOT NULL,
  source_id     TEXT NOT NULL,
  tier          TEXT NOT NULL CHECK (tier IN ('A','B','C')),
  published_at  TEXT,
  retrieved_at  TEXT NOT NULL,
  excerpt       TEXT NOT NULL CHECK (length(excerpt) <= 300),
  content_sha   TEXT NOT NULL,
  excerpt_found INTEGER NOT NULL CHECK (excerpt_found IN (0,1))
);
CREATE INDEX ix_evidence_url ON evidence (url_sha);

CREATE TABLE analyses (
  analysis_id   TEXT PRIMARY KEY,
  idem_key      TEXT NOT NULL UNIQUE,              -- sha256(market_id|rules_sha|rules_version|revision)
  market_id     TEXT NOT NULL REFERENCES markets(market_id),
  rules_version TEXT NOT NULL,                     -- sha256(settings.toml + prompts/)
  revision      INTEGER NOT NULL CHECK (revision >= 0),
  cycle_id      TEXT NOT NULL,
  t0            TEXT NOT NULL,
  mid_t0        REAL NOT NULL CHECK (mid_t0 BETWEEN 0 AND 1),
  p_base        REAL CHECK (p_base BETWEEN 0 AND 1),
  p_model       REAL CHECK (p_model BETWEEN 0 AND 1),
  p_final       REAL CHECK (p_final BETWEEN 0 AND 1),
  shrink_w      REAL CHECK (shrink_w BETWEEN 0 AND 1),
  verdict       TEXT NOT NULL CHECK (verdict IN ('PICK_YES','PICK_NO','NO_TRADE','INSUFFICIENT_EVIDENCE')),
  analysis_json TEXT NOT NULL,                     -- valida contra el JSON Schema (d)
  cost_usd      REAL NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL
);
CREATE INDEX ix_analyses_market ON analyses (market_id, revision);
CREATE INDEX ix_analyses_cycle  ON analyses (cycle_id);

CREATE TABLE analysis_evidence (
  analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id),
  evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
  role        TEXT NOT NULL CHECK (role IN ('support','contra','context')),
  label       TEXT NOT NULL CHECK (label IN ('VERIFICADO','INFERIDO','ESPECULACION','SIN_VERIFICAR')),
  PRIMARY KEY (analysis_id, evidence_id)
);
CREATE INDEX ix_ae_evidence ON analysis_evidence (evidence_id);

CREATE TABLE forecasts (                           -- primer p_final congelado: base del scoring
  market_id   TEXT PRIMARY KEY REFERENCES markets(market_id),
  analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id),
  t0          TEXT NOT NULL,
  p_final     REAL NOT NULL,
  mid_t0      REAL NOT NULL,
  category    TEXT NOT NULL,
  horizon_d   REAL NOT NULL
);
CREATE TRIGGER trg_forecasts_immutable BEFORE UPDATE ON forecasts
BEGIN SELECT RAISE(ABORT, 'forecasts are immutable'); END;
CREATE TRIGGER trg_forecasts_nodelete BEFORE DELETE ON forecasts
BEGIN SELECT RAISE(ABORT, 'forecasts are immutable'); END;

CREATE TABLE decisions (
  decision_id   TEXT PRIMARY KEY,
  analysis_id   TEXT NOT NULL REFERENCES analyses(analysis_id),
  side          TEXT CHECK (side IN ('YES','NO')),
  vwap REAL, fee_per_share REAL, edge_net REAL,
  filters_json  TEXT NOT NULL,                     -- {"passed": bool, "failures": [...]}
  kelly_full REAL, stake_usd REAL, shares REAL,
  outcome       TEXT NOT NULL CHECK (outcome IN ('SIZED','NO_TRADE_FILTER','NO_TRADE_SIZE','NO_TRADE_CAP','NO_TRADE_STOP')),
  cluster_id    TEXT,
  created_at    TEXT NOT NULL
);
CREATE INDEX ix_decisions_analysis ON decisions (analysis_id);

CREATE TABLE positions (
  position_id TEXT PRIMARY KEY,
  decision_id TEXT NOT NULL REFERENCES decisions(decision_id),
  mode        TEXT NOT NULL CHECK (mode IN ('paper','live_6a','live_6b')),
  market_id   TEXT NOT NULL REFERENCES markets(market_id),
  side        TEXT NOT NULL CHECK (side IN ('YES','NO')),
  shares      REAL NOT NULL CHECK (shares > 0),
  entry_price REAL NOT NULL,
  fee_paid    REAL NOT NULL,
  opened_at   TEXT NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('open','settled','closed_early')),
  exit_price REAL, pnl_usd REAL, settled_at TEXT,
  clv_close   REAL,                                -- precio del lado al cierre - entry_price
  fill_ref    TEXT                                 -- vivo: referencia del fill manual
);
CREATE INDEX ix_positions_open ON positions (mode, status);
CREATE INDEX ix_positions_mkt  ON positions (market_id);

CREATE TABLE equity (
  mode TEXT NOT NULL, ts TEXT NOT NULL,
  bankroll REAL NOT NULL, mtm_equity REAL NOT NULL, peak REAL NOT NULL, drawdown REAL NOT NULL,
  PRIMARY KEY (mode, ts)
);

CREATE TABLE system_state (                        -- stop, presupuesto, flags
  key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE llm_calls (
  call_id TEXT PRIMARY KEY, ts TEXT NOT NULL, task TEXT NOT NULL, model TEXT NOT NULL,
  prompt_sha TEXT NOT NULL, market_id TEXT, batch INTEGER NOT NULL,
  input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, cost_usd REAL NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok','schema_violation','error'))
);
CREATE INDEX ix_llm_month ON llm_calls (substr(ts,1,7));

CREATE TABLE calibration_params (
  version TEXT PRIMARY KEY, fitted_at TEXT NOT NULL, n_train INTEGER NOT NULL,
  shrink_w REAL NOT NULL, platt_a REAL NOT NULL, platt_b REAL NOT NULL,
  bucket_table_json TEXT NOT NULL, oos_delta_brier REAL NOT NULL, active INTEGER NOT NULL
);

CREATE TABLE checkpoints (
  cycle_id TEXT NOT NULL, step TEXT NOT NULL, market_id TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK (status IN ('running','done','failed')),
  error TEXT, updated_at TEXT NOT NULL,
  PRIMARY KEY (cycle_id, step, market_id)
);
CREATE INDEX ix_checkpoints_status ON checkpoints (cycle_id, status);
