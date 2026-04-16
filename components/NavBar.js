export default function NavBar({
  appUnlocked,
  currentPage,
  currentUser,
  watchlistCount,
  dropCount,
  theme,
  appMode,
  onShowPage,
  onToggleTheme,
  onEnterGuest,
  onLogout,
}) {
  return (
    <nav>
      <div className="nav-brand">
        <span className="nav-dot" />
        PriceWatch
      </div>
      <div className="nav-right">
        <div className="nav-tabs">
          {appUnlocked ? (
            <>
              <button
                className={`nav-tab ${currentPage === "check" ? "active" : ""}`}
                type="button"
                onClick={() => onShowPage("check")}
              >
                Price Check
              </button>
              <button
                className={`nav-tab ${currentPage === "dashboard" ? "active" : ""}`}
                type="button"
                onClick={() => onShowPage("dashboard")}
              >
                Dashboard
                {watchlistCount ? (
                  <span className={`badge ${dropCount ? "drop" : ""}`}>
                    {dropCount || watchlistCount}
                  </span>
                ) : null}
              </button>
              {currentUser ? (
                <button
                  className={`nav-tab ${currentPage === "account" ? "active" : ""}`}
                  type="button"
                  onClick={() => onShowPage("account")}
                >
                  {currentUser.username}
                </button>
              ) : null}
            </>
          ) : null}
        </div>

        <button className="theme-toggle" type="button" onClick={onToggleTheme}>
          {theme === "dark" ? "Light Mode" : "Dark Mode"}
        </button>

        {appMode === "demo" ? <span className="mode-chip demo">Demo</span> : null}
        {appMode === "demo" ? (
          <button className="btn-secondary" type="button" onClick={onEnterGuest}>
            Leave Demo
          </button>
        ) : null}
        {appMode === "account" && currentUser ? (
          <button className="btn-secondary" type="button" onClick={onLogout}>
            Log Out
          </button>
        ) : null}
      </div>
    </nav>
  );
}
