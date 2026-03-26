# Status history – verification and curl sample

## Endpoint

- **GET /api/v1/mxm/orders/<id>** returns `status_history` (array sorted asc by `at`).

## Curl

```bash
# 1) Login (get Bearer token)
RES=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"<PHONE>","pin":"<PIN>"}')
TOKEN=$(echo "$RES" | jq -r '.data.access_token // empty')

# 2) Order detail – confirm status_history exists and has at least RECEIVED
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/orders/<ORDER_ID>" | jq '.data.status_history'

# 3) Full response (pretty)
curl -i -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/orders/<ORDER_ID>"
```

## Expected JSON sample (status_history)

**New order (created via mobile checkout):** at least one entry with code `RECEIVED` and correct timestamp.

```json
{
  "success": true,
  "code": "OK",
  "message": "OK",
  "request_id": "...",
  "data": {
    "id": 42,
    "order_number": "S00042",
    "status_history": [
      { "code": "RECEIVED", "label": "Захиалга авлаа", "at": "2026-02-02 08:21:00" },
      { "code": "PREPARING", "label": "Бэлтгэж байна", "at": "2026-02-02 08:22:15" }
    ]
  },
  "meta": null
}
```

**Old order (no logs):** fallback single item from `order.state` (not written to DB).

```json
"status_history": [
  { "code": "RECEIVED", "label": "Захиалга авлаа", "at": "2026-01-15 10:00:00" }
]
```

## Verification steps (full flow A–F)

A) **Mobile-оос order үүсгэ** → RECEIVED лог үүснэ.  
B) **Sale Order confirm хий** → PREPARING лог үүснэ.  
C) **Inventory → Delivery (WH/OUT/xxxx) нээгээд** “Check Availability / Тоо шалгах” → state = assigned → **PACKED лог автоматаар нэмэгдэнэ**.  
D) **Delivery дээр “Хүргэлтэд гаргах” товч дар** → OUT_FOR_DELIVERY лог нэмэгдэнэ.  
E) **Delivery “Validate / Баталгаажуулах”** → state = done → **DELIVERED лог автоматаар нэмэгдэнэ**.  
F) **Curl proof:** `status_history` 4–5 мөртэй болно (RECEIVED, PREPARING, PACKED, OUT_FOR_DELIVERY, DELIVERED).

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/orders/<id>" | jq '.data.status_history'
```

## Short verification

1. Create an order via mobile (cart checkout).
2. Call: `curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/orders/<id>" | jq '.data.status_history'`
3. Confirm at least RECEIVED with valid `at`. After confirm SO → PREPARING. After Check Availability on delivery → PACKED. After “Хүргэлтэд гаргах” → OUT_FOR_DELIVERY. After Validate → DELIVERED.

## ERP 4-step flow (outgoing picking)

1. Create order via mobile → RECEIVED. 2. Open WH/OUT picking. 3. Click in order: Бэлтгэж байна → PREPARING; Бэлтгэж дууссан → PACKED; Хүргэлтэд гаргах → OUT_FOR_DELIVERY; Хүргэгдсэн → Validate → DELIVERED. 4. Curl: `status_history` has 5 entries. List: column "Захиалгын шат" + stage filters.

## Labels (Mongolian)

| code              | label            |
|-------------------|------------------|
| RECEIVED           | Захиалга авлаа   |
| PREPARING          | Бэлтгэж байна    |
| PACKED             | Бэлтгэж дууссан  |
| OUT_FOR_DELIVERY   | Хүргэлтэд гарсан |
| DELIVERED          | Хүргэгдсэн       |
| CANCELLED          | Цуцлагдсан       |
