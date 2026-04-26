import unittest
from unittest import mock

from store_scrapers import BrowserArtifacts, build_generic_product_snapshot, fetch_generic_product_snapshot


class GenericScraperTests(unittest.TestCase):
    def test_extracts_json_ld_product_from_unknown_domain(self):
        html = """
        <html>
          <head>
            <script type="application/ld+json">
              {
                "@context": "https://schema.org",
                "@type": "Product",
                "name": "Organic Pasta",
                "sku": "pasta-123",
                "brand": {"name": "Farm Co"},
                "image": ["https://example.com/pasta.jpg"],
                "offers": {
                  "@type": "Offer",
                  "price": "4.50",
                  "availability": "InStock",
                  "url": "/products/organic-pasta"
                }
              }
            </script>
          </head>
        </html>
        """

        snapshot = build_generic_product_snapshot(
            "https://shop.example.com/products/organic-pasta",
            html,
        )

        self.assertEqual(snapshot.product_id, "example:pasta-123")
        self.assertEqual(snapshot.name, "Organic Pasta")
        self.assertEqual(snapshot.brand, "Farm Co")
        self.assertEqual(snapshot.price, 4.5)
        self.assertTrue(snapshot.in_stock)
        self.assertEqual(snapshot.image_url, "https://example.com/pasta.jpg")
        self.assertEqual(
            snapshot.canonical_url,
            "https://shop.example.com/products/organic-pasta",
        )
        self.assertEqual(snapshot.page_type, "product")
        self.assertEqual(snapshot.fetch_mode, "http")
        self.assertEqual(snapshot.extraction_source, "http:json-ld")
        self.assertIsNotNone(snapshot.extraction_confidence)

    def test_extracts_embedded_hydration_product(self):
        html = """
        <html>
          <body>
            <script>
              window.__INITIAL_STATE__ = {
                "page": {
                  "product": {
                    "name": "Coffee Beans",
                    "sku": "coffee-1kg",
                    "brand": {"name": "Roaster"},
                    "currentPrice": "18.99",
                    "originalPrice": "21.50",
                    "availability": "In Stock",
                    "image": "https://deals.example.net/coffee.jpg"
                  }
                }
              };
            </script>
          </body>
        </html>
        """

        snapshot = build_generic_product_snapshot(
            "https://deals.example.net/products/coffee-beans",
            html,
        )

        self.assertEqual(snapshot.product_id, "example:coffee-1kg")
        self.assertEqual(snapshot.name, "Coffee Beans")
        self.assertEqual(snapshot.brand, "Roaster")
        self.assertEqual(snapshot.price, 18.99)
        self.assertEqual(snapshot.was_price, 21.5)
        self.assertTrue(snapshot.in_stock)
        self.assertEqual(snapshot.extraction_source, "http:hydration")
        self.assertEqual(snapshot.page_type, "product")

    def test_falls_back_to_meta_tags(self):
        html = """
        <html>
          <head>
            <title>Pantry Olive Oil</title>
            <meta property="og:title" content="Pantry Olive Oil" />
            <meta property="og:image" content="https://store.sample.org/oil.jpg" />
            <meta property="product:price:amount" content="12.40" />
            <meta property="product:availability" content="instock" />
          </head>
        </html>
        """

        snapshot = build_generic_product_snapshot(
            "https://store.sample.org/items/olive-oil",
            html,
        )

        self.assertEqual(snapshot.product_id, "sample:olive-oil")
        self.assertEqual(snapshot.name, "Pantry Olive Oil")
        self.assertEqual(snapshot.price, 12.4)
        self.assertTrue(snapshot.in_stock)
        self.assertEqual(snapshot.image_url, "https://store.sample.org/oil.jpg")
        self.assertEqual(snapshot.extraction_source, "http:meta")

    def test_falls_back_to_dom_for_product_page_markup(self):
        html = """
        <html>
          <body>
            <main class="product-detail-page">
              <h1>Roasted Almond Butter</h1>
              <div class="product-brand">Nut House</div>
              <div class="product-price">
                <span class="current-price">$8.49</span>
                <span class="was-price">$9.99</span>
              </div>
              <div class="stock-status">In stock</div>
              <div class="unit-price">$1.70 per 100 g</div>
              <img src="/images/almond-butter.jpg" alt="Roasted Almond Butter" />
            </main>
          </body>
        </html>
        """

        snapshot = build_generic_product_snapshot(
            "https://grocer.example.com/products/roasted-almond-butter",
            html,
        )

        self.assertEqual(snapshot.product_id, "example:roasted-almond-butter")
        self.assertEqual(snapshot.name, "Roasted Almond Butter")
        self.assertEqual(snapshot.brand, "Nut House")
        self.assertEqual(snapshot.price, 8.49)
        self.assertEqual(snapshot.was_price, 9.99)
        self.assertEqual(snapshot.cup_price, "$1.70 per 100 g")
        self.assertTrue(snapshot.in_stock)
        self.assertEqual(
            snapshot.image_url,
            "https://grocer.example.com/images/almond-butter.jpg",
        )
        self.assertEqual(snapshot.extraction_source, "http:dom")
        self.assertEqual(snapshot.page_type, "product")

    def test_dom_fallback_rejects_generic_listing_page(self):
        html = """
        <html>
          <body>
            <main>
              <h1>Products</h1>
              <article class="product-tile">
                <div class="product-name">Natural Walnuts 500g</div>
                <div class="product-price">$6.99</div>
              </article>
              <article class="product-tile">
                <div class="product-name">Mega Roulette 45g</div>
                <div class="product-price">$0.99</div>
              </article>
            </main>
          </body>
        </html>
        """

        with self.assertRaises(ValueError):
            build_generic_product_snapshot(
                "https://grocer.example.com/products/raw-organic-honey",
                html,
            )

    def test_extracts_product_from_browser_network_payload(self):
        html = """
        <html>
          <body>
            <main><h1>Products</h1></main>
          </body>
        </html>
        """

        snapshot = build_generic_product_snapshot(
            "https://shop.example.com/products/sparkling-water",
            html,
            fetch_mode="browser",
            network_payloads=[
                {
                    "page": {
                        "product": {
                            "name": "Sparkling Water",
                            "sku": "sparkling-water-6pk",
                            "brand": {"name": "Fresh Pop"},
                            "price": "6.75",
                            "priceCurrency": "AUD",
                            "availability": "In Stock",
                            "image": "https://shop.example.com/images/sparkling-water.jpg",
                            "url": "/products/sparkling-water",
                        }
                    }
                }
            ],
        )

        self.assertEqual(snapshot.product_id, "example:sparkling-water-6pk")
        self.assertEqual(snapshot.name, "Sparkling Water")
        self.assertEqual(snapshot.brand, "Fresh Pop")
        self.assertEqual(snapshot.price, 6.75)
        self.assertEqual(snapshot.currency, "AUD")
        self.assertEqual(snapshot.fetch_mode, "browser")
        self.assertEqual(snapshot.extraction_source, "browser:network-json")
        self.assertEqual(snapshot.page_type, "product")

    @mock.patch("store_scrapers._fetch_browser_artifacts")
    @mock.patch("store_scrapers.fetch_html")
    def test_fetch_generic_product_snapshot_uses_browser_fallback(self, mock_fetch_html, mock_fetch_browser_artifacts):
        mock_fetch_html.return_value = """
        <html>
          <body>
            <main>
              <h1>Products</h1>
              <article class=\"product-tile\"><div class=\"product-name\">Item One</div><div class=\"product-price\">$1.00</div></article>
              <article class=\"product-tile\"><div class=\"product-name\">Item Two</div><div class=\"product-price\">$2.00</div></article>
            </main>
          </body>
        </html>
        """
        mock_fetch_browser_artifacts.return_value = BrowserArtifacts(
            final_url="https://shop.example.com/products/browser-coffee",
            html="<html><body><main><h1>Browser Coffee</h1><div class='product-price'><span class='current-price'>$14.40</span></div></main></body></html>",
            json_payloads=[
                {
                    "product": {
                        "name": "Browser Coffee",
                        "sku": "browser-coffee-1kg",
                        "price": "14.40",
                        "brand": {"name": "Roaster House"},
                        "availability": "In Stock",
                        "url": "/products/browser-coffee",
                    }
                }
            ],
        )

        snapshot = fetch_generic_product_snapshot("https://shop.example.com/products/browser-coffee")

        self.assertEqual(snapshot.name, "Browser Coffee")
        self.assertEqual(snapshot.price, 14.4)
        self.assertEqual(snapshot.brand, "Roaster House")
        self.assertEqual(snapshot.fetch_mode, "browser")
        self.assertEqual(snapshot.extraction_source, "browser:network-json")


if __name__ == "__main__":
    unittest.main()