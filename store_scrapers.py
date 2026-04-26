#!/usr/bin/env python3
"""Generic and store-specific product scraping pipeline."""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass, field
from html import unescape
from typing import Any

from bs4 import BeautifulSoup

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover - optional dependency at runtime
    PlaywrightTimeoutError = None
    sync_playwright = None

from woolworths_scraper import USER_AGENT, ProductSnapshot, fetch_html
from woolworths_scraper import fetch_product_snapshot as fetch_woolworths_product_snapshot


JSON_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>\s*(.*?)\s*</script>',
    re.DOTALL | re.IGNORECASE,
)
SCRIPT_JSON_RE = re.compile(
    r'<script[^>]*type=["\']application/json["\'][^>]*>\s*(.*?)\s*</script>',
    re.DOTALL | re.IGNORECASE,
)
TITLE_RE = re.compile(r"<title[^>]*>\s*(.*?)\s*</title>", re.DOTALL | re.IGNORECASE)
META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
ATTRIBUTE_RE = re.compile(
    r'([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(["\'])(.*?)\2',
    re.DOTALL,
)

ASSIGNED_JSON_MARKERS = (
    "window.__INITIAL_STATE__",
    "window.__PRELOADED_STATE__",
    "window.__NUXT__",
    "window.__APOLLO_STATE__",
    "__INITIAL_STATE__",
    "__PRELOADED_STATE__",
    "__NUXT__",
    "__APOLLO_STATE__",
)

NAME_KEYS = (
    "name",
    "Name",
    "title",
    "Title",
    "productName",
    "ProductName",
    "displayName",
    "DisplayName",
)
PRICE_KEYS = (
    "price",
    "Price",
    "currentPrice",
    "CurrentPrice",
    "salePrice",
    "SalePrice",
    "amount",
    "Amount",
    "value",
    "Value",
    "minPrice",
    "MinPrice",
    "lowPrice",
    "LowPrice",
)
WAS_PRICE_KEYS = (
    "was_price",
    "wasPrice",
    "WasPrice",
    "originalPrice",
    "OriginalPrice",
    "listPrice",
    "ListPrice",
    "regularPrice",
    "RegularPrice",
    "compareAtPrice",
    "CompareAtPrice",
    "strikePrice",
    "StrikePrice",
    "rrp",
    "Rrp",
)
BRAND_KEYS = (
    "brand",
    "Brand",
    "brandName",
    "BrandName",
    "manufacturer",
    "Manufacturer",
)
IMAGE_KEYS = (
    "image",
    "Image",
    "imageUrl",
    "imageURL",
    "ImageUrl",
    "primaryImage",
    "primaryImageUrl",
    "thumbnailUrl",
    "images",
    "Images",
)
ID_KEYS = (
    "sku",
    "SKU",
    "productID",
    "productId",
    "ProductID",
    "ProductId",
    "gtin13",
    "gtin",
    "GTIN",
    "id",
    "Id",
    "itemId",
    "ItemId",
    "productCode",
    "ProductCode",
)
AVAILABILITY_KEYS = (
    "availability",
    "Availability",
    "stockLevelStatus",
    "StockLevelStatus",
    "stockStatus",
    "StockStatus",
    "inStock",
    "InStock",
    "isInStock",
    "IsInStock",
    "available",
    "Available",
    "isAvailable",
    "IsAvailable",
)
OFFER_KEYS = (
    "offers",
    "Offers",
    "offer",
    "Offer",
    "priceSpecification",
    "PriceSpecification",
    "priceInfo",
    "PriceInfo",
    "pricing",
    "Pricing",
)
URL_KEYS = (
    "url",
    "Url",
    "canonicalUrl",
    "canonicalURL",
    "productUrl",
    "ProductUrl",
    "link",
    "Link",
)
VARIANT_KEYS = (
    "variant",
    "Variant",
    "size",
    "Size",
    "packSize",
    "PackSize",
    "displaySize",
    "DisplaySize",
)
CURRENCY_KEYS = (
    "priceCurrency",
    "PriceCurrency",
    "currency",
    "Currency",
)
SELLER_KEYS = (
    "seller",
    "Seller",
    "merchant",
    "Merchant",
    "store",
    "Store",
)

NAME_MARKERS = (
    "product-name",
    "product_name",
    "producttitle",
    "product-title",
    "title",
    "name",
    "heading",
)
PRICE_MARKERS = ("price", "sale", "current", "now", "regular", "amount", "cost")
WAS_PRICE_MARKERS = ("was", "strike", "original", "compare", "list", "rrp", "old", "before")
UNIT_PRICE_MARKERS = ("comparison", "unit", "measure", "per-", "per_")
BRAND_MARKERS = ("brand", "manufacturer")
AVAILABILITY_MARKERS = ("stock", "availability", "sold", "inventory")
GENERIC_PAGE_NAMES = {
    "products",
    "product",
    "shop",
    "catalogue",
    "catalog",
    "search",
    "all products",
}
PRICE_TEXT_RE = re.compile(
    r'(?:[$£€]|aud|usd|eur)\s*\d[\d,]*(?:\.\d{1,2})?|\d[\d,]*(?:\.\d{1,2})?\s*(?:aud|usd|eur)',
    re.IGNORECASE,
)

