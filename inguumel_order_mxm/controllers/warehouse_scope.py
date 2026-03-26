# -*- coding: utf-8 -*-
"""
Warehouse scope helpers for order access control.
"""
import logging

_logger = logging.getLogger(__name__)


def is_warehouse_owner(user):
    """
    Return True when user has assigned warehouses (x_warehouse_ids).
    Safe if field is missing or user is invalid.
    """
    try:
        if not user:
            return False
        wh_ids = getattr(user, "x_warehouse_ids", None)
        return bool(wh_ids and wh_ids.ids)
    except Exception as err:
        _logger.warning("warehouse_scope.is_warehouse_owner error: %s", err)
        return False


def get_warehouse_owner_warehouse_ids(user):
    """
    Return list of warehouse IDs for warehouse owner.
    Returns None for non-warehouse owners (so callers can fall back to partner scope).
    """
    try:
        if not is_warehouse_owner(user):
            return None
        wh_ids = getattr(user, "x_warehouse_ids", None)
        return list(wh_ids.ids) if wh_ids else []
    except Exception as err:
        _logger.warning("warehouse_scope.get_warehouse_owner_warehouse_ids error: %s", err)
        return None


def order_in_warehouse_scope(order, user):
    """
    True when order.warehouse_id is within user's warehouse scope.
    Returns False if user is not a warehouse owner or on any error.
    """
    try:
        wh_ids = get_warehouse_owner_warehouse_ids(user)
        if not wh_ids:
            return False
        warehouse = getattr(order, "warehouse_id", None)
        if not warehouse or not warehouse.exists():
            return False
        return warehouse.id in wh_ids
    except Exception as err:
        _logger.warning("warehouse_scope.order_in_warehouse_scope error: %s", err)
        return False
