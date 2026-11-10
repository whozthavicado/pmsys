-- 0002: spec 1.1.0 (D1, D2, D3, D4, D5, D6)
-- D4: precio en el instante de congelar la evidencia
ALTER TABLE analyses  ADD COLUMN t_evidence     TEXT;
ALTER TABLE analyses  ADD COLUMN mid_t_evidence REAL CHECK (mid_t_evidence BETWEEN 0 AND 1);
ALTER TABLE forecasts ADD COLUMN t_evidence     TEXT;
ALTER TABLE forecasts ADD COLUMN mid_t_evidence REAL CHECK (mid_t_evidence BETWEEN 0 AND 1);
ALTER TABLE forecasts ADD COLUMN bias_version   TEXT;
ALTER TABLE forecasts ADD COLUMN class_sha      TEXT;

-- D4 + D5 + D6: invariantes en filas nuevas (ADD COLUMN no admite NOT NULL sin DEFAULT)
CREATE TRIGGER trg_analyses_evidence_required BEFORE INSERT ON analyses
WHEN NEW.t_evidence IS NULL OR NEW.mid_t_evidence IS NULL
BEGIN SELECT RAISE(ABORT, 'analyses.t_evidence/mid_t_evidence required'); END;

CREATE TRIGGER trg_forecasts_v11_required BEFORE INSERT ON forecasts
WHEN NEW.t_evidence IS NULL OR NEW.mid_t_evidence IS NULL OR NEW.bias_version IS NULL
  OR NEW.t_evidence > NEW.t0
  OR NEW.category NOT IN ('a','b','c','d')
BEGIN SELECT RAISE(ABORT, 'forecast invariant violated (D4/D5/D6)'); END;

-- D1: CLV a horizonte fijo, medible antes de la resolución
ALTER TABLE positions ADD COLUMN t_clv TEXT;
ALTER TABLE positions ADD COLUMN clv_h REAL;      -- mid del lado en t_clv - coste de entrada por acción
CREATE TABLE shadow_picks (                        -- D1: NO_TRADE_SIZE, solo indicador (M10)
  decision_id TEXT PRIMARY KEY REFERENCES decisions(decision_id),
  market_id   TEXT NOT NULL REFERENCES markets(market_id),
  side        TEXT NOT NULL CHECK (side IN ('YES','NO')),
  entry_cost  REAL NOT NULL,                       -- VWAP del tamaño mínimo + comisión
  t_entry     TEXT NOT NULL,
  t_clv       TEXT,
  clv_h       REAL
);

-- D2: tipo de evento y clases de referencia congeladas
CREATE TABLE market_event_type (
  market_id          TEXT NOT NULL REFERENCES markets(market_id),
  rules_sha          TEXT NOT NULL,
  classifier_version TEXT NOT NULL,
  event_type         TEXT NOT NULL,
  event_family       TEXT NOT NULL,
  yes_is_change      INTEGER NOT NULL CHECK (yes_is_change IN (0,1)),
  method             TEXT NOT NULL CHECK (method IN ('rule','llm')),
  rule_id            TEXT,
  created_at         TEXT NOT NULL,
  PRIMARY KEY (market_id, rules_sha, classifier_version)
);
CREATE INDEX ix_met_class ON market_event_type (classifier_version, event_type, yes_is_change);

CREATE TABLE ref_classes (
  class_sha   TEXT PRIMARY KEY,                    -- sha256(canonical_json(RefClassQuery))
  query_json  TEXT NOT NULL,
  level       INTEGER NOT NULL CHECK (level BETWEEN 0 AND 4),
  as_of       TEXT NOT NULL,
  n           INTEGER NOT NULL CHECK (n >= 20),
  k           INTEGER NOT NULL CHECK (k BETWEEN 0 AND n),
  members_sha TEXT NOT NULL,
  created_at  TEXT NOT NULL
);
CREATE TABLE ref_class_members (
  class_sha TEXT NOT NULL REFERENCES ref_classes(class_sha),
  market_id TEXT NOT NULL REFERENCES markets(market_id),
  PRIMARY KEY (class_sha, market_id)
) WITHOUT ROWID;
CREATE TABLE market_ref_class (
  market_id     TEXT NOT NULL REFERENCES markets(market_id),
  rules_sha     TEXT NOT NULL,
  rules_version TEXT NOT NULL,
  class_sha     TEXT NOT NULL REFERENCES ref_classes(class_sha),
  PRIMARY KEY (market_id, rules_sha, rules_version)
);
CREATE TRIGGER trg_market_ref_class_immutable BEFORE UPDATE ON market_ref_class
BEGIN SELECT RAISE(ABORT, 'ref class is frozen'); END;

-- D3: selección auditable
CREATE TABLE selection_runs (
  cycle_id      TEXT PRIMARY KEY,
  started_at    TEXT NOT NULL,
  params_json   TEXT NOT NULL,                     -- tags, end_date_min/max, rules_version
  pages_fetched INTEGER NOT NULL,
  n_raw         INTEGER NOT NULL,
  n_dedup       INTEGER NOT NULL,
  n_eligible    INTEGER NOT NULL,
  n_triage_pool INTEGER NOT NULL,
  n_triaged     INTEGER NOT NULL,
  n_forecast    INTEGER NOT NULL,
  universe_sha  TEXT NOT NULL,                     -- sha256 de market_id elegibles ordenados
  status        TEXT NOT NULL CHECK (status IN ('complete','failed'))
);
CREATE TABLE selection_members (
  cycle_id          TEXT NOT NULL REFERENCES selection_runs(cycle_id),
  market_id         TEXT NOT NULL,
  category          TEXT NOT NULL,
  horizon_days      REAL,
  mid_at_selection  REAL,
  vol_24h_usd       REAL,                          -- solo auditoría; nunca ordena ni filtra
  liquidity_usd     REAL,                          -- idem
  eligible          INTEGER NOT NULL CHECK (eligible IN (0,1)),
  exclusion_reason  TEXT,                          -- E1..E6, REFCLASS_EXHAUSTED
  pool              TEXT CHECK (pool IN ('new','retriage')),
  rank_key          TEXT,
  stratum_size      INTEGER,
  quota             INTEGER,
  p_incl_triage     REAL,
  triaged           INTEGER NOT NULL DEFAULT 0,
  triage_analyzable INTEGER,
  p_incl_forecast   REAL,
  forecast_selected INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (cycle_id, market_id)
);
CREATE INDEX ix_selm_market    ON selection_members (market_id);
CREATE INDEX ix_selm_cycle_sel ON selection_members (cycle_id, forecast_selected);

-- D5: corte temporal de la tabla de sesgo
ALTER TABLE calibration_params ADD COLUMN fit_from_utc     TEXT;
ALTER TABLE calibration_params ADD COLUMN cutoff_utc       TEXT;  -- fin exclusivo de la ventana de ajuste
ALTER TABLE calibration_params ADD COLUMN applies_from_utc TEXT;
ALTER TABLE calibration_params ADD COLUMN applies_to_utc   TEXT;
ALTER TABLE calibration_params ADD COLUMN n_cells_ok       INTEGER;
ALTER TABLE calibration_params ADD COLUMN n_cells_pooled   INTEGER;
ALTER TABLE calibration_params ADD COLUMN n_cells_identity INTEGER;
CREATE TRIGGER trg_calib_cutoff BEFORE INSERT ON calibration_params
WHEN NEW.cutoff_utc IS NULL OR NEW.applies_from_utc < NEW.cutoff_utc
BEGIN SELECT RAISE(ABORT, 'bias table applied before its cutoff'); END;
