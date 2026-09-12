/**
 * History listing page behavior.
 *
 * - Formats each row's created_at (stored UTC ISO) into 12-hour local
 *   time + timezone abbreviation - EXACT same formatting logic as
 *   live-activities-list.js's formatLocalStartTime/getTimezoneLabel
 *   (mirrored verbatim per client's explicit ask to match the activity
 *   card's format), just without the "Started " prefix since this is a
 *   table column, not a card label.
 * - Delete button: inline confirm (simple browser confirm() - History
 *   has no existing confirm-inline-card pattern of its own yet, and a
 *   plain confirm() is proportionate for a single-purpose "delete this
 *   row" action), then AJAX POST to /history/<id>/delete. Deleting also
 *   removes the activity's saved detection images server-side (see
 *   history_data.delete_activity) - nothing extra needed client-side
 *   for that part. On success, removes the row from the table
 *   client-side rather than a full page reload (keeps the current
 *   filter/page state intact without an extra round trip).
 */

function getTimezoneLabel(date) {
  // formatToParts gives structured output instead of a rendered string,
  // so there's nothing to split/slice - avoids the previous bug where
  // parsing an already-formatted string broke on browsers that shape it
  // differently than expected.
  const tryFormat = (timeZoneName) => {
    try {
      const parts = new Intl.DateTimeFormat(undefined, { timeZoneName }).formatToParts(date);
      const part = parts.find((p) => p.type === "timeZoneName");
      return part ? part.value : "";
    } catch (err) {
      return "";
    }
  };

  const generic = tryFormat("shortGeneric");
  if (generic) return generic;

  const short = tryFormat("short");
  if (short) return short;

  // Ultimate fallback: the IANA zone id itself (e.g. "Asia/Kolkata") -
  // always resolvable, never blank, unambiguous regardless of locale.
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch (err) {
    return "";
  }
}

function formatCreatedAtParts(isoString) {
  const date = new Date(isoString);
  if (!isoString || isNaN(date.getTime())) {
    return { datePart: "—", timePart: "" };
  }

  // Date and time are now rendered on separate lines (date above, time
  // below, in the SAME table cell) - client's explicit ask, to stop the
  // combined single-line string from forcing a horizontal scrollbar on
  // the History table. Split into two Intl.DateTimeFormat calls rather
  // than one toLocaleString + string-splitting, since splitting an
  // already-formatted string is exactly the fragile pattern this
  // project's own getTimezoneLabel() comment already warned against
  // (different locales/browsers shape the combined string differently).
  const datePart = date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });

  const timePart = date.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });

  const tzPart = getTimezoneLabel(date);

  return {
    datePart,
    timePart: tzPart ? `${timePart} ${tzPart}` : timePart,
  };
}

document.addEventListener("DOMContentLoaded", () => {
  const page = document.querySelector(".history-page");
  if (!page) return;

  const deleteUrlTemplate = page.dataset.deleteUrlTemplate;

  document.querySelectorAll(".history-table__created[data-created-at]").forEach((cell) => {
    const { datePart, timePart } = formatCreatedAtParts(cell.dataset.createdAt);
    const dateEl = cell.querySelector(".history-table__created-date");
    const timeEl = cell.querySelector(".history-table__created-time");
    if (dateEl) dateEl.textContent = datePart;
    if (timeEl) timeEl.textContent = timePart;
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
