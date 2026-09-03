/**
 * Live Kitting Activity - Monitor page behavior.
 *
 * "Total time" (header) and each camera panel's timer both show the
 * activity's running time - elapsed since created_at (stored server-side
 * as a UTC ISO string), computed client-side against the browser's
 * current time so it's correct regardless of which timezone the monitor
 * is viewed from.
 *
 * Per-kit timing (a timer that resets each time a camera's kit index
 * increments) isn't tracked yet - that needs a kit_started_at field
 * wired to real detection events, a later build. Until then, both
 * camera panels intentionally show the same activity-level time (see
 * each element's title attribute in monitor.html) rather than a
 * fabricated per-kit number.
 *
 * Each timer element carries its own data-created-at, so this loops
 * over every [data-activity-timer] element independently rather than
 * assuming one shared value - ready for per-kit timers later without
 * restructuring this loop.
 */

function formatElapsed(totalSeconds) {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = Math.floor(totalSeconds % 60);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
}

document.addEventListener("DOMContentLoaded", () => {
  const timerEls = document.querySelectorAll("[data-activity-timer]");
  if (timerEls.length === 0) return;

  const timers = Array.from(timerEls).map((el) => {
    const startTime = new Date(el.dataset.createdAt).getTime();
    return { el, startTime };
  });

  const invalid = timers.filter((t) => isNaN(t.startTime));
  invalid.forEach((t) => {
    console.warn(
      "Activity timer: missing or invalid created_at, cannot compute elapsed time.",
      { createdAt: t.el.dataset.createdAt }
    );
    t.el.textContent = "--:--:--";
  });

  const valid = timers.filter((t) => !isNaN(t.startTime));
  if (valid.length === 0) return;

  function tick() {
    valid.forEach(({ el, startTime }) => {
      const elapsedSeconds = (Date.now() - startTime) / 1000;
      el.textContent = formatElapsed(Math.max(elapsedSeconds, 0));
    });
  }

  tick();
  setInterval(tick, 1000);
});
