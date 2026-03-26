# Inguumel Order MXM – Upgrade Guide

## Important: Run as `odoo` user, not root

Running `odoo-bin` as `root` causes:
- "Running as user 'root' is a security risk"
- "Peer authentication failed for user odoo" (PostgreSQL)

## Correct upgrade procedure

### 1. Stop Odoo service

```bash
sudo systemctl stop odoo19
```

### 2. Run upgrade as user `odoo`

```bash
sudo -u odoo /opt/odoo/venv/bin/python /opt/odoo/odoo19/odoo-bin \
  -c /etc/odoo19.conf \
  -d InguumelStage \
  -u inguumel_mobile_api,inguumel_order_mxm \
  --stop-after-init
```

**Adjust paths if your installation differs:**
- Python: `/opt/odoo/venv/bin/python` (or `python3`)
- Odoo: `/opt/odoo/odoo19/odoo-bin` (or `odoo-bin` from PATH)
- Config: `/etc/odoo19.conf`
- Database: `InguumelStage` (use your actual DB name)

### 3. Start Odoo service

```bash
sudo systemctl start odoo19
```

## Verify

```bash
curl -s -c /tmp/mxm_cookies.txt -H "Content-Type: application/json" \
  -d '{"phone":"YOUR_PHONE","pin":"YOUR_PIN"}' \
  "http://YOUR_HOST:8069/api/v1/auth/login"

curl -s -b /tmp/mxm_cookies.txt "http://YOUR_HOST:8069/api/v1/auth/me" | jq .
```

## Troubleshooting: Login returns 500 "Internal error"

If POST `/api/v1/auth/login` returns HTTP 500 with `code: "INTERNAL_ERROR"`:

1. Check Odoo logs for the stacktrace at the same timestamp:
   - `journalctl -u odoo19 -n 200 --no-pager`
   - or `tail -n 200 /var/log/odoo/odoo19.log`
2. Look for `auth.login token creation failed` and the exception (e.g. relation `api_access_token` does not exist).
3. Ensure **inguumel_mobile_api** is upgraded so the `api_access_token` table exists. Re-run upgrade with your DB name:
   - `-u inguumel_mobile_api,inguumel_order_mxm` (or add other modules as needed).
