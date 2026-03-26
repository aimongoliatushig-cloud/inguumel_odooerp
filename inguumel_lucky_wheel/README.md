# Inguumel Lucky Wheel

Lucky Wheel (Lucky Draw) module for Odoo 19 Community. Accumulates spend from paid orders, grants spins at threshold, weighted RNG for prizes, OTP redemption.

## Upgrade

```bash
odoo-bin -c /etc/odoo19.conf -d <DB_NAME> -i inguumel_lucky_wheel --stop-after-init
# or -u inguumel_lucky_wheel for upgrade
sudo systemctl restart odoo19
```

## API Endpoints

- GET /api/v1/lucky-wheel/eligibility?warehouse_id=X (Bearer) - spin_credits, eligible, accumulated_paid_amount
- POST /api/v1/lucky-wheel/spin (Bearer) - Requires Idempotency-Key header, warehouse_id in body
- POST /api/v1/lucky-wheel/redeem/verify (Bearer) - Staff only. Body: prize_id, otp, redeem_channel

## Curl Tests

```bash
# 1) Login and get token
BASE="http://127.0.0.1:8069"
RES=$(curl -s -X POST "$BASE/api/v1/auth/login" -H "Content-Type: application/json" \
  -d '{"phone":"95909912","pin":"050206"}')
TOKEN=$(echo "$RES" | jq -r '.data.access_token // empty')

# 2) Eligibility
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/lucky-wheel/eligibility?warehouse_id=1" | jq .

# 3) Spin (Idempotency-Key required)
curl -s -X POST "$BASE/api/v1/lucky-wheel/spin" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-$(date +%s)" \
  -d '{"warehouse_id":1}' | jq .

# 4) Redeem (staff only)
curl -s -X POST "$BASE/api/v1/lucky-wheel/redeem/verify" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prize_id":1,"otp":"123456","redeem_channel":"pos"}' | jq .
```

## Configuration

- **lucky.wheel.config** per warehouse: threshold_amount (200k default), default_expire_days, fallback product/coupon, emergency_global_fallback_enabled.
- **lucky.wheel.node** (8 per warehouse): prize_type (product|coupon|empty), weight, is_top_prize.
- Kill switch: `ir.config_parameter` key `api_disabled:/api/v1/lucky-wheel` = true/false.
- Global fallback: `lucky_wheel.global_fallback_product_id`, `lucky_wheel.global_fallback_coupon_payload`.
