# -*- coding: utf-8 -*-
"""
Standard JSON response helpers and request_id for mobile API.
"""
import json
import logging
import uuid

from werkzeug.wrappers import Response

_logger = logging.getLogger(__name__)


def get_request_id():
    """Generate a unique request identifier (UUID4 string)."""
    return str(uuid.uuid4())


def ok(data=None, message="OK", code="OK", meta=None, request_id=None):
    """
    Build a success JSON response following the standard format.

    :param data: Optional payload (any JSON-serializable value).
    :param message: Human-readable message.
    :param code: Application code (default "OK").
    :param meta: Optional metadata (e.g. pagination).
    :param request_id: Optional request identifier for tracing.
    :return: werkzeug Response with status 200 and application/json.
    """
    payload = {
        "success": True,
        "code": code,
        "message": message,
        "request_id": request_id,
        "data": data,
        "meta": meta,
    }
    body = json.dumps(payload, default=str)
    return Response(
        body,
        status=200,
        mimetype="application/json",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )


def fail(
    message,
    code="ERROR",
    http_status=400,
    data=None,
    errors=None,
    meta=None,
    request_id=None,
):
    """
    Build a failure JSON response following the standard format.

    :param message: Human-readable error message.
    :param code: Application error code (default "ERROR").
    :param http_status: HTTP status code (default 400).
    :param data: Optional extra data (e.g. validation errors).
    :param errors: Optional list/dict of field-level validation errors.
    :param meta: Optional metadata.
    :param request_id: Optional request identifier for tracing.
    :return: werkzeug Response with given status and application/json.
    """
    payload = {
        "success": False,
        "code": code,
        "message": message,
        "request_id": request_id,
        "errors": errors,
        "data": data,
        "meta": meta,
    }
    body = json.dumps(payload, default=str)
    return Response(
        body,
        status=http_status,
        mimetype="application/json",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )


def ok_payload(data=None, message="OK", code="OK", meta=None, request_id=None):
    """
    Build a success payload dict (same format as ok()) for type='json' routes.
    Return this dict from the controller; Odoo will serialize it to JSON.
    """
    return {
        "success": True,
        "code": code,
        "message": message,
        "request_id": request_id,
        "data": data,
        "meta": meta,
    }


def fail_payload(
    message,
    code="ERROR",
    http_status=400,
    data=None,
    errors=None,
    meta=None,
    request_id=None,
):
    """
    Build a failure response for type='http' routes.

    Accepts http_status and returns odoo.http.Response (werkzeug Response)
    with proper status code and JSON body.

    Standard body: { success, code, message, request_id, errors, data, meta }
    """
    payload = {
        "success": False,
        "code": code,
        "message": message,
        "request_id": request_id,
        "errors": errors,
        "data": data,
        "meta": meta,
    }
    body = json.dumps(payload, default=str)
    return Response(
        body,
        status=http_status,
        mimetype="application/json",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )


def fail_payload_dict(message, code="ERROR", data=None, errors=None, meta=None, request_id=None):
    """
    Build a failure payload dict for type='json'/'jsonrpc' routes.
    Returns dict (not Response) since jsonrpc cannot set HTTP status from controller.
    """
    return {
        "success": False,
        "code": code,
        "message": message,
        "request_id": request_id,
        "errors": errors,
        "data": data,
        "meta": meta,
    }