BROWSER_TIMEOUT_MS = 15_000
NETWORK_IDLE_TIMEOUT_MS = 5_000
MAX_NETWORK_PAYLOAD_BYTES = 300_000
MAX_NETWORK_PAYLOADS = 40


@dataclass(frozen=True)
class SiteProfile:
    store_slug: str
    seller: str | None = None
    prefer_browser: bool = False
    browser_required: bool = False


@dataclass
class BrowserArtifacts:
    final_url: str
    html: str
    json_payloads: list[Any] = field(default_factory=list)


@dataclass
class DocumentContext:
    target_url: str
    parsed: urllib.parse.ParseResult
    final_url: str
    store_slug: str
    seller: str | None
    html: str
    fetch_mode: str
    network_payloads: list[Any] = field(default_factory=list)


@dataclass
class ExtractionAttempt:
    snapshot: ProductSnapshot
    score: int
    confidence: float
    page_type: str
    source: str
    fetch_mode: str


SITE_PROFILES = {
    "woolworths.com.au": SiteProfile(store_slug="woolworths", seller="Woolworths"),
    "coles.com.au": SiteProfile(store_slug="coles", seller="Coles", prefer_browser=True),
    "iga.com.au": SiteProfile(store_slug="iga", seller="IGA", prefer_browser=True),
    "igashop.com.au": SiteProfile(store_slug="iga", seller="IGA", prefer_browser=True),
    "aldi.com.au": SiteProfile(store_slug="aldi", seller="ALDI", prefer_browser=True),
}


def fetch_product_snapshot(target: str) -> ProductSnapshot:
    target = target.strip()
    if target.isdigit():
        return fetch_woolworths_product_snapshot(target)

    parsed = _parse_public_url(target)
    if "woolworths.com.au" in parsed.netloc.lower():
        return fetch_woolworths_product_snapshot(target)

    profile = _resolve_site_profile(parsed.netloc)
    return fetch_generic_product_snapshot(target, site_profile=profile)


def fetch_generic_product_snapshot(
    target: str,
    *,
    store_slug: str | None = None,
    site_profile: SiteProfile | None = None,
) -> ProductSnapshot:
    parsed = _parse_public_url(target)
    profile = site_profile or SiteProfile(
        store_slug=store_slug or _derive_store_slug(parsed.netloc),
        seller=_humanize_store_slug(store_slug or _derive_store_slug(parsed.netloc)),
    )

    html = fetch_html(target)
    static_context = _build_document_context(
        target,
        html,
        store_slug=profile.store_slug,
        seller=profile.seller,
        final_url=target,
        fetch_mode="http",
    )
    static_best = _select_best_attempt(static_context)

    browser_best = None
    if _should_try_browser(static_best, profile):
        browser_artifacts = _fetch_browser_artifacts(target)
        if browser_artifacts is not None:
            browser_context = _build_document_context(
                target,
                browser_artifacts.html,
                store_slug=profile.store_slug,
                seller=profile.seller,
                final_url=browser_artifacts.final_url,
                fetch_mode="browser",
                network_payloads=browser_artifacts.json_payloads,
            )
            browser_best = _select_best_attempt(browser_context)

    best = _choose_better_attempt(static_best, browser_best)
    if best is None:
        raise ValueError(
            "Could not extract a product price from the public page. The site may require stronger browser rendering, login access, or a store-specific scraper."
        )
    return best.snapshot


def build_generic_product_snapshot(
    target: str,
    html: str,
    *,
    store_slug: str | None = None,
    seller: str | None = None,
    final_url: str | None = None,
    fetch_mode: str = "http",
    network_payloads: list[Any] | None = None,
) -> ProductSnapshot:
    parsed = _parse_public_url(target)
    resolved_slug = store_slug or _derive_store_slug(parsed.netloc)
    resolved_seller = seller or _humanize_store_slug(resolved_slug)
    context = _build_document_context(
        target,
        html,
        store_slug=resolved_slug,
        seller=resolved_seller,
        final_url=final_url or target,
        fetch_mode=fetch_mode,
        network_payloads=network_payloads or [],
    )
    best = _select_best_attempt(context)
    if best is None:
        raise ValueError(
            "Could not extract a product price from the public page. The site may require stronger browser rendering, login access, or a store-specific scraper."
        )
    return best.snapshot


