import { API_BASE } from "./app-constants";

export function getStorage(key, fallback) {
  if (typeof window === "undefined") return fallback;
  try {
    const value = window.localStorage.getItem(key);
    return value ?? fallback;
  } catch {
    return fallback;
  }
}

export function setStorage(key, value) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, value);
  } catch {}
}

export function timeAgo(iso) {
  if (!iso) return "Never";
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function fmtDate(iso) {
  const date = new Date(iso);
  return `${date.toLocaleDateString("en-AU", {
    day: "numeric",
    month: "short",
  })} ${date.toLocaleTimeString("en-AU", {
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}

export function getDisplayChange(product, recentChanges) {
  const recent = recentChanges[product.product_id];
  if (recent) return recent;

  if (
    product.previous_price == null ||
    product.current_price == null ||
    product.previous_price === product.current_price
  ) {
    return null;
  }

  return {
    direction: product.current_price < product.previous_price ? "down" : "up",
    amount: Math.abs(product.current_price - product.previous_price),
    oldPrice: product.previous_price,
    newPrice: product.current_price,
  };
}

export async function apiFetch(path, options) {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    cache: "no-store",
    ...options,
  });

  const raw = await response.text();
  let data = null;

  try {
    data = raw ? JSON.parse(raw) : {};
  } catch {
    if (!response.ok) {
      throw new Error(raw || `HTTP ${response.status}`);
    }
    throw new Error("Received an invalid server response.");
  }

  if (!response.ok || data.error) {
    throw new Error(data.error || raw || `HTTP ${response.status}`);
  }
  return data;
}
