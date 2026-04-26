"use client";

import { useEffect, useMemo, useState } from "react";
import Flash from "../components/Flash";
import NavBar from "../components/NavBar";
import Tile from "../components/Tile";
import {
  LOGIN_FORM_DEFAULTS,
  SIGNUP_FORM_DEFAULTS,
  STORAGE_KEYS,
} from "../lib/app-constants";
import {
  apiFetch,
  getDisplayChange,
  getStorage,
  setStorage,
} from "../lib/app-utils";

export default function HomePage() {
  const [hydrating, setHydrating] = useState(true);
  const [theme, setTheme] = useState("dark");
  const [appUnlocked, setAppUnlocked] = useState(false);
  const [appMode, setAppMode] = useState("guest");
  const [currentPage, setCurrentPage] = useState("login");
  const [currentUser, setCurrentUser] = useState(null);
  const [watchlist, setWatchlist] = useState([]);
  const [histories, setHistories] = useState({});
  const [recentChanges, setRecentChanges] = useState({});
  const [flashes, setFlashes] = useState({});
  const [toast, setToast] = useState(null);
  const [urlInput, setUrlInput] = useState("");
  const [currentPreview, setCurrentPreview] = useState(null);
  const [checkLoading, setCheckLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [removeTarget, setRemoveTarget] = useState(null);
  const [loginForm, setLoginForm] = useState(LOGIN_FORM_DEFAULTS);
  const [signupForm, setSignupForm] = useState(SIGNUP_FORM_DEFAULTS);

  useEffect(() => {
    const savedTheme = getStorage(STORAGE_KEYS.appTheme, "dark");
    const savedAccess = getStorage(STORAGE_KEYS.appAccess, "0") === "1";
    const savedMode = getStorage(STORAGE_KEYS.appMode, "guest");
    const savedPage = getStorage(STORAGE_KEYS.appPage, "login");
    let savedChanges = {};

    try {
      savedChanges = JSON.parse(getStorage(STORAGE_KEYS.recentChanges, "{}")) || {};
    } catch {}

    setTheme(savedTheme);
    setAppUnlocked(savedAccess);
    setAppMode(savedMode);
    setCurrentPage(savedPage);
    setRecentChanges(savedChanges);
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    setStorage(STORAGE_KEYS.appTheme, theme);
  }, [theme]);

  useEffect(() => setStorage(STORAGE_KEYS.appAccess, appUnlocked ? "1" : "0"), [appUnlocked]);
  useEffect(() => setStorage(STORAGE_KEYS.appMode, appMode), [appMode]);
  useEffect(() => setStorage(STORAGE_KEYS.appPage, currentPage), [currentPage]);
  useEffect(
    () => setStorage(STORAGE_KEYS.recentChanges, JSON.stringify(recentChanges)),
    [recentChanges],
  );

  useEffect(() => {
    let cancelled = false;

    async function hydrateAuth() {
      try {
        const data = await apiFetch("/auth/me");
        if (cancelled) return;

        if (data.user) {
          setCurrentUser(data.user);
          setAppUnlocked(true);
          setAppMode("account");
          setCurrentPage((page) => (page === "login" || page === "signup" ? "check" : page));
        } else if (
          getStorage(STORAGE_KEYS.appAccess, "0") === "1" &&
          getStorage(STORAGE_KEYS.appMode, "guest") === "demo"
        ) {
          setCurrentUser(null);
          setAppUnlocked(true);
          setAppMode("demo");
          setCurrentPage((page) => (page === "login" || page === "signup" ? "check" : page));
        } else {
          setCurrentUser(null);
          setAppUnlocked(false);
          setAppMode("guest");
          setCurrentPage("login");
        }
      } catch {
        setCurrentUser(null);
        setAppUnlocked(false);
        setAppMode("guest");
        setCurrentPage("login");
      }

      if (!cancelled) setHydrating(false);
    }

    hydrateAuth();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!appUnlocked) return;
    syncWatchlist().catch(() => {});
  }, [appUnlocked, currentUser]);

  useEffect(() => {
    if (!toast) return undefined;
    const id = window.setTimeout(() => setToast(null), 5000);
    return () => window.clearTimeout(id);
  }, [toast]);

  useEffect(() => {
    if (appUnlocked && currentPage === "dashboard") {
      loadDashboard().catch((error) => showFlash("dashboard", "err", error.message));
    }
  }, [appUnlocked, currentPage]);

  const dropCount = useMemo(
    () =>
      watchlist
        .map((product) => getDisplayChange(product, recentChanges))
        .filter((change) => change?.direction === "down").length,
    [watchlist, recentChanges],
  );

  const increaseCount = useMemo(
    () =>
      watchlist
        .map((product) => getDisplayChange(product, recentChanges))
        .filter((change) => change?.direction === "up").length,
    [watchlist, recentChanges],
  );

  const previewSaved = currentPreview
    ? watchlist.some((item) => item.product_id === currentPreview.product_id)
    : false;

  const previewSavings =
    currentPreview?.was_price && currentPreview?.price
      ? currentPreview.was_price - currentPreview.price
      : null;

  const previewPct =
    previewSavings && previewSavings > 0
      ? Math.round((previewSavings / currentPreview.was_price) * 100)
      : null;

  function showFlash(page, type, message) {
    setFlashes((current) => ({ ...current, [page]: { type, message } }));
  }

  function clearFlash(page) {
    setFlashes((current) => {
      const next = { ...current };
      delete next[page];
      return next;
    });
  }

  function showToast(icon, title, message, tone = "green") {
    setToast({ icon, title, message, tone });
  }

  function showPage(name) {
    if (!appUnlocked && ["check", "dashboard", "account"].includes(name)) {
      setCurrentPage("login");
      return;
    }

    if (name === "account" && !currentUser) {
      setCurrentPage("dashboard");
      return;
    }

    setCurrentPage(name);
  }

  function resetToGuest() {
    setCurrentUser(null);
    setAppUnlocked(false);
    setAppMode("guest");
    setCurrentPage("signup");
    setWatchlist([]);
    setHistories({});
  }

  async function syncWatchlist() {
    const data = await apiFetch("/watchlist");
    setWatchlist(data.products || []);
    return data.products || [];
  }

  async function loadDashboard() {
    const products = await syncWatchlist();
    await Promise.all(
      products.map(async (product) => {
        try {
          const data = await apiFetch(
            `/history?product_id=${encodeURIComponent(product.product_id)}`,
          );
          setHistories((current) => ({
            ...current,
            [product.product_id]: data.history || [],
          }));
        } catch {
          setHistories((current) => ({ ...current, [product.product_id]: [] }));
        }
      }),
    );
  }

  async function submitLogin(event) {
    event.preventDefault();
    clearFlash("login");

    if (!loginForm.identifier.trim() || !loginForm.password.trim()) {
      showFlash("login", "err", "Enter your username/email and password, or use Continue to Demo.");
      return;
    }

    try {
      const data = await apiFetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(loginForm),
      });
      setCurrentUser(data.user);
      setAppUnlocked(true);
      setAppMode("account");
      setCurrentPage("check");
      showToast("✓", "Signed in", `Welcome back, ${data.user.first_name || data.user.username}.`);
    } catch (error) {
      showFlash("login", "err", error.message);
    }
  }

  async function submitSignup(event) {
    event.preventDefault();
    clearFlash("signup");

    if (
      !signupForm.first_name ||
      !signupForm.last_name ||
      !signupForm.username ||
      !signupForm.password ||
      !signupForm.confirm_password
    ) {
      showFlash("signup", "err", "Fill in the required account details to sign up.");
      return;
    }

    try {
      const data = await apiFetch("/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(signupForm),
      });
      setCurrentUser(data.user);
      setAppUnlocked(true);
      setAppMode("account");
      setCurrentPage("check");
      showToast("✓", "Account created", `Welcome, ${data.user.first_name || data.user.username}.`);
    } catch (error) {
      showFlash("signup", "err", error.message);
    }
  }

  async function logout() {
    try {
      await apiFetch("/auth/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
    } catch {}

    resetToGuest();
  }

  function enterDemo() {
    setCurrentUser(null);
    setAppUnlocked(true);
    setAppMode("demo");
    setCurrentPage("check");
    showToast("✓", "Demo mode on", "You are now using the live demo view backed by the shared database.");
  }

  async function doCheck() {
    if (!urlInput.trim()) return;
    setCheckLoading(true);
    clearFlash("check");

    try {
      const data = await apiFetch(`/product?target=${encodeURIComponent(urlInput.trim())}`);
      setCurrentPreview(data);
    } catch (error) {
      showFlash("check", "err", error.message);
    } finally {
      setCheckLoading(false);
    }
  }

  async function saveProduct() {
    if (!currentPreview || !urlInput.trim()) return;

    try {
      await apiFetch(`/save?target=${encodeURIComponent(urlInput.trim())}`);
      await syncWatchlist();
      showToast("✓", "Saved!", `${currentPreview.name || "Product"} added to your watchlist.`);
    } catch (error) {
      showFlash("check", "err", error.message);
    }
  }

  async function refreshAll() {
    setRefreshing(true);
    clearFlash("dashboard");

    try {
      const data = await apiFetch("/refresh-all");
      const nextChanges = {};

      for (const item of data.updated || []) {
        if (item.old_price == null || item.new_price == null || item.old_price === item.new_price) {
          continue;
        }

        nextChanges[item.product_id] = {
          direction: item.new_price < item.old_price ? "down" : "up",
          amount: Math.abs(item.new_price - item.old_price),
          oldPrice: item.old_price,
          newPrice: item.new_price,
        };
      }

      setRecentChanges(nextChanges);
      await loadDashboard();
    } catch (error) {
      showFlash("dashboard", "err", error.message);
    } finally {
      setRefreshing(false);
    }
  }

  async function confirmRemove() {
    if (!removeTarget) return;

    try {
      await apiFetch(`/remove?product_id=${encodeURIComponent(removeTarget)}`);
      setRemoveTarget(null);
      await loadDashboard();
    } catch (error) {
      showFlash("dashboard", "err", error.message);
    }
  }

  if (hydrating) return <main className="loading-shell">Loading PriceWatch...</main>;

  return (
    <main className={`app-shell ${!appUnlocked ? "auth-locked" : ""}`}>
      <NavBar
        appUnlocked={appUnlocked}
        currentPage={currentPage}
        currentUser={currentUser}
        watchlistCount={watchlist.length}
        dropCount={dropCount}
        theme={theme}
        appMode={appMode}
        onShowPage={showPage}
        onToggleTheme={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
        onEnterGuest={resetToGuest}
        onLogout={logout}
      />

      {!appUnlocked ? (
        <>
          <section className={`page auth-page ${currentPage === "login" ? "active" : ""}`}>
            <div className="auth-shell">
              <section className="auth-hero">
                <div>
                  <div className="auth-kicker"><span className="auth-kicker-dot" />Price alerts for real shoppers</div>
                  <h1 className="auth-title">Track the basket before the price moves.</h1>
                  <p className="auth-copy">Sign in to keep your watchlist, refresh history, and future alerts in one place across web and mobile.</p>
                  <div className="auth-points">
                    <div className="auth-point"><strong>Watchlist sync</strong><span>Saved products and recent checks tied to one account.</span></div>
                    <div className="auth-point"><strong>Alert ready</strong><span>Email, push, or SMS preferences can plug in later.</span></div>
                    <div className="auth-point"><strong>Web first</strong><span>The same product flow can later power a mobile app.</span></div>
                  </div>
                </div>
                <div className="auth-note">Server-side sessions stay simple for web now and still leave room for mobile APIs later.</div>
              </section>
              <section className="auth-card">
                <div className="page-eyebrow">Account</div>
                <h2>Welcome back</h2>
                <p>Sign in with your username or email. Keep the flow simple and jump into your watchlist fast.</p>
                <Flash flash={flashes.login} />
                <form className="auth-form" onSubmit={submitLogin}>
                  <div className="field-block">
                    <label className="field-label" htmlFor="login-email">Email or Username</label>
                    <input className="field-input" id="login-email" type="text" value={loginForm.identifier} onChange={(event) => setLoginForm((current) => ({ ...current, identifier: event.target.value }))} placeholder="fadhil or fadhil@example.com" />
                  </div>
                  <div className="field-block">
                    <label className="field-label" htmlFor="login-password">Password</label>
                    <input className="field-input" id="login-password" type="password" value={loginForm.password} onChange={(event) => setLoginForm((current) => ({ ...current, password: event.target.value }))} placeholder="Enter your password" />
                  </div>
                  <div className="auth-meta">
                    <label className="auth-checkbox"><input type="checkbox" /> Keep me signed in</label>
                    <button className="auth-link-btn" type="button" onClick={() => showPage("signup")}>Create one instead</button>
                  </div>
                  <div className="auth-actions">
                    <button className="btn-primary" type="submit">Sign In</button>
                    <button className="btn-secondary" type="button" onClick={enterDemo}>Continue to Demo</button>
                  </div>
                </form>
              </section>
            </div>
          </section>

          <section className={`page auth-page ${currentPage === "signup" ? "active" : ""}`}>
            <div className="auth-shell">
              <section className="auth-hero">
                <div>
                  <div className="auth-kicker"><span className="auth-kicker-dot" />New account setup</div>
                  <h1 className="auth-title">Create your tracker space.</h1>
                  <p className="auth-copy">Email is optional, so username stays the main sign-in option while the backend remains ready for proper user dashboards and alerts.</p>
                  <div className="auth-points">
                    <div className="auth-point"><strong>Saved products</strong><span>Each user gets their own watchlist view.</span></div>
                    <div className="auth-point"><strong>Future alerts</strong><span>Notification preferences can be stored per person.</span></div>
                    <div className="auth-point"><strong>Upgrade path</strong><span>This frontend can later become a packaged app.</span></div>
                  </div>
                </div>
                <div className="auth-note">We're keeping the same visual system here, just rebuilding it in React.</div>
              </section>
              <section className="auth-card">
                <button className="auth-back-btn" type="button" onClick={() => showPage("login")}>
                  ← Back to login
                </button>
                <div className="page-eyebrow">Sign Up</div>
                <h2>Create an account</h2>
                <p>Create a real local account here. Email is optional.</p>
                <Flash flash={flashes.signup} />
                <form className="auth-form" onSubmit={submitSignup}>
                  <div className="field-row">
                    <div className="field-block">
                      <label className="field-label" htmlFor="signup-first">First name</label>
                      <input className="field-input" id="signup-first" type="text" value={signupForm.first_name} onChange={(event) => setSignupForm((current) => ({ ...current, first_name: event.target.value }))} />
                    </div>
                    <div className="field-block">
                      <label className="field-label" htmlFor="signup-last">Last name</label>
                      <input className="field-input" id="signup-last" type="text" value={signupForm.last_name} onChange={(event) => setSignupForm((current) => ({ ...current, last_name: event.target.value }))} />
                    </div>
                  </div>
                  <div className="field-block">
                    <label className="field-label" htmlFor="signup-username">Username</label>
                    <input className="field-input" id="signup-username" type="text" value={signupForm.username} onChange={(event) => setSignupForm((current) => ({ ...current, username: event.target.value }))} />
                  </div>
                  <div className="field-block">
                    <label className="field-label" htmlFor="signup-email">Email Optional</label>
                    <input className="field-input" id="signup-email" type="email" value={signupForm.email} onChange={(event) => setSignupForm((current) => ({ ...current, email: event.target.value }))} />
                  </div>
                  <div className="field-row">
                    <div className="field-block">
                      <label className="field-label" htmlFor="signup-password">Password</label>
                      <input className="field-input" id="signup-password" type="password" value={signupForm.password} onChange={(event) => setSignupForm((current) => ({ ...current, password: event.target.value }))} />
                    </div>
                    <div className="field-block">
                      <label className="field-label" htmlFor="signup-confirm">Confirm password</label>
                      <input className="field-input" id="signup-confirm" type="password" value={signupForm.confirm_password} onChange={(event) => setSignupForm((current) => ({ ...current, confirm_password: event.target.value }))} />
                    </div>
                  </div>
                  <div className="auth-meta">
                    <label className="auth-checkbox"><input type="checkbox" required /> I agree to receive account alerts</label>
                    <button className="auth-link-btn" type="button" onClick={() => showPage("login")}>Already have an account?</button>
                  </div>
                  <div className="auth-actions">
                    <button className="btn-primary" type="submit">Create Account</button>
                    <button className="btn-secondary" type="button" onClick={() => showPage("login")}>Back to Login</button>
                  </div>
                </form>
              </section>
            </div>
          </section>
        </>
      ) : (
        <>
          <section className={`page ${currentPage === "check" ? "active" : ""}`}>
            <div className="page-eyebrow">Groceries</div>
            <h1 className="page-title">Price Check</h1>
            <p className="page-sub">{appMode === "account" ? "Paste a public product URL to preview it and save it to your personal dashboard." : "Paste a public product URL to preview it and save it to your watchlist. Known stores are optimized, and other public product pages now use a best-effort generic scraper."}</p>
            <Flash flash={flashes.check} />
            <div className="check-grid">
              <div>
                <div className="input-card">
                  <div className="input-label">Product URL or ID</div>
                  <div className="url-row">
                    <input className="url-input" type="text" value={urlInput} onChange={(event) => setUrlInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); doCheck(); } }} placeholder="Paste a public product URL" />
                    <button className="btn-primary" type="button" onClick={doCheck} disabled={checkLoading}>{checkLoading ? <span className="spin" /> : "Check"}</button>
                  </div>
                  <div className={`load-bar ${checkLoading ? "on" : ""}`}><div className="load-bar-inner" /></div>
                </div>
                {currentPreview ? (
                  <div className="preview-card">
                    <div className="preview-img">{currentPreview.image_url ? <img src={currentPreview.image_url} alt="" /> : <span className="muted-small">No image</span>}</div>
                    <div className="preview-body">
                      {currentPreview.brand ? <div className="preview-brand">{currentPreview.brand}</div> : null}
                      <div className="preview-name">{currentPreview.name || "Unknown product"}</div>
                      <div className="price-row">
                        <span className="price-big">{currentPreview.price != null ? `$${currentPreview.price.toFixed(2)}` : "-"}</span>
                        {currentPreview.was_price ? <span className="price-was">${currentPreview.was_price.toFixed(2)}</span> : null}
                        {previewPct ? <span className="sale-badge">SAVE {previewPct}%</span> : null}
                      </div>
                      {currentPreview.cup_price ? <div className="cup">{currentPreview.cup_price}</div> : null}
                      <span className={`stock-pill ${currentPreview.in_stock === null ? "unknown" : currentPreview.in_stock ? "in" : "out"}`}>
                        <span className="stock-dot" />
                        {currentPreview.in_stock === null ? "Stock unknown" : currentPreview.in_stock ? "In stock" : "Out of stock"}
                      </span>
                      <div><a className="ext-link" href={currentPreview.canonical_url} target="_blank" rel="noreferrer">Open product ↗</a></div>
                    </div>
                  </div>
                ) : (
                  <div className="empty-box"><p>Enter a URL above to preview</p></div>
                )}
              </div>
              <div>
                {currentPreview ? (
                  <div className="save-panel">
                    <h3>Save to Watchlist</h3>
                    <p>Add this product to your dashboard and compare it on refresh.</p>
                    <button className="btn-save" type="button" onClick={saveProduct} disabled={previewSaved}>{previewSaved ? "Already saved" : "Save to Dashboard"}</button>
                    {previewSaved ? <button className="plain-link go-dash" type="button" onClick={() => showPage("dashboard")}>View in Dashboard →</button> : null}
                  </div>
                ) : null}
              </div>
            </div>
          </section>

          <section className={`page ${currentPage === "dashboard" ? "active" : ""}`}>
            <div className="page-eyebrow">Watching</div>
            <h1 className="page-title">Dashboard</h1>
            <p className="page-sub">{appMode === "account" && currentUser ? `Your personal watchlist for ${currentUser.username}. Hit Refresh All to check for price changes.` : "Demo dashboard using the shared watchlist. Hit Refresh All to check for price changes."}</p>
            <Flash flash={flashes.dashboard} />
            <div className="dash-toolbar">
              <div className="stat-chips">
                <span className="stat-chip"><strong>{watchlist.length}</strong> tracked</span>
                {dropCount ? <span className="stat-chip drop-chip"><strong>{dropCount}</strong> drops ↓</span> : null}
                {increaseCount ? <span className="stat-chip increase-chip"><strong>{increaseCount}</strong> increases ↑</span> : null}
              </div>
              <button className="btn-refresh" type="button" onClick={refreshAll} disabled={refreshing}>{refreshing ? <span className="spin spin-w" /> : "Refresh All"}</button>
            </div>
            <div className="product-grid">
              {!watchlist.length ? (
                <div className="empty-box full-span">
                  <p>No products tracked yet.</p>
                  <button className="btn-primary check-empty-btn" type="button" onClick={() => showPage("check")}>Check a Product</button>
                </div>
              ) : watchlist.map((product) => (
                <Tile key={`${product.product_id}-${product.product_db_id ?? ""}`} product={product} history={histories[product.product_id]} recentChanges={recentChanges} onRemove={setRemoveTarget} />
              ))}
            </div>
          </section>

          {currentUser ? (
            <section className={`page ${currentPage === "account" ? "active" : ""}`}>
              <div className="page-eyebrow">Profile</div>
              <h1 className="page-title">Account</h1>
              <p className="page-sub">Your personal PriceWatch account and separate dashboard space.</p>
              <div className="input-card">
                <div className="input-label">Signed In As</div>
                <div className="account-stack">
                  <div className="tile-meta">{`${currentUser.first_name || ""} ${currentUser.last_name || ""}`.trim() || currentUser.username}</div>
                  <div className="tile-name">@{currentUser.username}</div>
                  <div className="tile-meta">{currentUser.email || "Email not set"}</div>
                  <div className="auth-actions top-gap">
                    <button className="btn-primary" type="button" onClick={() => showPage("dashboard")}>Open My Dashboard</button>
                    <button className="btn-secondary" type="button" onClick={logout}>Log Out</button>
                  </div>
                </div>
              </div>
            </section>
          ) : null}
        </>
      )}

      {removeTarget ? (
        <div className="modal-bg">
          <div className="modal">
            <h3>Remove product?</h3>
            <p>This removes the item from your watchlist.</p>
            <div className="modal-btns">
              <button className="btn-cancel" type="button" onClick={() => setRemoveTarget(null)}>Cancel</button>
              <button className="btn-del" type="button" onClick={confirmRemove}>Remove</button>
            </div>
          </div>
        </div>
      ) : null}

      {toast ? (
        <div className={`toast ${toast.tone}`}>
          <span className="t-icon">{toast.icon}</span>
          <div><div className="t-title">{toast.title}</div><div className="t-msg">{toast.message}</div></div>
          <button className="t-x" type="button" onClick={() => setToast(null)}>×</button>
        </div>
      ) : null}
    </main>
  );
}
