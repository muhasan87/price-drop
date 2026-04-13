#!/usr/bin/env python3
"""Helpers for scraping public Woolworths product pages."""

from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from html import unescape
from typing import Any


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">\s*(.*?)\s*</script>',
    re.DOTALL,
)
PRODUCT_ID_RE = re.compile(r"/shop/productdetails/(\d+)")


@dataclass
class ProductSnapshot:
    product_id: str
    name: str | None
    brand: str | None
    price: float | None
    was_price: float | None
    cup_price: str | None
    in_stock: bool | None
    availability: str | None
    image_url: str | None
    canonical_url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalise_target(target: str) -> tuple[str, str]:
    target = target.strip()

    if target.isdigit():
        return target, f"https://www.woolworths.com.au/shop/productdetails/{target}"

    parsed = urllib.parse.urlparse(target)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Target must be a product URL or a numeric product ID.")

    match = PRODUCT_ID_RE.search(parsed.path)
    if not match:
        raise ValueError("Could not find a Woolworths product ID in the URL.")

    product_id = match.group(1)
    return product_id, target


def fetch_product_snapshot(target: str, *, insecure: bool = False) -> ProductSnapshot:
    product_id, url = normalise_target(target)
    html = fetch_html(url, insecure=insecure)
    next_data = extract_next_data(html)
    return build_snapshot(product_id, url, next_data)


def fetch_html(url: str, *, insecure: bool = False) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-AU,en;q=0.9",
        },
    )
    context = None
    if insecure:
        context = ssl._create_unverified_context()

    try:
        with urllib.request.urlopen(request, timeout=20, context=context) as response:
            return response.read().decode("utf-8", errors="replace")
    except ssl.SSLCertVerificationError:
        if insecure:
            raise
        # Local macOS/Python installs sometimes lack the CA chain needed here.
        fallback_context = ssl._create_unverified_context()
        with urllib.request.urlopen(
            request, timeout=20, context=fallback_context
        ) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if insecure or not _is_ssl_cert_verify_error(reason):
            raise
        fallback_context = ssl._create_unverified_context()
        with urllib.request.urlopen(
            request, timeout=20, context=fallback_context
        ) as response:
            return response.read().decode("utf-8", errors="replace")


def extract_next_data(html: str) -> dict[str, Any]:
    match = NEXT_DATA_RE.search(html)
    if not match:
        raise ValueError("Could not find __NEXT_DATA__ in the product page HTML.")
    return json.loads(unescape(match.group(1)))


def build_snapshot(
    product_id: str, source_url: str, payload: dict[str, Any]
) -> ProductSnapshot:
    props = payload.get("props", {})
    page_props = props.get("pageProps", {})
    pd_details = page_props.get("pdDetails") or {}
    product = pd_details.get("Product") or page_props.get("product") or {}
    schema = page_props.get("pdSchema") or {}
    offer = schema.get("offers") or {}

    name = _first_non_empty(
        product.get("Name"),
        product.get("DisplayName"),
        schema.get("name"),
    )
    brand = _first_non_empty(
        product.get("Brand"),
        product.get("BrandName"),
        (schema.get("brand") or {}).get("name"),
    )
    price = _coerce_float(
        _first_non_empty(
            product.get("Price"),
            product.get("InstorePrice"),
            offer.get("price"),
        )
    )
    raw_was_price = _coerce_float(
        _first_non_empty(
            product.get("WasPrice"),
            product.get("InstoreWasPrice"),
            product.get("WasPriceValue"),
            product.get("Was"),
        )
    )
    savings_amount = _coerce_float(
        _first_non_empty(
            product.get("SavingsAmount"),
            product.get("InstoreSavingsAmount"),
        )
    )
    is_on_special = _coerce_bool(
        _first_non_empty(
            product.get("IsOnSpecial"),
            product.get("InstoreIsOnSpecial"),
            product.get("IsHalfPrice"),
            product.get("IsEdrSpecial"),
        )
    )
    was_price = _normalise_was_price(
        current_price=price,
        raw_was_price=raw_was_price,
        savings_amount=savings_amount,
        is_on_special=is_on_special,
    )
    cup_price = _normalise_cup_price(
        cup_price=_first_non_empty(
            product.get("CupString"),
            product.get("CupPriceString"),
            product.get("CupPrice"),
        ),
        has_cup_price=_coerce_bool(
            _first_non_empty(
                product.get("HasCupPrice"),
                product.get("InstoreHasCupPrice"),
            )
        ),
    )
    availability = _first_non_empty(
        offer.get("availability"),
        product.get("StockLevelStatus"),
        product.get("Availability"),
    )
    in_stock = None
    if isinstance(availability, str):
        in_stock = "instock" in availability.lower()

    image_url = _first_non_empty(
        (product.get("DetailsImagePaths") or [None])[0],
        schema.get("image"),
    )
    canonical_url = _first_non_empty(
        source_url,
        schema.get("url"),
        f"https://www.woolworths.com.au/shop/productdetails/{product_id}",
    )

    return ProductSnapshot(
        product_id=product_id,
        name=name,
        brand=brand,
        price=price,
        was_price=was_price,
        cup_price=cup_price,
        in_stock=in_stock,
        availability=availability,
        image_url=image_url,
        canonical_url=canonical_url,
    )


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace("$", "").replace(",", "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def _normalise_was_price(
    *,
    current_price: float | None,
    raw_was_price: float | None,
    savings_amount: float | None,
    is_on_special: bool | None,
) -> float | None:
    if current_price is None:
        return None
    if savings_amount is not None and savings_amount > 0:
        return current_price + savings_amount
    if raw_was_price is not None and raw_was_price > current_price:
        return raw_was_price
    if is_on_special:
        return raw_was_price
    return None


def _normalise_cup_price(cup_price: Any, has_cup_price: bool | None) -> str | None:
    if has_cup_price is False:
        return None
    if cup_price in (None, "", 0, 0.0, "0", "0.0"):
        return None
    if isinstance(cup_price, str):
        return cup_price
    return str(cup_price)


def _is_ssl_cert_verify_error(reason: Any) -> bool:
    if isinstance(reason, ssl.SSLCertVerificationError):
        return True
    if isinstance(reason, ssl.SSLError):
        return "CERTIFICATE_VERIFY_FAILED" in str(reason)
    return "CERTIFICATE_VERIFY_FAILED" in str(reason)
