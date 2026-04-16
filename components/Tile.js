import { fmtDate, getDisplayChange, timeAgo } from "../lib/app-utils";

export default function Tile({ product, history, recentChanges, onRemove }) {
  const change = getDisplayChange(product, recentChanges);
  const savings =
    product.original_price != null && product.current_price != null
      ? product.original_price - product.current_price
      : null;
  const percentOff =
    savings && savings > 0 && product.original_price
      ? Math.round((savings / product.original_price) * 100)
      : null;
  const originalLabel = product.original_price != null && savings && savings > 0
    ? `Originally $${product.original_price.toFixed(2)}`
    : "";

  return (
    <div
      className={`tile ${change?.direction === "down" ? "has-drop" : ""} ${
        change?.direction === "up" ? "has-increase" : ""
      }`}
    >
      <div className="tile-img">
        {product.image_url ? (
          <img src={product.image_url} alt="" />
        ) : (
          <span className="muted-small">No image</span>
        )}
      </div>
      <div className="tile-body">
        {product.brand ? <div className="tile-brand">{product.brand}</div> : null}
        <div className="tile-name">{product.name || product.product_id}</div>
        <div className="tile-price-row">
          <span className="tile-price">
            {product.current_price != null ? `$${product.current_price.toFixed(2)}` : "-"}
          </span>
          {change?.direction === "down" ? (
            <span className="tile-change down">↓ ${change.amount.toFixed(2)}</span>
          ) : null}
          {change?.direction === "up" ? (
            <span className="tile-change up">↑ ${change.amount.toFixed(2)}</span>
          ) : null}
        </div>
        {originalLabel || percentOff ? (
          <div className="tile-meta">
            {originalLabel ? <span className="tile-was">{originalLabel}</span> : null}
            {percentOff ? <span className="tile-sale">{percentOff}% off</span> : null}
          </div>
        ) : null}
        {product.cup_price ? <div className="tile-submeta">{product.cup_price}</div> : null}
        <div className="tile-submeta">
          {product.in_stock === null
            ? "Stock unknown"
            : product.in_stock
              ? "In stock"
              : "Out of stock"}
        </div>
      </div>
      <div className="tile-history">
        <div className="history-label">Price History</div>
        <div className="history-list">
          {history === undefined ? (
            <span className="muted-small">Loading...</span>
          ) : history.length ? (
            history
              .slice()
              .reverse()
              .slice(0, 5)
              .map((row, index) => (
                <div
                  className="history-row"
                  key={`${product.product_id}-${index}-${row.recorded_at}`}
                >
                  <span className="history-price">
                    {row.price != null ? `$${row.price.toFixed(2)}` : "-"}
                  </span>
                  <span className="history-date">{fmtDate(row.recorded_at)}</span>
                </div>
              ))
          ) : (
            <span className="muted-small">No history yet</span>
          )}
        </div>
      </div>
      <div className="tile-footer">
        <span className="tile-checked">Checked {timeAgo(product.last_checked_at)}</span>
        <div className="tile-footer-actions">
          <a
            className="ext-link"
            href={product.product_url}
            target="_blank"
            rel="noreferrer"
          >
            View ↗
          </a>
          <button
            className="btn-remove"
            type="button"
            onClick={() => onRemove(product.product_id)}
          >
            Remove
          </button>
        </div>
      </div>
    </div>
  );
}
