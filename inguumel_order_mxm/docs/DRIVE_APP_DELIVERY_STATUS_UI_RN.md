# Drive App (RN) – Delivery Status UI: Mongolian Labels

**Problem:** Status update buttons show raw codes (e.g. `out_for_delivery`, `cancelled`) instead of Mongolian labels.

**Backend contract:**
- `GET /api/v1/orders/<id>/delivery` returns `current_status: { code, label }` and `timeline[].label` in Mongolian.
- `POST /api/v1/orders/<id>/delivery/status` returns the full delivery payload with `current_status.label` in Mongolian.

**Requirement:** Buttons must display Mongolian only; send `status.code` in the API body unchanged.

---

## 1) Preferred: Use backend labels

When you have the delivery payload (from GET or POST response):

- **Current status text:** use `current_status.label` (or `label_mn` if present).
- **Timeline items:** use `item.label` for display.
- **Next-status buttons:** if the backend ever returns allowed next statuses with labels, use each item’s `label` for the button text and `code` for the request body.

Example (conceptual):

```ts
// Display current status
<Text>{delivery.current_status?.label ?? deliveryStatusLabelMn(delivery.current_status?.code)}</Text>

// Timeline
{delivery.timeline?.map((item) => (
  <Text key={item.at}>{item.label ?? deliveryStatusLabelMn(item.code)}</Text>
))}

// Action button: show label, send code
const nextStatus = { code: 'preparing', label: 'Бэлтгэж байна' };
<TouchableOpacity onPress={() => postStatus(nextStatus.code)}>
  <Text>{nextStatus.label}</Text>
</TouchableOpacity>
```

---

## 2) Fallback: Frontend label map

When the backend does **not** provide labels for “next statuses”, use a local map. Keep it in sync with backend (`delivery.py` `DELIVERY_STATUS_LABELS`).

**Canonical map (copy into your RN app):**

```ts
// deliveryStatusLabels.ts (or .js) – use for UI text only; always send code to API

export const DELIVERY_STATUS_LABEL_MN: Record<string, string> = {
  received: 'Захиалга авлаа',
  preparing: 'Бэлтгэж байна',
  prepared: 'Бэлтгэж дууссан',
  out_for_delivery: 'Хүргэлтэд гарсан',
  delivered: 'Хүргэгдсэн',
  cancelled: 'Цуцлагдсан',
};

export function deliveryStatusLabelMn(code: string | null | undefined): string {
  if (code == null || code === '') return '';
  return DELIVERY_STATUS_LABEL_MN[code] ?? code;
}
```

**Usage:**

- **Button label:** `deliveryStatusLabelMn(nextStatusCode)` so the user never sees raw `code`.
- **API body:** send `{ status: nextStatusCode }` unchanged (e.g. `"preparing"`, `"out_for_delivery"`).

Example for a list of allowed next codes:

```ts
const allowedNextCodes = ['preparing', 'cancelled']; // from your flow logic

allowedNextCodes.map((code) => (
  <TouchableOpacity key={code} onPress={() => postDeliveryStatus(orderId, code)}>
    <Text>{deliveryStatusLabelMn(code)}</Text>
  </TouchableOpacity>
));
```

---

## 3) Acceptance criteria

- [ ] No English or snake_case status text is visible in the UI.
- [ ] All delivery statuses and action buttons are shown in Mongolian.
- [ ] API payload still uses only `status: "<code>"` (e.g. `preparing`, `out_for_delivery`, `cancelled`).

---

## 4) Backend labels reference (for parity)

| code              | label (MN)           |
|-------------------|----------------------|
| received          | Захиалга авлаа       |
| preparing         | Бэлтгэж байна        |
| prepared          | Бэлтгэж дууссан      |
| out_for_delivery  | Хүргэлтэд гарсан     |
| delivered         | Хүргэгдсэн           |
| cancelled         | Цуцлагдсан           |

Use these same strings in your frontend map so UI and API responses match.
