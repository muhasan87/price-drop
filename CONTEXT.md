# Project Context

## Overview

PriceWatch is a local grocery price-tracking prototype with two runtime pieces:

- A Python backend in `server.py` that handles scraping, authentication, PostgreSQL persistence, and JSON APIs.
- A Next.js frontend in `app/` that provides the interactive UI and talks to the backend through `/api` rewrites.

The main user journey is:

1. Paste a product URL.
2. Preview the current product snapshot.
3. Save the product to a watchlist.
4. Refresh the watchlist later to detect drops or increases.
5. Review recent price history for each tracked product.

This repo is structured as a web-first app, but the frontend is intentionally built so it can later be wrapped into a more mobile-like experience.

## Runtime Architecture

### Backend

`server.py` is the main application runtime.

- Loads `.env` values directly from disk at startup.
- Connects to PostgreSQL using `psycopg`.
- Calls `init_db()` on boot to create tables, indexes, compatibility views, and migrate old table names if they exist.
- Starts a standard-library `HTTPServer` on `APP_HOST:APP_PORT`.
- Exposes JSON-only endpoints for auth, product lookup, watchlist operations, and history.

The backend is stateful around server-side sessions, but otherwise behaves like a lightweight REST-style API.

### Frontend

The Next.js app is small and intentionally centralized.

- `app/layout.js` sets metadata and global layout.
- `app/page.js` is the main UI for the entire product. It is a single client component that conditionally renders login, signup, check, dashboard, and account states.
- `next.config.mjs` rewrites `/api/:path*` to the Python backend at `http://127.0.0.1:8080/:path*`.

There is no large multi-page routing model yet. The frontend behaves more like a state-driven single-page app inside a Next.js shell.

### Background Checks

`run_checks.py` is a separate process for scheduled refreshes.

- Imports `server.py` and reuses the same database and scraping logic.
- Supports `--once` for a single pass.
- Supports repeated refreshes via `--interval-seconds`.
- Uses `refresh_all_products(all_scopes=True)` so it refreshes all active watched items across demo and account scopes.

## Core Logic Flows

### 1. App Load and Session Hydration

When the frontend loads, `app/page.js`:

- Restores UI state from `localStorage`.
- Calls `/auth/me` to check whether a cookie-backed user session exists.
- If a real session exists, the app enters account mode.
- If no session exists but local storage says demo mode was active, the app restores demo mode.
- Otherwise it falls back to the locked auth screens.

This means the frontend distinguishes between:

- `guest`: locked, not yet inside the app.
- `demo`: unlocked without a logged-in user.
- `account`: unlocked with a logged-in user.

### 2. Product Preview

The check flow starts in `app/page.js` when the user enters a product URL and calls `/product?target=...`.

Backend flow:

1. `Handler.do_GET()` receives `/product`.
2. `store_scrapers.fetch_product_snapshot()` chooses the correct scraper.
3. A `ProductSnapshot` is returned to the client.
4. The frontend shows product name, brand, price, was-price, stock state, and image.

This preview step does not save anything by itself.

### 3. Save to Watchlist

Saving a product calls `/save?target=...`.

Backend flow:

1. The backend scrapes the product again.
2. `add_product_to_watchlist()` calls `upsert_product_snapshot()`.
3. The product is inserted or updated in `products`.
4. A new `product_price_history` row is written only if the price changed from the latest recorded history row.
5. A `user_watchlists` row is inserted or reactivated.

Important detail: the client preview object is not reused server-side. Save performs a fresh scrape.

### 4. Dashboard Load

The dashboard is built from two API calls:

- `/watchlist` for tracked products.
- `/history?product_id=...` for each product's price history.

The frontend stores watchlist rows in state and keeps a separate `histories` object keyed by `product_id`.

### 5. Refresh All

Refreshing the dashboard calls `/refresh-all`.

Backend flow:

1. `refresh_all_products()` loads active products for the current scope.
2. Each product is scraped again.
3. The latest product row is updated.
4. Any price movement is returned in the response as `updated`, `drops`, and `increases`.

The frontend converts that response into `recentChanges` so the UI can immediately highlight up/down movement without waiting for a full page reload.

### 6. Authentication

Signup and login are handled by `POST /auth/signup` and `POST /auth/login`.

- Passwords are hashed with PBKDF2-HMAC-SHA256.
- Sessions are stored in the `user_sessions` table.
- The browser receives a `pricewatch_session` HTTP-only cookie.
- `GET /auth/me` resolves the current user from that cookie.
- `POST /auth/logout` removes the session and clears the cookie.

This is a classic server-session model, not token-based auth.

## Data Model

The current PostgreSQL schema is centered around five tables:

### `users`

Stores account identity data.

### `user_sessions`

Stores hashed session tokens and expiration timestamps.

### `products`

Stores the latest known snapshot for each unique external product.

Key fields:

- `external_product_id`: stable product key used by the app.
- `product_url`: canonical URL used for future refreshes.
- `current_price`, `original_price`, `was_price`.
- `cup_price`, `in_stock`, `image_url`.
- `last_checked_at`.

The scraper also now produces extra runtime metadata on each `ProductSnapshot` for preview and diagnostics:

- `currency`
- `seller`
- `variant`
- `page_type`
- `fetch_mode`
- `extraction_source`
- `extraction_confidence`

These extra fields are part of the scraper contract returned to the frontend, but they are not fully persisted in the PostgreSQL schema yet.

### `user_watchlists`

Links products into a watchlist scope.

Important behavior:

- `active = FALSE` is used instead of hard deletion.
- uniqueness is scoped by `(COALESCE(user_id, 0), product_id)`.
- this allows the same product to exist once in demo scope and once per real user.

