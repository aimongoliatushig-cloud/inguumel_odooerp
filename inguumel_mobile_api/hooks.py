# -*- coding: utf-8 -*-
"""
Init hooks for inguumel_mobile_api.

Used to migrate stock.warehouse x_aimag_id / x_sum_id from Integer columns
to Many2one: rename old columns before the ORM applies the new schema,
then copy data (0 -> NULL) and drop legacy columns after.
"""
import logging

_logger = logging.getLogger(__name__)

TABLE = "stock_warehouse"
LEGACY_AIMAG = "x_aimag_id_legacy"
LEGACY_SUM = "x_sum_id_legacy"
INT_TYPES = ("integer", "smallint", "bigint")


def pre_init_hook(env):
    """
    Run on install only. Rename existing integer columns so Odoo does not
    drop them when creating the new Many2one fields. For upgrades, use
    migrations/1.0.2/pre-rename_warehouse_location_columns.py.
    """
    cr = env.cr
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
            "inguumel_mobile_api pre_init_hook: could not check columns: %s",
            e,
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
                "inguumel_mobile_api pre_init_hook: rename x_aimag_id failed: %s",
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
                "inguumel_mobile_api pre_init_hook: rename x_sum_id failed: %s",
                e,
            )


def post_init_hook(env):
    """
    Run after the module is loaded (install only). Copy legacy integer values
    into the new Many2one columns (0 -> NULL), then drop legacy columns.
    For upgrades, use migrations/1.0.2/post-migrate_warehouse_location_data.py.
    """
    cr = env.cr
    try:
        cr.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name IN (%s, %s)
            """,
            (TABLE, LEGACY_AIMAG, LEGACY_SUM),
        )
        legacy_cols = [r[0] for r in cr.fetchall()]
    except Exception as e:
        _logger.warning(
            "inguumel_mobile_api post_init_hook: could not check legacy columns: %s",
            e,
        )
        return
    if not legacy_cols:
        return

    if LEGACY_AIMAG in legacy_cols:
        try:
            cr.execute(
                """
                UPDATE "{}" SET x_aimag_id = CASE
                    WHEN {} IS NOT NULL AND {} <> 0 THEN {}::integer
                    ELSE NULL
                END
                """.format(
                    TABLE, LEGACY_AIMAG, LEGACY_AIMAG, LEGACY_AIMAG
                )
            )
            cr.execute(
                'ALTER TABLE "{}" DROP COLUMN IF EXISTS "{}"'.format(
                    TABLE, LEGACY_AIMAG
                )
            )
            _logger.info(
                "inguumel_mobile_api: migrated and dropped %s", LEGACY_AIMAG
            )
        except Exception as e:
            _logger.warning(
                "inguumel_mobile_api post_init_hook: migrate aimag failed: %s",
                e,
            )
    if LEGACY_SUM in legacy_cols:
        try:
            cr.execute(
                """
                UPDATE "{}" SET x_sum_id = CASE
                    WHEN {} IS NOT NULL AND {} <> 0 THEN {}::integer
                    ELSE NULL
                END
                """.format(
                    TABLE, LEGACY_SUM, LEGACY_SUM, LEGACY_SUM
                )
            )
            cr.execute(
                'ALTER TABLE "{}" DROP COLUMN IF EXISTS "{}"'.format(
                    TABLE, LEGACY_SUM
                )
            )
            _logger.info(
                "inguumel_mobile_api: migrated and dropped %s", LEGACY_SUM
            )
        except Exception as e:
            _logger.warning(
                "inguumel_mobile_api post_init_hook: migrate sum failed: %s", e
            )

    try:
        cr.execute(
            """
            SELECT id, name FROM "{}"
            WHERE x_aimag_id IS NULL OR x_sum_id IS NULL
            """.format(
                TABLE
            )
        )
        missing = cr.fetchall()
        for row in missing:
            _logger.warning(
                "inguumel_mobile_api: warehouse id=%s name=%r has no aimag/sum mapping",
                row[0],
                row[1],
            )
    except Exception as e:
        _logger.debug(
            "inguumel_mobile_api post_init_hook: check missing mapping: %s", e
        )
