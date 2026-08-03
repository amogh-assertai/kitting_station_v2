/**
 * Theme toggle.
 *
 * Server already sets the correct data-theme attribute on <html> on first
 * render (from the cookie), so there is no flash of wrong theme. This
 * script only handles the user clicking the toggle afterwards:
 *   1. Flip the data-theme attribute on <html>.
 *   2. Persist the choice in a cookie so the server picks it up next request.
 */

(function () {
  const STORAGE_COOKIE_NAME = document.documentElement.dataset.themeCookieName;
  const COOKIE_MAX_AGE_DAYS = parseInt(
    document.documentElement.dataset.themeCookieMaxAgeDays || "365",
    10
  );

  function setThemeCookie(theme) {
    const maxAgeSeconds = COOKIE_MAX_AGE_DAYS * 24 * 60 * 60;
    document.cookie = `${STORAGE_COOKIE_NAME}=${theme}; path=/; max-age=${maxAgeSeconds}; SameSite=Lax`;
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  }

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "light"
      ? "light"
      : "dark";
  }

  function toggleTheme() {
    const next = currentTheme() === "dark" ? "light" : "dark";
    applyTheme(next);
    setThemeCookie(next);
    updateToggleLabel(next);
  }

  function updateToggleLabel(theme) {
    const button = document.getElementById("theme-toggle-button");
    if (!button) return;
    button.textContent = theme === "dark" ? "Light mode" : "Dark mode";
    button.setAttribute("aria-pressed", theme === "light");
  }

  document.addEventListener("DOMContentLoaded", function () {
    const button = document.getElementById("theme-toggle-button");
    if (!button) return;
    updateToggleLabel(currentTheme());
    button.addEventListener("click", toggleTheme);
  });
})();