### `product_price_history`

Stores price snapshots over time.

History is append-only, but rows are only added when the latest price actually changes. This keeps the table smaller and makes the history more meaningful.

## Demo Mode vs Account Mode

This distinction is important for understanding the app.

- In account mode, the watchlist is tied to a real `users.id`.
- In demo mode, requests run with `user_id = None` on the backend.
- The backend query layer treats `NULL` user IDs as the shared demo scope.

So demo mode is not fake data in the UI. It is a real shared backend watchlist scope backed by the same database.

## Scraper Layer

`store_scrapers.py` is now the generic scraping pipeline and routing layer for store-specific scraping.

- Woolworths uses a dedicated scraper in `woolworths_scraper.py`.
- Coles, IGA, ALDI, and unknown public product domains go through the generic pipeline with domain profiles and browser escalation rules.

### Woolworths scraper

`woolworths_scraper.py`:

- Accepts either a numeric product ID or a full Woolworths URL.
- Downloads HTML using `urllib.request`.
- Extracts the `__NEXT_DATA__` script payload.
- Builds a normalized `ProductSnapshot` from the embedded product data.
- Falls back to an unverified SSL context if the local Python/macOS certificate chain fails.

### Generic retailer scraper

`store_scrapers.py` for non-Woolworths pages now uses a multi-stage extractor:

- Resolves a site profile from the target host.
- Fetches the initial HTML over standard HTTP.
- Extracts candidates from JSON-LD product schema.
- Extracts candidates from embedded hydration JSON.
- Extracts candidates from browser-captured network JSON payloads when browser fallback runs.
- Falls back to product-oriented meta tags.
- Falls back to page-level DOM extraction for stable server-rendered product pages.
- Classifies candidates as likely product pages or listing pages.
- Scores all candidates and returns the strongest `ProductSnapshot`.

If the static HTTP pass is weak or the site profile prefers browser rendering, the scraper escalates to a Playwright-driven Chromium session and retries extraction on the rendered DOM plus captured network responses.

This means the generic path is no longer limited to static structured metadata. It can now handle:

- static product pages with JSON-LD or meta data
- server-rendered pages with visible DOM pricing
- JavaScript-heavy pages where product data is exposed through browser-rendered HTML or JSON responses

It still does not guarantee support for login-gated, personalized, or heavily bot-protected sites.

## Frontend State Model

The frontend keeps most of its logic inside `app/page.js`.

Main state buckets:

- auth and mode state: `appUnlocked`, `appMode`, `currentUser`, `currentPage`
- product lookup state: `urlInput`, `currentPreview`, `checkLoading`
- dashboard state: `watchlist`, `histories`, `recentChanges`, `refreshing`
- feedback state: `flashes`, `toast`, `removeTarget`
- form state: `loginForm`, `signupForm`
- appearance state: `theme`

Persistent browser state is stored with `localStorage` via `lib/app-utils.js`.

Stored items include:

- theme
- unlocked status
- current app mode
- current page
- recent change highlights

## File Structure Guide

### Backend and jobs

- `server.py`: backend server, schema init, auth, watchlist logic, price refresh logic, HTTP handlers
- `run_checks.py`: scheduled refresh loop
- `store_scrapers.py`: site-profile-aware generic scraping pipeline with static extraction, browser fallback, network JSON extraction, page classification, and scoring
- `woolworths_scraper.py`: Woolworths-specific extraction logic
- `requirements.txt`: Python dependencies including BeautifulSoup and Playwright for browser-assisted scraping

### Frontend app shell

- `app/layout.js`: layout and metadata
- `app/page.js`: main UI and state machine
- `app/manifest.js`: installable web app manifest
- `app/globals.css`: global design system and page styling

### Frontend UI components

- `components/NavBar.js`: top navigation and mode controls
- `components/Tile.js`: dashboard product card with recent history and actions
- `components/Flash.js`: inline feedback banner

### Frontend shared utilities

- `lib/app-constants.js`: API base and local storage keys
- `lib/app-utils.js`: fetch wrapper, local storage helpers, date formatting, price-change helpers

### Tooling

- `next.config.mjs`: backend proxy rewrite
- `package.json`: frontend scripts and dependencies
- `jsconfig.json`: JavaScript import path tooling

## Legacy Compatibility

`init_db()` contains migration and compatibility logic for older table names.

- If `watched_products` exists, it is renamed to `watched_products_legacy`.
- If `price_history` exists, it is renamed to `price_history_legacy`.
- Legacy data is copied into the current normalized schema.
- Compatibility views named `watched_products` and `price_history` are recreated.

This suggests the project evolved from a simpler earlier schema into the current user-aware model.

## Operational Notes

- Backend default: `http://127.0.0.1:8080`
- Frontend default: `http://127.0.0.1:3000`
- Frontend API default: `/api`, proxied by Next.js to the backend
- Database: PostgreSQL

Typical local startup:

```bash
.venv/bin/python server.py
npm run dev
```

Scheduled checks:

```bash
.venv/bin/python run_checks.py --once
.venv/bin/python run_checks.py
```

## Key Constraints and Current Shape

- The frontend is centralized in one large client component rather than split into route-level features.
- Backend endpoints are intentionally simple and JSON-only.
- Demo mode and account mode share most of the same code paths, but they differ by watchlist scope.
- Price history is change-driven, not scrape-driven.
- Retailer support outside Woolworths is broader because the scraper now has browser-rendered fallback and network JSON extraction, but reliability still depends on the site exposing product data to the browser in some recoverable form.
- The backend still uses the standard-library HTTP server, so this is a lightweight prototype rather than a production-hardened web stack.
