# -*- coding: utf-8 -*-
"""
Pre-migrate (1.0.2): rename stock.warehouse integer columns before the ORM
applies the new Many2one fields, so existing data is preserved.
Runs when upgrading to 1.0.2 (e.g. from 1.0.0 or 1.0.1 with broken integer columns).
"""
import logging

_logger = logging.getLogger(__name__)

TABLE = "stock_warehouse"
LEGACY_AIMAG = "x_aimag_id_legacy"
LEGACY_SUM = "x_sum_id_legacy"
INT_TYPES = ("integer", "smallint", "bigint")


def migrate(cr, version):
    try:
        cr.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name IN ('x_aimag_id', 'x_sum_id')
            """,
            (TABLE,),
        )
        rows = cr.fetchall()
    except Exception as e:
        _logger.warning(
            "inguumel_mobile_api pre-migrate: could not check columns: %s", e
        )
        return
    col_map = {r[0]: r[1] for r in rows}
    if "x_aimag_id" in col_map and col_map["x_aimag_id"] in INT_TYPES:
        try:
            cr.execute(
                'ALTER TABLE "{}" RENAME COLUMN x_aimag_id TO {}'.format(
                    TABLE, LEGACY_AIMAG
                )
            )
            _logger.info(
                "inguumel_mobile_api: renamed x_aimag_id -> %s", LEGACY_AIMAG
            )
        except Exception as e:
            _logger.warning(
                "inguumel_mobile_api pre-migrate: rename x_aimag_id failed: %s",
                e,
            )
    if "x_sum_id" in col_map and col_map["x_sum_id"] in INT_TYPES:
        try:
            cr.execute(
                'ALTER TABLE "{}" RENAME COLUMN x_sum_id TO {}'.format(
                    TABLE, LEGACY_SUM
                )
            )
            _logger.info("inguumel_mobile_api: renamed x_sum_id -> %s", LEGACY_SUM)
        except Exception as e:
            _logger.warning(
                "inguumel_mobile_api pre-migrate: rename x_sum_id failed: %s",
                e,
            )