def _resolve_site_profile(host: str) -> SiteProfile:
    lowered = host.lower()
    for domain, profile in SITE_PROFILES.items():
        if domain in lowered:
            return profile

    slug = _derive_store_slug(lowered)
    return SiteProfile(store_slug=slug, seller=_humanize_store_slug(slug))


def _build_document_context(
    target: str,
    html: str,
    *,
    store_slug: str,
    seller: str | None,
    final_url: str,
    fetch_mode: str,
    network_payloads: list[Any] | None = None,
) -> DocumentContext:
    return DocumentContext(
        target_url=target,
        parsed=_parse_public_url(target),
        final_url=final_url,
        store_slug=store_slug,
        seller=seller,
        html=html,
        fetch_mode=fetch_mode,
        network_payloads=network_payloads or [],
    )


def _select_best_attempt(context: DocumentContext) -> ExtractionAttempt | None:
    attempts = _collect_attempts(context)
    if not attempts:
        return None
    return max(attempts, key=lambda attempt: attempt.score)


def _collect_attempts(context: DocumentContext) -> list[ExtractionAttempt]:
    attempts: list[ExtractionAttempt] = []
    attempts.extend(_build_product_attempts(_extract_json_ld_products(context.html), context, source="json-ld"))
    attempts.extend(_build_product_attempts(_extract_hydration_products(context.html), context, source="hydration"))
    attempts.extend(_build_product_attempts(_extract_network_products(context.network_payloads), context, source="network-json"))

    meta_attempt = _build_meta_attempt(context)
    if meta_attempt is not None:
        attempts.append(meta_attempt)

    dom_attempt = _build_dom_attempt(context)
    if dom_attempt is not None:
        attempts.append(dom_attempt)

    return attempts


def _build_product_attempts(
    products: list[dict[str, Any]],
    context: DocumentContext,
    *,
    source: str,
) -> list[ExtractionAttempt]:
    attempts: list[ExtractionAttempt] = []
    target_tokens = _meaningful_tokens(context.parsed.path)
    product_like_count = len(products)

    for product in products:
        offer = _pick_offer(_first_mapped_value(product, OFFER_KEYS))
        name = _normalise_string(_first_mapped_value(product, NAME_KEYS))
        brand = _normalise_brand(_first_mapped_value(product, BRAND_KEYS))
        price = _coerce_price_value(
            _first_non_empty(_first_mapped_value(offer, PRICE_KEYS), _first_mapped_value(product, PRICE_KEYS))
        )
        if price is None:
            continue

        was_price = _coerce_price_value(
            _first_non_empty(_first_mapped_value(offer, WAS_PRICE_KEYS), _first_mapped_value(product, WAS_PRICE_KEYS))
        )
        availability = _first_non_empty(
            _first_mapped_value(offer, AVAILABILITY_KEYS),
            _first_mapped_value(product, AVAILABILITY_KEYS),
        )
        image_url = _normalise_url(
            _normalise_image(_first_non_empty(_first_mapped_value(product, IMAGE_KEYS), _first_mapped_value(offer, IMAGE_KEYS))),
            base_url=context.final_url,
        )
        canonical_url = _normalise_url(
            _first_non_empty(_first_mapped_value(product, URL_KEYS), _first_mapped_value(offer, URL_KEYS), context.final_url),
            base_url=context.final_url,
        ) or context.final_url
        raw_product_id = _normalise_identifier(
            _first_non_empty(_first_mapped_value(product, ID_KEYS), _first_mapped_value(offer, ID_KEYS), _slug_from_path(urllib.parse.urlparse(canonical_url).path))
        )
        seller = _normalise_seller(_first_non_empty(_first_mapped_value(offer, SELLER_KEYS), _first_mapped_value(product, SELLER_KEYS), context.seller))
        variant = _normalise_string(_first_mapped_value(product, VARIANT_KEYS))
        currency = _normalise_currency(_first_non_empty(_first_mapped_value(offer, CURRENCY_KEYS), _first_mapped_value(product, CURRENCY_KEYS)))

        url_match = _url_matches_target(canonical_url, context.target_url)
        overlap = _target_overlap(name, raw_product_id, canonical_url, target_tokens)
        page_type = _classify_product_candidate_page_type(product_like_count, url_match=url_match, overlap=overlap)
        if page_type == "listing" and not url_match and overlap < 2:
            continue

        snapshot = ProductSnapshot(
            product_id=_build_snapshot_product_id(context.store_slug, raw_product_id, context.parsed),
            name=name,
            brand=brand,
            price=price,
            was_price=was_price if was_price is not None and was_price > price else None,
            cup_price=None,
            in_stock=_coerce_stock_flag(availability),
            availability=_normalise_string(availability),
            image_url=image_url,
            canonical_url=canonical_url,
            currency=currency,
            seller=seller,
            variant=variant,
            page_type=page_type,
            fetch_mode=context.fetch_mode,
            extraction_source=f"{context.fetch_mode}:{source}",
            extraction_confidence=None,
        )
        score = _score_attempt(snapshot, source=source, fetch_mode=context.fetch_mode, url_match=url_match, overlap=overlap, page_type=page_type)
        confidence = _score_to_confidence(score)
        snapshot.extraction_confidence = confidence
        attempts.append(
            ExtractionAttempt(
                snapshot=snapshot,
                score=score,
                confidence=confidence,
                page_type=page_type,
                source=source,
                fetch_mode=context.fetch_mode,
            )
        )

    return attempts


