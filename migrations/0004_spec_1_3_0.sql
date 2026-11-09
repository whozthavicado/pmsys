-- 0004: spec 1.3.0 (C1, C2, C3, C4, C6, C9)
-- C1 + C2: modo live_6b_c y estado de CLV (SQLite no altera CHECK: se reconstruye positions; aún sin datos)
CREATE TABLE positions_v13 (
  position_id TEXT PRIMARY KEY,
  decision_id TEXT NOT NULL REFERENCES decisions(decision_id),
  mode        TEXT NOT NULL CHECK (mode IN ('paper','live_6a','live_6b','live_6b_c')),
  market_id   TEXT NOT NULL REFERENCES markets(market_id),
  side        TEXT NOT NULL CHECK (side IN ('YES','NO')),
  shares      REAL NOT NULL CHECK (shares > 0),
  entry_price REAL NOT NULL,
  fee_paid    REAL NOT NULL,
  opened_at   TEXT NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('open','settled','closed_early')),
  exit_price REAL, pnl_usd REAL, settled_at TEXT,
  clv_close   REAL,
  fill_ref    TEXT,
  t_clv       TEXT,
  clv_h       REAL,
  clv_status  TEXT NOT NULL DEFAULT 'pending' CHECK (clv_status IN ('pending','measured','unmeasurable'))
);
INSERT INTO positions_v13
  (position_id, decision_id, mode, market_id, side, shares, entry_price, fee_paid, opened_at, status,
   exit_price, pnl_usd, settled_at, clv_close, fill_ref, t_clv, clv_h, clv_status)
SELECT position_id, decision_id, mode, market_id, side, shares, entry_price, fee_paid, opened_at, status,
       exit_price, pnl_usd, settled_at, clv_close, fill_ref, t_clv, clv_h,
       CASE WHEN clv_h IS NULL THEN 'pending' ELSE 'measured' END
FROM positions;
DROP TABLE positions;
ALTER TABLE positions_v13 RENAME TO positions;
CREATE INDEX ix_positions_open ON positions (mode, status);
CREATE INDEX ix_positions_mkt  ON positions (market_id);
CREATE TRIGGER trg_positions_clv_after_entry BEFORE UPDATE OF t_clv ON positions
WHEN NEW.t_clv IS NOT NULL AND NEW.clv_status = 'measured'
 AND (julianday(NEW.t_clv) - julianday(NEW.opened_at)) * 24 < 6
BEGIN SELECT RAISE(ABORT, 'C2: t_clv must be >= opened_at + 6 h'); END;
ALTER TABLE shadow_picks ADD COLUMN clv_status TEXT NOT NULL DEFAULT 'pending'
  CHECK (clv_status IN ('pending','measured','unmeasurable'));

-- C9: un mercado cuenta una vez en P4; prevalece el registro vivo; 6a excluido (1.2/M2)
CREATE VIEW v_p4_picks AS
WITH ranked AS (
  SELECT p.*,
         ROW_NUMBER() OVER (
           PARTITION BY p.market_id
           ORDER BY CASE WHEN p.mode IN ('live_6b','live_6b_c') THEN 0 ELSE 1 END, p.opened_at, p.position_id
         ) AS rn
  FROM positions p
  WHERE p.mode IN ('paper','live_6b','live_6b_c')
)
SELECT * FROM ranked WHERE rn = 1 AND clv_status = 'measured';

-- C3: versiones de sesgo inmutables, sin solapes; registro de caída a identidad
CREATE TRIGGER trg_calib_noupdate BEFORE UPDATE ON calibration_params
BEGIN SELECT RAISE(ABORT, 'calibration_params are immutable'); END;
CREATE TRIGGER trg_calib_nodelete BEFORE DELETE ON calibration_params
BEGIN SELECT RAISE(ABORT, 'calibration_params are immutable'); END;
CREATE TRIGGER trg_calib_no_overlap BEFORE INSERT ON calibration_params
WHEN NEW.version <> 'identity-v0' AND EXISTS (
  SELECT 1 FROM calibration_params cp
  WHERE cp.version <> 'identity-v0'
    AND NEW.applies_from_utc < cp.applies_to_utc
    AND cp.applies_from_utc < NEW.applies_to_utc)
BEGIN SELECT RAISE(ABORT, 'C3: overlapping bias versions'); END;
CREATE TABLE bias_fallback_log (
  market_id           TEXT NOT NULL REFERENCES markets(market_id),
  t0                  TEXT NOT NULL,
  last_fitted_version TEXT NOT NULL,
  last_applies_to_utc TEXT NOT NULL,
  PRIMARY KEY (market_id, t0)
);
CREATE TRIGGER trg_forecasts_bias_fallback AFTER INSERT ON forecasts
WHEN NEW.bias_version = 'identity-v0' AND EXISTS (
  SELECT 1 FROM calibration_params cp
  WHERE cp.version <> 'identity-v0' AND cp.applies_to_utc <= NEW.t0)
BEGIN
  INSERT INTO bias_fallback_log
  SELECT NEW.market_id, NEW.t0, cp.version, cp.applies_to_utc
  FROM calibration_params cp
  WHERE cp.version <> 'identity-v0' AND cp.applies_to_utc <= NEW.t0
  ORDER BY cp.applies_to_utc DESC LIMIT 1;
END;

-- C4: sumas ponderadas (w = 1 / p_incl_triage; 1 si es NULL)
ALTER TABLE selection_members_agg ADD COLUMN sum_w           REAL;
ALTER TABLE selection_members_agg ADD COLUMN sum_w_horizon   REAL;
ALTER TABLE selection_members_agg ADD COLUMN sumsq_w_horizon REAL;
ALTER TABLE selection_members_agg ADD COLUMN sum_w_absmid    REAL;
ALTER TABLE selection_members_agg ADD COLUMN sumsq_w_absmid  REAL;
ALTER TABLE selection_members_agg ADD COLUMN sum_w_logvol    REAL;
ALTER TABLE selection_members_agg ADD COLUMN sumsq_w_logvol  REAL;

-- C6: VERIFICADO exige excerpt_found = 1
CREATE TRIGGER trg_ae_verified_needs_excerpt BEFORE INSERT ON analysis_evidence
WHEN NEW.label = 'VERIFICADO'
 AND COALESCE((SELECT excerpt_found FROM evidence e WHERE e.evidence_id = NEW.evidence_id), 0) = 0
BEGIN SELECT RAISE(ABORT, 'C6: VERIFICADO requires excerpt_found = 1'); END;
