/**
 * Activity Report page behavior.
 *
 * - Durations (Total Kit Time, Active Time, Avg Detection Gap, and the
 *   summary timing table) are computed server-side in SECONDS
 *   (data-seconds="123.4") and formatted here into "Xm Ys" / "Xs" -
 *   kept as a plain number in the data attribute rather than a
 *   pre-formatted string, so this file owns all formatting/rounding
 *   decisions in one place.
 * - Header timestamps (Started/Stopped) use the exact same
 *   getTimezoneLabel()/toLocaleString formatting already established
 *   in live-activities-list.js and history-list.js - kept consistent
 *   across all three pages.
 */

function getTimezoneLabel(date) {
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

  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch (err) {
    return "";
  }
}

function formatTimestamp(isoString) {
  if (!isoString) return "—";
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return "—";

  const dateTimePart = date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });

  const tzPart = getTimezoneLabel(date);
  return tzPart ? `${dateTimePart} ${tzPart}` : dateTimePart;
}

function formatDuration(totalSeconds) {
  if (totalSeconds === null || totalSeconds === undefined || isNaN(totalSeconds)) {
    return "—";
  }

  const seconds = Math.round(totalSeconds);
  if (seconds < 60) return `${seconds}s`;

  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60) return `${minutes}m ${remainingSeconds}s`;

  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h ${remainingMinutes}m`;
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".report-timestamp[data-iso]").forEach((el) => {
    el.textContent = formatTimestamp(el.dataset.iso);
  });

  document.querySelectorAll(".report-duration[data-seconds]").forEach((el) => {
    const raw = el.dataset.seconds;
    // Jinja renders Python's None as the literal string "None" into
    // the attribute - guard for that explicitly, not just empty string.
    const seconds = raw === "" || raw === "None" ? null : parseFloat(raw);
    el.textContent = formatDuration(seconds);
  });

  // Kit circle click -> kit-level detail view.
  document.querySelectorAll(".kit-circle").forEach((circle) => {
    circle.addEventListener("click", () => {
      const detailUrl = circle.dataset.detailUrl;
      if (detailUrl) {
        window.location.href = detailUrl;
      }
    });
  });
});
