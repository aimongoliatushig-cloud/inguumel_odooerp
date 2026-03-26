# React Native / Expo – client.ts + authStore.ts patches

Apply these in your mobile app. Single auth path: Bearer only; no cookies.

---

## 1. Token: single source of truth (memoryToken)

**Module-level (e.g. in `lib/api/client.ts` or `src/api/client.ts`):**

```ts
// Single source of truth; Axios interceptor reads this synchronously.
// AsyncStorage is ONLY used in hydrate() (e.g. App.tsx or authStore init).
let memoryToken: string | null = null;

export function getMemoryToken(): string | null {
  return memoryToken;
}

export function setMemoryToken(token: string | null): void {
  memoryToken = token;
}
```

**Hydrate on app start (e.g. in authStore or App.tsx):**

```ts
import AsyncStorage from '@react-native-async-storage/async-storage';
import { setMemoryToken } from './api/client';

const ACCESS_TOKEN_KEY = 'access_token'; // or your key

export async function hydrateAuth(): Promise<void> {
  try {
    const token = await AsyncStorage.getItem(ACCESS_TOKEN_KEY);
    setMemoryToken(token);
    // Optionally set authStatus from token presence
  } catch {
    setMemoryToken(null);
  }
}
```

---

## 2. client.ts – Axios instance + Bearer + 401 handling

```ts
import axios, { AxiosError } from 'axios';
import { getMemoryToken } from './token'; // or inline getMemoryToken

const BASE_URL = 'https://your-odoo.com'; // or env

export const apiClient = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
});

// Last 401 timestamp for dedupe (e.g. one alert per 30s)
let lastUnauthorizedAt = 0;
const UNAUTHORIZED_ALERT_THROTTLE_MS = 30000;

export function setOnUnauthorized(handler: () => void): void {
  onUnauthorizedRef.current = handler;
}
const onUnauthorizedRef = { current: (() => {}) as () => void };

apiClient.interceptors.request.use(
  (config) => {
    const token = getMemoryToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (e) => Promise.reject(e)
);

apiClient.interceptors.response.use(
  (res) => res,
  (err: AxiosError) => {
    if (err.response?.status === 401) {
      const now = Date.now();
      if (now - lastUnauthorizedAt > UNAUTHORIZED_ALERT_THROTTLE_MS) {
        lastUnauthorizedAt = now;
        onUnauthorizedRef.current();
      }
      // Optionally: cancel in-flight requests (AbortController or axios CancelToken)
    }
    // Cancelled requests: do not show UI error
    if (axios.isCancel(err) || err.code === 'ERR_CANCELED') {
      return Promise.reject(err); // silent
    }
    return Promise.reject(err);
  }
);
```

---

## 3. authStore.ts – Login sequencing (no race)

After **login success** (e.g. in your login thunk or screen):

```ts
import AsyncStorage from '@react-native-async-storage/async-storage';
import { setMemoryToken } from '../api/client';
import { apiClient } from '../api/client';

const ACCESS_TOKEN_KEY = 'access_token';

export async function setAccessToken(token: string): Promise<void> {
  await AsyncStorage.setItem(ACCESS_TOKEN_KEY, token);
}

export async function clearAccessToken(): Promise<void> {
  await AsyncStorage.removeItem(ACCESS_TOKEN_KEY);
  setMemoryToken(null);
}

// In your login success handler (pseudo-code):
async function onLoginSuccess(data: { access_token: string }) {
  const token = data.access_token;
  if (!token) return;

  // 1) Persist for next app start
  await setAccessToken(token);
  // 2) Single source of truth for this session
  setMemoryToken(token);
  // 3) Auth state
  setAuthStatus('LOGged_IN'); // or your store setter

  // 4) ONLY THEN trigger initial fetches (categories, products, cart)
  await Promise.all([
    fetchCategories(),
    fetchProducts(),
    fetchCart(),
  ]);
}
```

**Guard all auto-fetches:**

```ts
if (authStatus !== 'LOGGED_IN') return;
// then call apiClient.get(...)
```

---

## 4. Orders screen – UX

- If **logged out**: show CTA **«Нэвтрэх»**; do **not** show **«Алдаа гарлаа»** for 401.
- Only show real network/connection errors when appropriate.

```tsx
// Example: Orders screen
if (!isLoggedIn) {
  return (
    <View>
      <Text>Нэвтрэх</Text>
      <Button title="Нэвтрэх" onPress={() => navigation.navigate('Login')} />
    </View>
  );
}
// Do not show "Алдаа гарлаа" for 401; 401 is handled by global logout + redirect to login
```

---

## 5. Checklist

- [ ] **memoryToken** is module-level; AsyncStorage only in **hydrate()** and **setAccessToken**.
- [ ] Axios interceptor reads **getMemoryToken()** only (no AsyncStorage per request).
- [ ] Login: **await setAccessToken(token)** → **setMemoryToken(token)** → **authStatus = LOGged_IN** → then fetch categories/products/cart.
- [ ] All **mxm/*** calls use **apiClient** (same Bearer header).
- [ ] 401: one handler, deduplicated (e.g. 1 alert / 30s); cancel in-flight; no retry loop.
- [ ] Cancelled requests: silent in UI (no error toast).
- [ ] Orders when logged out: show «Нэвтрэх», not «Алдаа гарлаа».
