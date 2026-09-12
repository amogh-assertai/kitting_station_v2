/**
 * History listing page behavior.
 *
 * - Formats each row's created_at (stored UTC ISO) into the viewer's
 *   local timezone using Intl.DateTimeFormat, same convention already
 *   established elsewhere in this app (see live-activities-list.js's
 *   own created_at handling) - never done server-side, so the display
 *   always matches the browser's own timezone rather than a fixed one.
 * - Delete button: inline confirm (simple browser confirm() - History
 *   has no existing confirm-inline-card pattern of its own yet, and a
 *   plain confirm() is proportionate for a single-purpose "delete this
 *   row" action), then AJAX POST to /history/<id>/delete. On success,
 *   removes the row from the table client-side rather than a full page
 *   reload (keeps the current filter/page state intact without an
 *   extra round trip).
 */
document.addEventListener("DOMContentLoaded", () => {
  const page = document.querySelector(".history-page");
  if (!page) return;

  const deleteUrlTemplate = page.dataset.deleteUrlTemplate;

  function formatCreatedAt(isoString) {
    if (!isoString) return "—";
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return "—";

    const parts = new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).formatToParts(date);

    return parts.map((p) => p.value).join("");
  }

  document.querySelectorAll(".history-table__created[data-created-at]").forEach((cell) => {
    cell.textContent = formatCreatedAt(cell.dataset.createdAt);
  });

  page.addEventListener("click", async (event) => {
    const deleteButton = event.target.closest(".history-action-delete");
    if (!deleteButton) return;

    const row = deleteButton.closest("tr[data-activity-id]");
    if (!row) return;

    const activityId = row.dataset.activityId;
    const confirmed = window.confirm("Delete this history record? This cannot be undone.");
    if (!confirmed) return;

    deleteButton.disabled = true;
    deleteButton.textContent = "Deleting...";

    const deleteUrl = deleteUrlTemplate.replace("ACTIVITY_ID", activityId);

    let response;
    try {
      response = await fetch(deleteUrl, { method: "POST" });
    } catch (err) {
      deleteButton.disabled = false;
      deleteButton.textContent = "Delete";
      window.alert("Could not reach the server. Check your connection and try again.");
      return;
    }

    let data;
    try {
      data = await response.json();
    } catch (err) {
      deleteButton.disabled = false;
      deleteButton.textContent = "Delete";
      window.alert("Unexpected server response. Try again.");
      return;
    }

    if (!data.success) {
      deleteButton.disabled = false;
      deleteButton.textContent = "Delete";
      window.alert(data.error || "Could not delete this record.");
      return;
    }

    row.remove();
  });
});
