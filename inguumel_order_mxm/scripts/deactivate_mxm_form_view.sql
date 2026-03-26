-- Emergency fix: set MXM stock picking form view INACTIVE in DB so Odoo stops loading it.
-- Run when Odoo is stopped. Use the same user that Odoo uses to connect to PostgreSQL.
--
-- If PostgreSQL uses peer auth (FATAL: Peer authentication failed), run as the DB user:
--   sudo -u odoo psql -d InguumelStage -f deactivate_mxm_form_view.sql
--
-- Or as postgres superuser:
--   sudo -u postgres psql -d InguumelStage -f deactivate_mxm_form_view.sql
--
-- Replace InguumelStage with your database name if different.

UPDATE ir_ui_view
SET active = false
WHERE id = (
    SELECT res_id
    FROM ir_model_data
    WHERE module = 'inguumel_order_mxm'
      AND name = 'view_picking_form_mxm'
      AND model = 'ir.ui.view'
    LIMIT 1
);
