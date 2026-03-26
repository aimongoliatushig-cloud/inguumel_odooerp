#!/usr/bin/env bash
# Upgrade Inguumel custom modules (run where Odoo is installed).
# Usage:
#   ./upgrade_modules.sh                    # uses DB=odoo
#   DB=mydb ./upgrade_modules.sh            # upgrade database 'mydb'
#   ODOO_CONF=/etc/odoo/odoo.conf ./upgrade_modules.sh

set -e
DB="${DB:-odoo}"
ODOO_CONF="${ODOO_CONF:-}"
ADDONS_PATH="${ADDONS_PATH:-}"
# If you use odoo-bin directly, set ODOO_CMD to full path, e.g.:
# ODOO_CMD="/opt/odoo/odoo19/odoo-bin"
ODOO_CMD="${ODOO_CMD:-odoo}"

if [[ -n "$ODOO_CONF" ]]; then
  CONF_ARGS=(-c "$ODOO_CONF")
else
  CONF_ARGS=()
fi

if [[ -n "$ADDONS_PATH" ]]; then
  PATH_ARGS=(--addons-path="$ADDONS_PATH")
else
  PATH_ARGS=()
fi

echo "Upgrading modules (DB=$DB)..."
"$ODOO_CMD" "${CONF_ARGS[@]}" "${PATH_ARGS[@]}" -d "$DB" \
  -u inguumel_mobile_api,inguumel_order_mxm,inguumel_catalog_mxm \
  --stop-after-init

echo "Done. Restart Odoo service if it is running."
