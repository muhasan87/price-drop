# PriceCompare

Local prototype for tracking Woolworths product prices from direct product URLs.

## Setup

Create and activate a virtual environment, then install the project dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy the sample environment file and fill in your PostgreSQL details:

```bash
cp .env.example .env
```

## Current flow

1. User pastes a Woolworths product URL into the app
2. The user presses `Check Price`
3. The app previews the product on the current page
4. The preview shows the product name, current price, and whether it is on sale
5. The user presses `Save Product To Dashboard` only if they want to track it
6. The dashboard stores tracked products in a PostgreSQL database
7. Later, the user clicks a refresh button on the dashboard to re-check tracked prices
8. If the latest price is lower than the previous saved price, the dashboard highlights the drop

## Why URL input first

Woolworths currently disallows `/shop/search` in `robots.txt`, so this prototype intentionally starts with direct product URLs instead of keyword search.

## Run the web app

```bash
python3 server.py
```

Open `http://127.0.0.1:8000`.

Use the pages like this:

- `/`: check a single product price and preview it without saving
- `/dashboard`: see tracked products and refresh their prices

## Files

- `server.py`: local web server and PostgreSQL-backed watchlist API
- `woolworths_scraper.py`: reusable Woolworths scraping helpers

## Good next steps

1. Add a real users table and login instead of a single local watchlist
2. Store full price history instead of only previous and current price
3. Add scheduled background checks
4. Send email or push notifications when prices drop
