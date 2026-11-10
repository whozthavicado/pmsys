-- 0005: spec 1.4.0 (contigüidad de calibration_params; t_clv terminal)
-- Se ejecuta con el protocolo de migración de 1.4.0 (foreign_keys=OFF fuera de transacción + foreign_key_check).

-- Contigüidad: exactamente una versión abierta (applies_to_utc NULL); cada alta cierra la anterior
DROP TRIGGER trg_calib_noupdate;          -- 0004: inmutable total; se sustituye por "solo cierre"
DROP TRIGGER trg_calib_no_overlap;        -- 0004: el solape queda imposible por construcción
DROP TRIGGER trg_forecasts_bias_fallback; -- 0004: la caída a identidad queda imposible tras la primera versión ajustada
DROP TABLE bias_fallback_log;
UPDATE calibration_params SET applies_to_utc = NULL
 WHERE version = 'identity-v0'
   AND NOT EXISTS (SELECT 1 FROM calibration_params WHERE version <> 'identity-v0');
CREATE UNIQUE INDEX ux_calib_single_open ON calibration_params ((1)) WHERE applies_to_utc IS NULL;

CREATE TRIGGER trg_calib_close_only BEFORE UPDATE ON calibration_params
WHEN NOT (OLD.applies_to_utc IS NULL AND NEW.applies_to_utc IS NOT NULL
      AND NEW.version IS OLD.version AND NEW.fitted_at IS OLD.fitted_at AND NEW.n_train IS OLD.n_train
      AND NEW.shrink_w IS OLD.shrink_w AND NEW.platt_a IS OLD.platt_a AND NEW.platt_b IS OLD.platt_b
      AND NEW.bucket_table_json IS OLD.bucket_table_json AND NEW.oos_delta_brier IS OLD.oos_delta_brier
      AND NEW.active IS OLD.active AND NEW.fit_from_utc IS OLD.fit_from_utc AND NEW.cutoff_utc IS OLD.cutoff_utc
      AND NEW.applies_from_utc IS OLD.applies_from_utc AND NEW.n_cells_ok IS OLD.n_cells_ok
      AND NEW.n_cells_pooled IS OLD.n_cells_pooled AND NEW.n_cells_identity IS OLD.n_cells_identity)
BEGIN SELECT RAISE(ABORT, 'calibration_params: only closing the open version is allowed'); END;

CREATE TRIGGER trg_calib_append BEFORE INSERT ON calibration_params
BEGIN
  SELECT RAISE(ABORT, 'contiguity: new version must be open (applies_to_utc NULL)')
   WHERE NEW.applies_to_utc IS NOT NULL;
  SELECT RAISE(ABORT, 'contiguity: applies_from must be after the open version start')
   WHERE NEW.applies_from_utc <= (SELECT applies_from_utc FROM calibration_params WHERE applies_to_utc IS NULL);
  SELECT RAISE(ABORT, 'contiguity: would reassign existing forecasts')
   WHERE EXISTS (SELECT 1 FROM forecasts f WHERE f.t0 >= NEW.applies_from_utc);
  UPDATE calibration_params SET applies_to_utc = NEW.applies_from_utc WHERE applies_to_utc IS NULL;
END;

-- El trigger de forecasts admite la versión abierta (applies_to_utc NULL)
DROP TRIGGER trg_forecasts_v12_required;
CREATE TRIGGER trg_forecasts_v14_required BEFORE INSERT ON forecasts
WHEN NEW.t_evidence IS NULL OR NEW.mid_t_evidence IS NULL OR NEW.bias_version IS NULL
  OR NEW.t_evidence > NEW.t0
  OR NEW.category NOT IN ('a','b','c','d')
  OR NOT EXISTS (SELECT 1 FROM calibration_params cp
                 WHERE cp.version = NEW.bias_version
                   AND NEW.t0 >= cp.applies_from_utc
                   AND NEW.t0 < COALESCE(cp.applies_to_utc, '9999-12-31T23:59:59Z'))
BEGIN SELECT RAISE(ABORT, 'forecast invariant violated (D4/D5/D6/M4/1.4)'); END;

-- t_clv terminal: base de medición y suelo de 6 h solo para las bases standard y early_24h
ALTER TABLE positions    ADD COLUMN clv_basis TEXT CHECK (clv_basis IN ('standard','early_24h','terminal_1h'));
ALTER TABLE shadow_picks ADD COLUMN clv_basis TEXT CHECK (clv_basis IN ('standard','early_24h','terminal_1h'));
DROP TRIGGER trg_positions_clv_after_entry;
CREATE TRIGGER trg_positions_clv_v14 BEFORE UPDATE OF t_clv, clv_status, clv_basis ON positions
WHEN NEW.clv_status = 'measured' AND (
      NEW.t_clv IS NULL OR NEW.clv_basis IS NULL
   OR julianday(NEW.t_clv) <= julianday(NEW.opened_at)
   OR (NEW.clv_basis IN ('standard','early_24h') AND (julianday(NEW.t_clv) - julianday(NEW.opened_at)) * 24 < 6))
BEGIN SELECT RAISE(ABORT, 't_clv rule violated (1.4)'); END;