def _build_meta_attempt(context: DocumentContext) -> ExtractionAttempt | None:
    meta = _extract_meta_map(context.html)
    price = _coerce_price_value(
        _first_non_empty(meta.get("product:price:amount"), meta.get("og:price:amount"), meta.get("price"))
    )
    if price is None:
        return None

    name = _normalise_string(_first_non_empty(meta.get("og:title"), meta.get("twitter:title"), meta.get("title")))
    page_type = _classify_page_from_meta(meta, context.parsed)
    if page_type != "product":
        return None

    snapshot = ProductSnapshot(
        product_id=_build_snapshot_product_id(
            context.store_slug,
            _normalise_identifier(_slug_from_path(context.parsed.path)),
            context.parsed,
        ),
        name=name,
        brand=None,
        price=price,
        was_price=None,
        cup_price=None,
        in_stock=_coerce_stock_flag(_first_non_empty(meta.get("product:availability"), meta.get("og:availability"))),
        availability=_normalise_string(_first_non_empty(meta.get("product:availability"), meta.get("og:availability"))),
        image_url=_normalise_url(_first_non_empty(meta.get("og:image"), meta.get("twitter:image")), base_url=context.final_url),
        canonical_url=_normalise_url(_first_non_empty(meta.get("og:url"), context.final_url), base_url=context.final_url) or context.final_url,
        currency=_normalise_currency(meta.get("product:price:currency")),
        seller=context.seller,
        variant=None,
        page_type=page_type,
        fetch_mode=context.fetch_mode,
        extraction_source=f"{context.fetch_mode}:meta",
        extraction_confidence=None,
    )
    overlap = _target_overlap(snapshot.name, None, snapshot.canonical_url, _meaningful_tokens(context.parsed.path))
    score = _score_attempt(snapshot, source="meta", fetch_mode=context.fetch_mode, url_match=_url_matches_target(snapshot.canonical_url, context.target_url), overlap=overlap, page_type=page_type)
    confidence = _score_to_confidence(score)
    snapshot.extraction_confidence = confidence
    return ExtractionAttempt(snapshot=snapshot, score=score, confidence=confidence, page_type=page_type, source="meta", fetch_mode=context.fetch_mode)


def _build_dom_attempt(context: DocumentContext) -> ExtractionAttempt | None:
    soup = BeautifulSoup(context.html, "html.parser")
    scope = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article") or soup.body
    if scope is None:
        return None

    name, used_h1 = _extract_dom_name(scope)
    if not name or _is_generic_page_name(name):
        return None

    prices = _extract_dom_price_candidates(scope)
    current_prices = [candidate for candidate in prices if candidate[1] == "current"]
    was_prices = [candidate for candidate in prices if candidate[1] == "was"]
    unit_prices = [candidate for candidate in prices if candidate[1] == "unit"]
    if not current_prices:
        return None

    product_card_count = _count_product_cards(scope)
    target_tokens = _meaningful_tokens(context.parsed.path)
    name_overlap = _target_overlap(name, None, None, target_tokens)
    page_type = _classify_dom_page_type(scope, name=name, current_price_count=len(current_prices), product_card_count=product_card_count)
    if page_type != "product" and name_overlap < 2:
        return None

    current_price = current_prices[0][0]
    was_price = next((price for price, _, _, _ in was_prices if price > current_price), None)
    cup_price = unit_prices[0][3] if unit_prices else None
    availability = _extract_dom_availability(scope)
    candidate_url = _extract_dom_url(scope, target=context.final_url)
    url_match = _url_matches_target(candidate_url or "", context.target_url)
    overlap = _target_overlap(name, None, candidate_url, target_tokens)
    if product_card_count > 1 and overlap < 2 and not url_match:
        return None

    snapshot = ProductSnapshot(
        product_id=_build_snapshot_product_id(
            context.store_slug,
            _normalise_identifier(_slug_from_path(context.parsed.path)),
            context.parsed,
        ),
        name=name,
        brand=_extract_dom_brand(scope),
        price=current_price,
        was_price=was_price,
        cup_price=cup_price,
        in_stock=_coerce_stock_flag(availability),
        availability=availability,
        image_url=_extract_dom_image(scope, target=context.final_url),
        canonical_url=candidate_url or context.final_url,
        currency=_extract_dom_currency(scope),
        seller=context.seller,
        variant=_extract_dom_variant(scope),
        page_type=page_type,
        fetch_mode=context.fetch_mode,
        extraction_source=f"{context.fetch_mode}:dom",
        extraction_confidence=None,
    )
    score = 62
    score += 10 if used_h1 else 0
    score += 8 if len(current_prices) == 1 else 0
    score += 10 if url_match else 0
    score += 8 if overlap >= 2 else 4 if overlap == 1 else 0
    score += 4 if snapshot.brand else 0
    score += 4 if snapshot.image_url else 0
    score += 3 if snapshot.availability is not None else 0
    score += 3 if snapshot.was_price is not None else 0
    score += 6 if context.fetch_mode == "browser" else 0
    confidence = _score_to_confidence(score)
    snapshot.extraction_confidence = confidence
    return ExtractionAttempt(snapshot=snapshot, score=score, confidence=confidence, page_type=page_type, source="dom", fetch_mode=context.fetch_mode)


