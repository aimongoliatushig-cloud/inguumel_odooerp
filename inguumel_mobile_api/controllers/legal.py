# -*- coding: utf-8 -*-
"""Public legal pages for App Store / Play Store review and user self-service."""
from werkzeug.wrappers import Response

from odoo import http


BASE_STYLES = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; background: #f8fafc; color: #0f172a; }
.wrap { max-width: 760px; margin: 0 auto; padding: 32px 20px 48px; }
.hero { background: linear-gradient(135deg, #ecfeff, #eff6ff); border: 1px solid #bae6fd; border-radius: 24px; padding: 24px; margin-bottom: 18px; }
.card { background: #fff; border: 1px solid #e2e8f0; border-radius: 20px; padding: 20px; margin-bottom: 16px; }
h1 { margin: 0 0 10px; font-size: 30px; }
h2 { margin: 0 0 10px; font-size: 18px; }
p, li, label, input, button { font-size: 15px; line-height: 1.6; }
ul { margin: 0; padding-left: 18px; }
label { display: block; font-weight: 600; margin-bottom: 6px; }
input { width: 100%; box-sizing: border-box; padding: 12px 14px; border: 1px solid #cbd5e1; border-radius: 12px; margin-bottom: 14px; }
button { border: 0; background: #0f766e; color: #fff; padding: 12px 16px; border-radius: 12px; cursor: pointer; font-weight: 700; }
.danger { background: #dc2626; }
.muted { color: #475569; }
.small { font-size: 13px; color: #64748b; }
.result { margin-top: 14px; padding: 12px 14px; border-radius: 12px; background: #f8fafc; border: 1px solid #e2e8f0; white-space: pre-wrap; }
a { color: #0f766e; }
"""


def _page(title, subtitle, body_html):
    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <style>{BASE_STYLES}</style>
  </head>
  <body>
    <div class="wrap">
      <section class="hero">
        <h1>{title}</h1>
        <p class="muted">{subtitle}</p>
      </section>
      {body_html}
    </div>
  </body>
</html>"""
    return Response(
        html,
        status=200,
        mimetype="text/html",
        headers={"Content-Type": "text/html; charset=utf-8"},
    )


class MobileLegalPages(http.Controller):
    @http.route("/legal/privacy-policy", type="http", auth="public", methods=["GET"], csrf=False)
    def privacy_policy(self, **kwargs):
        body = """
        <section class="card">
          <h2>Data we process</h2>
          <ul>
            <li>Phone number, PIN-based account access, delivery addresses, and order history for shopping and fulfillment.</li>
            <li>Warehouse assignment and delivery status data for the staff app.</li>
            <li>Profile avatar selections are stored on the device unless a future sync feature is explicitly enabled.</li>
          </ul>
        </section>
        <section class="card">
          <h2>Why we use it</h2>
          <ul>
            <li>Authenticate users and staff.</li>
            <li>Show the right catalog, warehouse, orders, and delivery actions.</li>
            <li>Maintain legally required order and accounting records.</li>
          </ul>
        </section>
        <section class="card">
          <h2>Your controls</h2>
          <p>You can request account deletion inside the app or on the account deletion page below.</p>
          <p><a href="/legal/account-deletion">Open the account deletion page</a></p>
        </section>
        """
        return _page(
            "Inguumel Privacy Policy",
            "Policy page intended for mobile store review, public listing, and user reference.",
            body,
        )

    @http.route("/legal/terms", type="http", auth="public", methods=["GET"], csrf=False)
    def terms(self, **kwargs):
        body = """
        <section class="card">
          <h2>Service scope</h2>
          <p>Inguumel enables customers to place warehouse-backed product orders and allows assigned staff to manage delivery and payment workflow.</p>
        </section>
        <section class="card">
          <h2>Account use</h2>
          <p>Users are responsible for keeping their phone number and PIN secure. Staff access is limited to authorized warehouse and cashier roles.</p>
        </section>
        <section class="card">
          <h2>Orders and records</h2>
          <p>Completed orders, payment records, and accounting records may be retained as required by law even after account deletion, but personal profile data is anonymized.</p>
        </section>
        """
        return _page(
            "Inguumel Terms of Service",
            "General customer and staff terms for the mobile applications.",
            body,
        )

    @http.route("/legal/account-deletion", type="http", auth="public", methods=["GET"], csrf=False)
    def account_deletion(self, **kwargs):
        body = """
        <section class="card">
          <h2>Delete your account</h2>
          <p>You can delete your account directly inside the customer app under <strong>Profile → Privacy &amp; Account</strong>.</p>
          <p>This page also provides a web deletion request for users who no longer have the app installed.</p>
        </section>
        <section class="card">
          <h2>Web deletion request</h2>
          <label for="phone">Phone number</label>
          <input id="phone" type="tel" placeholder="99112233" />
          <label for="pin">6-digit PIN</label>
          <input id="pin" type="password" maxlength="6" placeholder="123456" />
          <button class="danger" onclick="submitDelete()">Delete account</button>
          <div id="result" class="result small">No request submitted yet.</div>
        </section>
        <section class="card">
          <h2>What happens after deletion</h2>
          <ul>
            <li>Your customer login is disabled immediately.</li>
            <li>Personal profile data is anonymized.</li>
            <li>Order and accounting records may be retained when legally required.</li>
          </ul>
        </section>
        <script>
          async function submitDelete() {
            const phone = document.getElementById('phone').value.trim();
            const pin = document.getElementById('pin').value.trim();
            const result = document.getElementById('result');
            result.textContent = 'Submitting request...';
            try {
              const res = await fetch('/api/v1/auth/account/delete_request', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone, pin }),
              });
              const body = await res.json();
              result.textContent = JSON.stringify(body, null, 2);
            } catch (err) {
              result.textContent = 'Request failed: ' + String(err);
            }
          }
        </script>
        """
        return _page(
            "Inguumel Account Deletion",
            "Public self-service deletion page for app store compliance and user support.",
            body,
        )
