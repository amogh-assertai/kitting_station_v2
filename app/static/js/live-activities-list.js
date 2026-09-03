/**
 * Live Kitting Activities - landing page behavior.
 *
 * "Complete Manually" opens an inline confirm panel on the card itself
 * (Yes/No + optional reason textarea) rather than a native confirm()
 * dialog - this app runs on kiosk-style HMI screens where native browser
 * dialogs behave inconsistently. On "Yes", POSTs to the per-activity
 * complete-manually endpoint; on success the card is removed from the
 * grid (the activity moved to activity_history and is no longer live).
 *
 * "View Monitor" is currently a stub - the monitor/detail page isn't
 * built yet.
 *
 * Start time is stored server-side as a UTC ISO string (created_at) -
 * formatted here into the browser's local timezone, 12-hour clock, with
 * the timezone abbreviation shown, so an operator sees a time that
 * matches their wall clock rather than raw UTC.
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

function formatLocalStartTime(isoString) {
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return "Started —";

  const timePart = date.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });

  const tzPart = getTimezoneLabel(date);

  return tzPart ? `Started ${timePart} ${tzPart}` : `Started ${timePart}`;
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".activity-card__started[data-created-at]").forEach((el) => {
    el.textContent = formatLocalStartTime(el.dataset.createdAt);
  });

  const grid = document.querySelector(".activities-grid");
  if (!grid) return;

  const urlTemplate = grid.dataset.completeUrlTemplate;

  grid.querySelectorAll(".activity-card").forEach((card) => {
    const activityId = card.dataset.activityId;
    const completeBtn = card.querySelector(".activity-card__complete-btn");
    const confirmPanel = card.querySelector(".activity-card__confirm");
    const confirmNo = card.querySelector(".activity-card__confirm-no");
    const confirmYes = card.querySelector(".activity-card__confirm-yes");
    const reasonInput = card.querySelector(".activity-card__confirm-reason");
    const confirmError = card.querySelector(".activity-card__confirm-error");
    const viewMonitorBtn = card.querySelector(".activity-card__view-monitor");

    viewMonitorBtn.addEventListener("click", () => {
      window.location.href = card.dataset.monitorUrl;
    });

    completeBtn.addEventListener("click", () => {
      confirmPanel.hidden = false;
      completeBtn.hidden = true;
      viewMonitorBtn.hidden = true;
      reasonInput.focus();
    });

    confirmNo.addEventListener("click", () => {
      confirmPanel.hidden = true;
      completeBtn.hidden = false;
      viewMonitorBtn.hidden = false;
      reasonInput.value = "";
      confirmError.hidden = true;
    });

    confirmYes.addEventListener("click", async () => {
      confirmError.hidden = true;
      confirmYes.disabled = true;
      confirmNo.disabled = true;
      confirmYes.textContent = "Completing...";

      const completeUrl = urlTemplate.replace("ACTIVITY_ID", activityId);
      const reason = reasonInput.value.trim();

      let response;
      try {
        response = await fetch(completeUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason }),
        });
      } catch (err) {
        confirmYes.disabled = false;
        confirmNo.disabled = false;
        confirmYes.textContent = "Yes, complete";
        confirmError.textContent = "Could not reach the server. Check your connection and try again.";
        confirmError.hidden = false;
        return;
      }

      let data;
      try {
        data = await response.json();
      } catch (err) {
        confirmYes.disabled = false;
        confirmNo.disabled = false;
        confirmYes.textContent = "Yes, complete";
        confirmError.textContent = "Unexpected server response. Try again.";
        confirmError.hidden = false;
        return;
      }

      if (!data.success) {
        confirmYes.disabled = false;
        confirmNo.disabled = false;
        confirmYes.textContent = "Yes, complete";
        confirmError.textContent = data.error || "Could not complete this activity.";
        confirmError.hidden = false;
        return;
      }

      card.remove();
      if (!grid.querySelector(".activity-card")) {
        const empty = document.createElement("p");
        empty.className = "activities-empty";
        empty.textContent = "No active kitting activities.";
        grid.replaceWith(empty);
      }
    });
  });
});
