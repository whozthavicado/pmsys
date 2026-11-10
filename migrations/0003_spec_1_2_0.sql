-- 0003: spec 1.2.0 (B5, 1.2/M4, 1.2/M5, 1.2/M6, 1.2/M7)
-- B5: analyses inmutable; t_evidence <= t0 también en analyses
CREATE TRIGGER trg_analyses_immutable BEFORE UPDATE ON analyses
BEGIN SELECT RAISE(ABORT, 'analyses are immutable; write a new revision'); END;
CREATE TRIGGER trg_analyses_nodelete BEFORE DELETE ON analyses
BEGIN SELECT RAISE(ABORT, 'analyses are immutable'); END;
DROP TRIGGER trg_analyses_evidence_required;
CREATE TRIGGER trg_analyses_evidence_required BEFORE INSERT ON analyses
WHEN NEW.t_evidence IS NULL OR NEW.mid_t_evidence IS NULL OR NEW.t_evidence > NEW.t0
BEGIN SELECT RAISE(ABORT, 'analyses: t_evidence/mid_t_evidence required and t_evidence <= t0'); END;

-- 1.2/M4: versión identidad sembrada; el forecast exige una bias_version existente y vigente en t0
INSERT INTO calibration_params
  (version, fitted_at, n_train, shrink_w, platt_a, platt_b, bucket_table_json, oos_delta_brier, active,
   fit_from_utc, cutoff_utc, applies_from_utc, applies_to_utc, n_cells_ok, n_cells_pooled, n_cells_identity)
VALUES ('identity-v0', '2026-11-05T00:00:00Z', 0, 0.30, 0.0, 1.0, '{"mode":"identity"}', 0.0, 1,
        '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', '1970-01-01T00:00:00Z', '9999-12-31T23:59:59Z', 0, 0, 0);
DROP TRIGGER trg_forecasts_v11_required;
CREATE TRIGGER trg_forecasts_v12_required BEFORE INSERT ON forecasts
WHEN NEW.t_evidence IS NULL OR NEW.mid_t_evidence IS NULL OR NEW.bias_version IS NULL
  OR NEW.t_evidence > NEW.t0
  OR NEW.category NOT IN ('a','b','c','d')
  OR NOT EXISTS (SELECT 1 FROM calibration_params cp
                 WHERE cp.version = NEW.bias_version
                   AND NEW.t0 >= cp.applies_from_utc AND NEW.t0 < cp.applies_to_utc)
  OR (NEW.bias_version = 'identity-v0' AND EXISTS (
        SELECT 1 FROM calibration_params cp
        WHERE cp.version <> 'identity-v0'
          AND NEW.t0 >= cp.applies_from_utc AND NEW.t0 < cp.applies_to_utc))
BEGIN SELECT RAISE(ABORT, 'forecast invariant violated (D4/D5/D6/M4)'); END;

-- 1.2/M5: agregados para compactar selection_members
CREATE TABLE selection_members_agg (
  cycle_id         TEXT NOT NULL REFERENCES selection_runs(cycle_id),
  category         TEXT NOT NULL,
  eligible         INTEGER NOT NULL CHECK (eligible IN (0,1)),
  exclusion_reason TEXT NOT NULL DEFAULT '',
  pool             TEXT NOT NULL DEFAULT '',
  n                INTEGER NOT NULL CHECK (n > 0),
  sum_horizon REAL, sumsq_horizon REAL,
  sum_absmid  REAL, sumsq_absmid  REAL,            -- |mid - 0.5|
  sum_logvol  REAL, sumsq_logvol  REAL,            -- log(1 + vol_24h_usd)
  PRIMARY KEY (cycle_id, category, eligible, exclusion_reason, pool)
);

-- 1.2/M6: clases de referencia no borrables ni editables
CREATE TRIGGER trg_ref_classes_nodelete BEFORE DELETE ON ref_classes
BEGIN SELECT RAISE(ABORT, 'ref classes are frozen'); END;
CREATE TRIGGER trg_ref_classes_noupdate BEFORE UPDATE ON ref_classes
BEGIN SELECT RAISE(ABORT, 'ref classes are frozen'); END;
CREATE TRIGGER trg_ref_class_members_nodelete BEFORE DELETE ON ref_class_members
BEGIN SELECT RAISE(ABORT, 'ref classes are frozen'); END;
CREATE TRIGGER trg_market_ref_class_nodelete BEFORE DELETE ON market_ref_class
BEGIN SELECT RAISE(ABORT, 'ref class is frozen'); END;

-- 1.2/M7: milisegundos en book_snapshots.ts y equity.ts
CREATE TRIGGER trg_book_ts_ms BEFORE INSERT ON book_snapshots
WHEN NEW.ts NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'
BEGIN SELECT RAISE(ABORT, 'book_snapshots.ts must be YYYY-MM-DDTHH:MM:SS.sssZ'); END;
CREATE TRIGGER trg_equity_ts_ms BEFORE INSERT ON equity
WHEN NEW.ts NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'
BEGIN SELECT RAISE(ABORT, 'equity.ts must be YYYY-MM-DDTHH:MM:SS.sssZ'); END;
