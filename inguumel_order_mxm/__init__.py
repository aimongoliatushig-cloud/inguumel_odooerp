# -*- coding: utf-8 -*-
# #region agent log
import json
import time
for _p in ("/opt/odoo/custom_addons/.cursor/debug.log", "/tmp/odoo_debug_cursor.log"):
    try:
        with open(_p, "a") as _f:
            _f.write(json.dumps({"location": "inguumel_order_mxm.__init__", "message": "module loading", "data": {}, "hypothesisId": "H4", "timestamp": int(time.time() * 1000), "sessionId": "debug-session", "runId": "run1"}) + "\n")
        break
    except Exception:
        continue
# #endregion
from . import models
from . import services
from . import controllers
