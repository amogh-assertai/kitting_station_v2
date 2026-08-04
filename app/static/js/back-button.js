/**
 * Global back button (present on every page - see base.html).
 *
 * Uses browser history so it returns to wherever the user actually came
 * from, rather than a fixed "parent page" per template. Falls back to
 * Home only if there's no history to go back to (e.g. page opened
 * directly via a bookmark/typed URL).
 */

(function () {
  document.addEventListener("DOMContentLoaded", function () {
    const button = document.getElementById("back-button");
    if (!button) return;

    button.addEventListener("click", function () {
      if (window.history.length > 1) {
        window.history.back();
      } else {
        window.location.href = button.dataset.fallbackUrl;
      }
    });
  });
})();