def _should_try_browser(static_best: ExtractionAttempt | None, profile: SiteProfile) -> bool:
    if sync_playwright is None:
        return False
    if profile.browser_required:
        return True
    if static_best is None:
        return True
    if profile.prefer_browser and static_best.confidence < 0.92:
        return True
    if static_best.page_type != "product":
        return True
    return static_best.confidence < 0.78


def _choose_better_attempt(
    static_best: ExtractionAttempt | None,
    browser_best: ExtractionAttempt | None,
) -> ExtractionAttempt | None:
    if browser_best is None:
        return static_best
    if static_best is None:
        return browser_best
    if browser_best.page_type == "product" and static_best.page_type != "product":
        return browser_best
    if browser_best.score >= static_best.score + 5:
        return browser_best
    return static_best


def _fetch_browser_artifacts(target: str) -> BrowserArtifacts | None:
    if sync_playwright is None:
        return None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(user_agent=USER_AGENT, locale="en-AU")
            page = context.new_page()
            json_payloads: list[Any] = []

            def handle_response(response: Any) -> None:
                if len(json_payloads) >= MAX_NETWORK_PAYLOADS:
                    return
                resource_type = getattr(response.request, "resource_type", "")
                if resource_type not in {"xhr", "fetch", "document"}:
                    return
                content_type = response.headers.get("content-type", "").lower()
                if "json" not in content_type and "javascript" not in content_type:
                    return
                try:
                    body = response.text()
                except Exception:
                    return
                if not body or len(body) > MAX_NETWORK_PAYLOAD_BYTES:
                    return
                payload = _try_load_json(body)
                if payload is None:
                    return
                json_payloads.append(payload)

            page.on("response", handle_response)
            page.goto(target, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT_MS)
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
            except Exception:
                pass

            artifacts = BrowserArtifacts(final_url=page.url, html=page.content(), json_payloads=json_payloads)
            context.close()
            browser.close()
            return artifacts
    except Exception:
        return None


def _extract_json_ld_products(html: str) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    for raw_json in JSON_LD_RE.findall(html):
        payload = _try_load_json(unescape(raw_json))
        if payload is None:
            continue
        products.extend(_find_product_nodes(payload))
    return products


def _extract_hydration_products(html: str) -> list[dict[str, Any]]:
    payloads: list[Any] = []
    for raw_json in SCRIPT_JSON_RE.findall(html):
        payload = _try_load_json(unescape(raw_json))
        if payload is not None:
            payloads.append(payload)
    for marker in ASSIGNED_JSON_MARKERS:
        payloads.extend(_extract_assigned_json_payloads(html, marker))

    products: list[dict[str, Any]] = []
    for payload in payloads:
        products.extend(_find_product_nodes(payload))
    return products


def _extract_network_products(network_payloads: list[Any]) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    for payload in network_payloads:
        products.extend(_find_product_nodes(payload))
    return products


def _extract_assigned_json_payloads(html: str, marker: str) -> list[Any]:
    payloads: list[Any] = []
    start_index = 0

    while True:
        marker_index = html.find(marker, start_index)
        if marker_index < 0:
            return payloads

        equals_index = html.find("=", marker_index + len(marker))
        if equals_index < 0:
            return payloads

        extracted = _extract_balanced_json(html[equals_index + 1 :])
        start_index = marker_index + len(marker)
        if extracted is None:
            continue

        payload = _try_load_json(unescape(extracted))
        if payload is not None:
            payloads.append(payload)


