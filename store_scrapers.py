#!/usr/bin/env python3
"""Route product URLs to the right store scraper."""

from __future__ import annotations

import json
import re
import urllib.parse
from html import unescape
from typing import Any

from woolworths_scraper import (
    ProductSnapshot,
    fetch_html,
    fetch_product_snapshot as fetch_woolworths_product_snapshot,
)


JSON_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>\s*(.*?)\s*</script>',
    re.DOTALL | re.IGNORECASE,
)

SUPPORTED_STORES = {
    "woolworths.com.au": "Woolworths",
    "coles.com.au": "Coles",
    "iga.com.au": "IGA",
    "aldi.com.au": "ALDI",
}


def fetch_product_snapshot(target: str) -> ProductSnapshot:
    target = target.strip()
    if target.isdigit():
        return fetch_woolworths_product_snapshot(target)

    parsed = urllib.parse.urlparse(target)
    host = parsed.netloc.lower()

    if "woolworths.com.au" in host:
        return fetch_woolworths_product_snapshot(target)
    if "coles.com.au" in host:
        return fetch_generic_product_snapshot(target, store_slug="coles")
    if "iga.com.au" in host:
        return fetch_generic_product_snapshot(target, store_slug="iga")
    if "aldi.com.au" in host:
        return fetch_generic_product_snapshot(target, store_slug="aldi")

    supported = ", ".join(SUPPORTED_STORES.values())
    raise ValueError(f"Unsupported retailer URL. Supported stores: {supported}.")


def fetch_generic_product_snapshot(target: str, *, store_slug: str) -> ProductSnapshot:
    html = fetch_html(target)
    parsed = urllib.parse.urlparse(target)
    product = _extract_json_ld_product(html)
    offers = _pick_offer(product.get("offers"))

    price = _coerce_float(_first_non_empty(
        offers.get("price"),
        product.get("price"),
    ))
    availability = _first_non_empty(
        offers.get("availability"),
        product.get("availability"),
    )
    image_url = _normalise_image(product.get("image"))
    raw_product_id = _first_non_empty(
        product.get("sku"),
        product.get("productID"),
        product.get("gtin13"),
        product.get("gtin"),
        _slug_from_path(parsed.path),
    )
    if raw_product_id is None:
        raise ValueError("Could not find a product identifier on the retailer page.")

    return ProductSnapshot(
        product_id=f"{store_slug}:{raw_product_id}",
        name=_first_non_empty(product.get("name")),
        brand=_normalise_brand(product.get("brand")),
        price=price,
        was_price=None,
        cup_price=None,
        in_stock=_coerce_stock_flag(availability),
        availability=availability,
        image_url=image_url,
        canonical_url=target,
    )


def _extract_json_ld_product(html: str) -> dict[str, Any]:
    for raw_json in JSON_LD_RE.findall(html):
        try:
            payload = json.loads(unescape(raw_json))
        except json.JSONDecodeError:
            continue

        product = _find_product_node(payload)
        if product is not None:
            return product

    raise ValueError("Could not find product metadata on the retailer page.")


def _find_product_node(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        node_type = payload.get("@type")
        if _type_matches_product(node_type):
            return payload

        graph = payload.get("@graph")
        if graph is not None:
            found = _find_product_node(graph)
            if found is not None:
                return found

        for value in payload.values():
            found = _find_product_node(value)
            if found is not None:
                return found

    if isinstance(payload, list):
        for item in payload:
            found = _find_product_node(item)
            if found is not None:
                return found

    return None


def _type_matches_product(node_type: Any) -> bool:
    if isinstance(node_type, str):
        return node_type.lower() == "product"
    if isinstance(node_type, list):
        return any(isinstance(item, str) and item.lower() == "product" for item in node_type)
    return False


def _pick_offer(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def _normalise_brand(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str):
            return name
    return None


def _normalise_image(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                return item
    return None


def _slug_from_path(path: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    if not parts:
        return None
    return parts[-1]


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


def _coerce_stock_flag(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if not lowered:
            return None
        if any(token in lowered for token in ("instock", "in stock", "available")):
            return True
        if any(token in lowered for token in ("outofstock", "out of stock", "soldout", "sold out", "unavailable")):
            return False
    return None
