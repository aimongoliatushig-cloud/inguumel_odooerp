# -*- coding: utf-8 -*-
"""
Post-migrate (1.0.2): copy legacy integer values into the new Many2one columns
(they store the same ID in the DB), convert 0 -> NULL, drop legacy columns,
and log warnings for warehouses missing mapping.
"""
import logging

_logger = logging.getLogger(__name__)

TABLE = "stock_warehouse"
LEGACY_AIMAG = "x_aimag_id_legacy"
LEGACY_SUM = "x_sum_id_legacy"


def migrate(cr, version):
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
            "inguumel_mobile_api post-migrate: could not check legacy columns: %s",
            e,
        )
        return
    if not legacy_cols:
        return

    # Copy legacy -> new; convert 0 to NULL (invalid FK).
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
                "inguumel_mobile_api post-migrate: migrate aimag failed: %s", e
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
                "inguumel_mobile_api post-migrate: migrate sum failed: %s", e
            )

    # Log warehouses missing mapping (no aimag/sum after migration).
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
            "inguumel_mobile_api post-migrate: check missing mapping: %s", e
        )