def _extract_balanced_json(source: str) -> str | None:
    index = 0
    while index < len(source) and source[index].isspace():
        index += 1

    if index >= len(source) or source[index] not in "[{":
        return None

    opening = source[index]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    string_delimiter = ""

    for cursor in range(index, len(source)):
        char = source[cursor]

        if in_string:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == string_delimiter:
                in_string = False
            continue

        if char in {'"', "'"}:
            in_string = True
            string_delimiter = char
            continue

        if char == opening:
            depth += 1
            continue

        if char == closing:
            depth -= 1
            if depth == 0:
                return source[index : cursor + 1]

    return None


def _find_product_nodes(payload: Any, *, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 12:
        return []

    found: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        if _looks_like_product_node(payload):
            found.append(payload)
        for value in payload.values():
            if isinstance(value, (dict, list)):
                found.extend(_find_product_nodes(value, depth=depth + 1))
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, (dict, list)):
                found.extend(_find_product_nodes(item, depth=depth + 1))

    return found


def _looks_like_product_node(node: dict[str, Any]) -> bool:
    if _type_matches_product(node.get("@type")):
        return True

    name = _normalise_string(_first_mapped_value(node, NAME_KEYS))
    price = _coerce_price_value(
        _first_non_empty(_first_mapped_value(node, PRICE_KEYS), _first_mapped_value(node, OFFER_KEYS))
    )
    has_offer = bool(_pick_offer(_first_mapped_value(node, OFFER_KEYS)))
    image = _normalise_image(_first_mapped_value(node, IMAGE_KEYS))
    raw_id = _normalise_identifier(_first_mapped_value(node, ID_KEYS))
    return bool(name and (price is not None or has_offer or image or raw_id))


def _classify_product_candidate_page_type(count: int, *, url_match: bool, overlap: int) -> str:
    if count <= 1:
        return "product"
    if url_match or overlap >= 2:
        return "product"
    return "listing"


def _classify_page_from_meta(meta: dict[str, str], parsed: urllib.parse.ParseResult) -> str:
    og_type = meta.get("og:type", "").lower()
    if og_type == "product":
        return "product"
    title = _normalise_string(_first_non_empty(meta.get("og:title"), meta.get("title")))
    if title and not _is_generic_page_name(title) and meta.get("product:price:amount"):
        return "product"
    if parsed.query and any(token in parsed.query.lower() for token in ("search", "query", "q=")):
        return "listing"
    return "unknown"


def _classify_dom_page_type(scope: Any, *, name: str, current_price_count: int, product_card_count: int) -> str:
    if _is_generic_page_name(name):
        return "listing"
    if product_card_count > 1 and current_price_count > 1:
        return "listing"
    if current_price_count >= 1:
        return "product"
    return "unknown"


def _score_attempt(
    snapshot: ProductSnapshot,
    *,
    source: str,
    fetch_mode: str,
    url_match: bool,
    overlap: int,
    page_type: str,
) -> int:
    base = {
        "network-json": 86,
        "json-ld": 82,
        "hydration": 74,
        "dom": 64,
        "meta": 48,
    }.get(source, 40)

    score = base
    score += 8 if fetch_mode == "browser" else 0
    score += 10 if page_type == "product" else -12 if page_type == "listing" else 0
    score += 10 if snapshot.name else 0
    score += 10 if snapshot.price is not None else 0
    score += 5 if snapshot.brand else 0
    score += 4 if snapshot.image_url else 0
    score += 4 if snapshot.availability is not None else 0
    score += 4 if snapshot.currency else 0
    score += 3 if snapshot.was_price is not None else 0
    score += 12 if url_match else 0
    score += 10 if overlap >= 2 else 5 if overlap == 1 else 0
    return max(score, 1)


def _score_to_confidence(score: int) -> float:
    return min(0.99, round(score / 100, 2))


