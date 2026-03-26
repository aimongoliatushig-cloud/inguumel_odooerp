# -*- coding: utf-8 -*-
"""
Post-migrate: copy legacy integer values into the new Many2one columns
(they store the same ID in the DB), then drop legacy columns.
"""
import logging

_logger = logging.getLogger(__name__)

TABLE = "stock_warehouse"
LEGACY_AIMAG = "x_aimag_id_legacy"
LEGACY_SUM = "x_sum_id_legacy"


def migrate(cr, version):
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
    if not legacy_cols:
        return
    if LEGACY_AIMAG in legacy_cols:
        cr.execute(
            'UPDATE "{}" SET x_aimag_id = {} WHERE {} IS NOT NULL'.format(
                TABLE, LEGACY_AIMAG, LEGACY_AIMAG
            )
        )
        cr.execute('ALTER TABLE "{}" DROP COLUMN IF EXISTS {}'.format(TABLE, LEGACY_AIMAG))
        _logger.info("inguumel_mobile_api: migrated and dropped %s", LEGACY_AIMAG)
    if LEGACY_SUM in legacy_cols:
        cr.execute(
            'UPDATE "{}" SET x_sum_id = {} WHERE {} IS NOT NULL'.format(
                TABLE, LEGACY_SUM, LEGACY_SUM
            )
        )
        cr.execute('ALTER TABLE "{}" DROP COLUMN IF EXISTS {}'.format(TABLE, LEGACY_SUM))
        _logger.info("inguumel_mobile_api: migrated and dropped %s", LEGACY_SUM)
