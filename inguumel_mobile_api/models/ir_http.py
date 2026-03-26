# -*- coding: utf-8 -*-
"""Bearer auth for /api/v1: resolve token → uid; set request.env and (after base) session.uid.

- Client sends: Authorization: Bearer <access_token> (from POST /api/v1/auth/login).
- We set request.update_env(user=uid) in _authenticate so _auth_method_public does not
  override to public (it only sets public when request.env.uid is None).
- We set request.session.uid ONLY after super()._pre_dispatch() so base check_session()
  is never run with our Bearer session (no session_token → would reset env).
- Do NOT set request.uid in Odoo 19: the setter raises NotImplementedError and causes 500.
"""
import json
import logging
import os
import time
import traceback

from odoo import models
from odoo.http import request

_logger = logging.getLogger(__name__)

# #region agent log
_DEBUG_LOG_PATH = "/opt/odoo/custom_addons/.cursor/debug.log"
_DEBUG_LOG_FALLBACK = "/tmp/odoo_debug_cursor.log"
def _ir_http_debug_log(location, message, data=None, hypothesis_id=None):
    payload = json.dumps({"location": location, "message": message, "data": data or {}, "hypothesisId": hypothesis_id, "timestamp": int(time.time() * 1000), "sessionId": "debug-session", "runId": "run1"}) + "\n"
    for path in (_DEBUG_LOG_PATH, _DEBUG_LOG_FALLBACK):
        try:
            with open(path, "a") as f:
                f.write(payload)
            break
        except Exception:
            continue
# #endregion

DEBUG_MOBILE_AUTH = os.environ.get("DEBUG_MOBILE_AUTH") == "1"


def _mask_token(token, visible=8):
    """First `visible` chars + '***'; safe for logging."""
    if not token or not isinstance(token, str):
        return "*" * 8
    t = (token or "").strip()
    if len(t) <= visible:
        return "*" * 8
    return t[:visible] + "***"


def _safe_get_path():
    try:
        return (request and request.httprequest and request.httprequest.path) or ""
    except Exception:
        return ""


def _safe_get_auth_header():
    try:
        return (request and request.httprequest and request.httprequest.headers.get("Authorization")) or ""
    except Exception:
        return ""


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _authenticate(cls, endpoint):
        """Set request.env from Bearer token only (no session.uid) so check_session is not triggered."""
        # #region agent log
        path = _safe_get_path()
        _ir_http_debug_log("ir_http._authenticate:entry", "request authenticate", {"path": path}, "H2")
        # #endregion
        try:
            path = _safe_get_path()
            if not path.startswith("/api/v1"):
                super()._authenticate(endpoint)
                return
            auth_header = _safe_get_auth_header()
            if not auth_header.startswith("Bearer "):
                super()._authenticate(endpoint)
                return
            token = auth_header[7:].strip()
            if not token:
                super()._authenticate(endpoint)
                return
            try:
                token_model = request.env["api.access.token"].sudo()
                uid = token_model.get_user_id_by_token(token)
                if uid:
                    request.update_env(user=uid)
            except Exception as e:
                _logger.debug("Bearer token lookup in _authenticate failed: %s", e)
        except Exception as e:
            _logger.debug("Bearer _authenticate guard: %s", e)
        try:
            super()._authenticate(endpoint)
        except Exception as e:
            # #region agent log
            _ir_http_debug_log("ir_http._authenticate:exception", "exception in _authenticate", {"error": str(e), "traceback": traceback.format_exc()}, "H2")
            # #endregion
            raise

    @classmethod
    def _pre_dispatch(cls, rule, args):
        """Resolve Bearer → uid; run base; THEN set session.uid and re-apply env (session.uid only after super)."""
        # #region agent log
        _ir_http_debug_log("ir_http._pre_dispatch:entry", "request pre_dispatch", {"path": _safe_get_path()}, "H2")
        # #endregion
        path = ""
        auth_header = ""
        has_bearer = False
        token_masked = "*" * 8
        resolved_uid = None
        try:
            path = _safe_get_path()
            auth_header = _safe_get_auth_header()
            has_bearer = auth_header.startswith("Bearer ")
            token_masked = _mask_token(auth_header[7:].strip()) if has_bearer else "*" * 8
            if path.startswith("/api/v1") and has_bearer:
                token = auth_header[7:].strip()
                if token:
                    try:
                        token_model = request.env["api.access.token"].sudo()
                        uid = token_model.get_user_id_by_token(token)
                        if uid:
                            resolved_uid = uid
                            request.update_env(user=uid)
                    except Exception as e:
                        _logger.debug("Bearer token lookup in _pre_dispatch failed: %s", e)
        except Exception as e:
            _logger.debug("Bearer _pre_dispatch pre-super guard: %s", e)

        try:
            super()._pre_dispatch(rule, args)
        except Exception as e:
            # #region agent log
            _ir_http_debug_log("ir_http._pre_dispatch:exception", "exception in _pre_dispatch", {"error": str(e), "traceback": traceback.format_exc()}, "H2")
            # #endregion
            raise

        if path.startswith("/api/v1") and resolved_uid is not None:
            try:
                request.session.uid = resolved_uid
                request.update_env(user=resolved_uid)
                user = request.env["res.users"].sudo().browse(resolved_uid)
                if user.exists():
                    request.session.login = user.login
            except Exception as e:
                _logger.debug("Re-apply Bearer uid after _pre_dispatch: %s", e)

        if path.startswith("/api/v1") and DEBUG_MOBILE_AUTH:
            try:
                final_session_uid = getattr(request.session, "uid", None)
                env_user_id = None
                try:
                    if request.env and getattr(request.env, "user", None):
                        env_user_id = request.env.user.id
                except Exception:
                    try:
                        env_user_id = getattr(request.env, "uid", None)
                    except Exception:
                        pass
                _logger.info(
                    "ir_http [DEBUG_MOBILE_AUTH] path=%s auth_present=%s scheme_bearer=%s token_masked=%s "
                    "resolved_uid=%s session_uid=%s env_user_id=%s",
                    path,
                    bool(auth_header),
                    has_bearer,
                    token_masked,
                    resolved_uid,
                    final_session_uid,
                    env_user_id,
                )
            except Exception as e:
                _logger.debug("DEBUG_MOBILE_AUTH log guard: %s", e)
