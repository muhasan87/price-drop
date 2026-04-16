export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "/api";

export const STORAGE_KEYS = {
  recentChanges: "pricewatch_recent_changes",
  appAccess: "pricewatch_app_access",
  appMode: "pricewatch_mode",
  appPage: "pricewatch_current_page",
  appTheme: "pricewatch_theme",
};

export const LOGIN_FORM_DEFAULTS = {
  identifier: "",
  password: "",
};

export const SIGNUP_FORM_DEFAULTS = {
  first_name: "",
  last_name: "",
  username: "",
  email: "",
  password: "",
  confirm_password: "",
};