def _extract_meta_map(html: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for tag in META_TAG_RE.findall(html):
        attrs = _parse_tag_attributes(tag)
        key = (attrs.get("property") or attrs.get("name") or "").strip().lower()
        content = attrs.get("content")
        if key and content:
            meta.setdefault(key, unescape(content.strip()))

    title = _extract_title(html)
    if title:
        meta.setdefault("title", title)
    return meta


def _parse_tag_attributes(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for name, _, value in ATTRIBUTE_RE.findall(tag):
        attrs[name.strip().lower()] = unescape(value.strip())
    return attrs


def _extract_title(html: str) -> str | None:
    match = TITLE_RE.search(html)
    if not match:
        return None
    return _normalise_string(unescape(match.group(1)))


def _extract_dom_name(scope: Any) -> tuple[str | None, bool]:
    heading = scope.find("h1")
    if heading:
        text = _normalise_string(heading.get_text(" ", strip=True))
        if text and not _is_generic_page_name(text):
            return text, True

    for tag in scope.find_all(True, limit=300):
        marker = _dom_marker_text(tag)
        text = _normalise_string(tag.get_text(" ", strip=True))
        if not text or _looks_like_price_text(text) or len(text) > 140:
            continue
        if any(keyword in marker for keyword in NAME_MARKERS) and ("product" in marker or tag.name in {"h2", "h3"}):
            return text, False

    return None, False


def _extract_dom_price_candidates(scope: Any) -> list[tuple[float, str, int, str]]:
    candidates: list[tuple[float, str, int, str]] = []
    seen: set[tuple[str, str]] = set()
    for tag in scope.find_all(True, limit=500):
        marker = _dom_marker_text(tag)
        text = _normalise_string(tag.get_text(" ", strip=True))
        if not text or len(text) > 80 or not _looks_like_price_text(text):
            continue
        kind = _classify_dom_price(marker, text)
        if kind is None:
            continue
        price = _coerce_float(text)
        if price is None:
            continue
        key = (kind, text)
        if key in seen:
            continue
        seen.add(key)
        score = 10 if kind == "current" else 6 if kind == "was" else 4
        score += 4 if any(keyword in marker for keyword in ("product", "base-price", "price")) else 0
        candidates.append((price, kind, score, text))

    def sort_key(item: tuple[float, str, int, str]) -> tuple[int, float]:
        price, kind, score, _ = item
        kind_rank = {"current": 3, "was": 2, "unit": 1}.get(kind, 0)
        return score + kind_rank, -price

    return sorted(candidates, key=sort_key, reverse=True)


def _classify_dom_price(marker: str, text: str) -> str | None:
    lowered_text = text.lower()
    if any(keyword in marker for keyword in UNIT_PRICE_MARKERS) or " per " in lowered_text:
        return "unit"
    if any(keyword in marker for keyword in WAS_PRICE_MARKERS):
        return "was"
    if any(keyword in marker for keyword in PRICE_MARKERS):
        return "current"
    return None


def _extract_dom_brand(scope: Any) -> str | None:
    for tag in scope.find_all(True, limit=200):
        marker = _dom_marker_text(tag)
        text = _normalise_string(tag.get_text(" ", strip=True))
        if text and len(text) <= 80 and any(keyword in marker for keyword in BRAND_MARKERS):
            return text
    return None


def _extract_dom_variant(scope: Any) -> str | None:
    for tag in scope.find_all(True, limit=200):
        marker = _dom_marker_text(tag)
        text = _normalise_string(tag.get_text(" ", strip=True))
        if not text or len(text) > 80:
            continue
        if any(keyword in marker for keyword in ("variant", "size", "pack")):
            return text
    return None


def _extract_dom_availability(scope: Any) -> str | None:
    for tag in scope.find_all(True, limit=200):
        marker = _dom_marker_text(tag)
        text = _normalise_string(tag.get_text(" ", strip=True))
        if not text or len(text) > 80:
            continue
        if any(keyword in marker for keyword in AVAILABILITY_MARKERS) or _coerce_stock_flag(text) is not None:
            if _coerce_stock_flag(text) is not None:
                return text
    return None


def _extract_dom_image(scope: Any, *, target: str) -> str | None:
    image = scope.find("img")
    if not image:
        return None
    for attr in ("src", "data-src", "srcset"):
        value = image.get(attr)
        if not value:
            continue
        if attr == "srcset":
            value = value.split(",", 1)[0].strip().split(" ", 1)[0]
        return _normalise_url(value, base_url=target)
    return None


def _extract_dom_url(scope: Any, *, target: str) -> str | None:
    link = scope.find("a", href=True)
    if not link:
        return None
    return _normalise_url(link.get("href"), base_url=target)


def _extract_dom_currency(scope: Any) -> str | None:
    text = scope.get_text(" ", strip=True)
    if "$" in text:
        return "AUD"
    if " usd" in text.lower():
        return "USD"
    if " eur" in text.lower() or "€" in text:
        return "EUR"
    if "£" in text:
        return "GBP"
    return None


def _count_product_cards(scope: Any) -> int:
    selectors = [
        "[class*='product-card']",
        "[class*='product-tile']",
        "[data-test*='product']",
        "article",
    ]
    count = 0
    for selector in selectors:
        try:
            count = max(count, len(scope.select(selector)))
        except Exception:
            continue
    return count


def _dom_marker_text(tag: Any) -> str:
    values: list[str] = []
    for attr in ("class", "id", "data-test", "data-testid", "itemprop", "name", "aria-label"):
        value = tag.get(attr)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif isinstance(value, str):
            values.append(value)
    return " ".join(values).lower()


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


def _first_mapped_value(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, "", [], {}):
            return mapping[key]
    return None


def _parse_public_url(target: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(target.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Target must be a public product URL or a numeric Woolworths product ID.")
    return parsed


def _derive_store_slug(host: str) -> str:
    labels = [label for label in host.lower().split(".") if label and label not in {"www", "m", "amp", "shop"}]
    if not labels:
        return "site"
    if len(labels) >= 3 and labels[-2] in {"com", "net", "org", "co"}:
        return labels[-3]
    if len(labels) >= 2:
        return labels[-2]
    return labels[0]


def _humanize_store_slug(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


def _build_snapshot_product_id(store_slug: str, raw_product_id: str | None, parsed: urllib.parse.ParseResult) -> str:
    suffix = raw_product_id or _normalise_identifier(_slug_from_path(parsed.path)) or "product"
    return f"{store_slug}:{suffix}"


def _slug_from_path(path: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    if not parts:
        return None
    return urllib.parse.unquote(parts[-1])


def _normalise_identifier(value: Any) -> str | None:
    text = _normalise_string(value)
    if not text:
        return None
    cleaned = re.sub(r"[^a-zA-Z0-9._:-]+", "-", text).strip("-._:")
    return cleaned or None


def _normalise_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"\s+", " ", unescape(value)).strip()
    return cleaned or None


def _normalise_brand(value: Any) -> str | None:
    if isinstance(value, str):
        return _normalise_string(value)
    if isinstance(value, dict):
        return _normalise_string(_first_non_empty(value.get("name"), value.get("Name"), value.get("brand")))
    if isinstance(value, list):
        for item in value:
            brand = _normalise_brand(item)
            if brand:
                return brand
    return None


def _normalise_seller(value: Any) -> str | None:
    if isinstance(value, str):
        return _normalise_string(value)
    if isinstance(value, dict):
        return _normalise_string(_first_non_empty(value.get("name"), value.get("Name"), value.get("seller")))
    return None


def _normalise_image(value: Any) -> str | None:
    if isinstance(value, str):
        return _normalise_string(value)
    if isinstance(value, dict):
        return _normalise_image(_first_non_empty(value.get("url"), value.get("Url"), value.get("src"), value.get("Src")))
    if isinstance(value, list):
        for item in value:
            image = _normalise_image(item)
            if image:
                return image
    return None


def _normalise_url(value: Any, *, base_url: str) -> str | None:
    text = _normalise_string(value)
    if not text:
        return None
    return urllib.parse.urljoin(base_url, text)


def _normalise_currency(value: Any) -> str | None:
    text = _normalise_string(value)
    if not text:
        return None
    return text.upper()


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _coerce_price_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return _coerce_price_value(_first_non_empty(_first_mapped_value(value, PRICE_KEYS), value.get("lowPrice"), value.get("highPrice")))
    if isinstance(value, list):
        for item in value:
            result = _coerce_price_value(item)
            if result is not None:
                return result
        return None
    return _coerce_float(value)


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        cleaned = re.sub(r"^[^\d-]+", "", cleaned)
        cleaned = cleaned.replace(",", "")
        match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        if not match:
            return None
        try:
            return float(match.group(0))
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
        if any(token in lowered for token in ("instock", "in stock", "available", "purchasable")):
            return True
        if any(token in lowered for token in ("outofstock", "out of stock", "soldout", "sold out", "unavailable")):
            return False
    return None


def _try_load_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except Exception:
        return None


def _meaningful_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", urllib.parse.unquote(value).lower()):
        if len(token) < 4:
            continue
        if not any(char.isalpha() for char in token):
            continue
        tokens.add(token)
    return tokens


def _target_overlap(name: str | None, raw_product_id: str | None, url: str | None, target_tokens: set[str]) -> int:
    values = [name or "", raw_product_id or ""]
    if url:
        values.append(urllib.parse.urlparse(url).path)
    combined = " ".join(values)
    text_tokens = _meaningful_tokens(combined)
    return len(text_tokens & target_tokens)


def _url_matches_target(candidate_url: str, target_url: str) -> bool:
    if not candidate_url:
        return False
    candidate = urllib.parse.urlparse(candidate_url)
    target = urllib.parse.urlparse(target_url)
    if candidate.netloc.lower() != target.netloc.lower():
        return False
    candidate_path = candidate.path.rstrip("/")
    target_path = target.path.rstrip("/")
    return bool(candidate_path and target_path and (candidate_path == target_path or candidate_path.endswith(target_path) or target_path.endswith(candidate_path)))


def _is_generic_page_name(name: str) -> bool:
    return name.strip().lower() in GENERIC_PAGE_NAMES


def _looks_like_price_text(text: str) -> bool:
    return bool(PRICE_TEXT_RE.search(text))
