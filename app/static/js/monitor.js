/**
 * Live Kitting Activity - Monitor page behavior.
 *
 * Concerns in this file:
 *
 * 1. "Total time" header timer (unchanged) - activity-wide elapsed
 *    time, computed client-side against created_at, never resets.
 *
 * 1b. Per-camera "Kit timer" (added this session) - each camera panel
 *     shows how long its CURRENT kit has been in progress, computed
 *     against that kit's actual_kit_start_time (see
 *     cv_ingest/detection_data.py's kit_timings_cam{1,2}). Resets to 0
 *     live, independently per camera, whenever that camera's
 *     "kit:advanced" socket event arrives - client's explicit
 *     requirement: "near cam1 and cam2, show actual kit time, that
 *     timer resets and starts from 0" on validation.
 *
 * 2. Socket.IO live detection sync - every browser tab viewing this
 *    activity's monitor page joins a server-side room keyed by activity
 *    id, and reacts to events pushed from cv_ingest/routes.py:
 *      - "detection:green"  -> expected part detected: shows a full-box
 *        pop-up (image + part/qty/time) inside that camera's panel,
 *        replacing the completed/pending list for the configured
 *        duration, then reverts. Also updates the part's card/qty and
 *        moves it to Completed once its quantity is met.
 *      - "detection:red"    -> unexpected part detected: same full-box
 *        pop-up treatment, styled as a warning. Alert-type
 *        differentiation (Validation Error vs Wrong Part Error) is a
 *        later build - this is only the visual pop-up.
 *      - "kit:advanced"     -> that camera's kit index moved forward;
 *        clear all live counts back to 0/required for that camera only
 *        (cam1/cam2 advance independently), reset its Kit timer to 0,
 *        and if is_completed is true, replace the completed/pending
 *        view with a "Kits Completed" state for that camera only.
 *      - "sound:toggled"    -> a viewer flipped one camera's green-sound
 *        toggle; every viewer's icon updates to match, so the toggle
 *        state stays in sync across all open monitor pages for this
 *        activity.
 *      - "activity:completed" -> BOTH cameras have finished all their
 *        kits; the server has already moved the activity to history.
 *        Freezes "Total time," shows a brief confirmation overlay, then
 *        auto-redirects to the landing page.
 *
 * 3. Detection sound playback - on "detection:green"/"detection:red",
 *    if the server decided a sound should play (see
 *    cv_ingest/detection_data.resolve_sound_for_detection - green
 *    follows this activity's per-camera toggle, red always follows the
 *    table's saved default), the browser plays the given audio_url once.
 *
 * Exactly one part-card carries the "Last detected" badge at a time per
 * camera - handleGreenDetection() clears any stale badge before tagging
 * the newly-detected part's card.
 *
 * All viewers of the same activity_id see the same state, since the
 * server is the single source of truth (Mongo) and every tab reacts to
 * the same broadcast rather than polling.
 */

// ---------------------------------------------------------------------
// 1. Elapsed-time timers - "Total time" (activity-wide, never resets)
// ---------------------------------------------------------------------

function formatElapsed(totalSeconds) {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = Math.floor(totalSeconds % 60);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
}

function initTimers() {
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

  // "Total time" freezes once BOTH cameras complete (client's explicit
  // requirement) - each tick checks the element's own data-completed-at
  // (populated live by freezeActivityTimer() on "activity:completed",
  // see below) rather than a module-level flag, so this same tick loop
  // works whether or not completion ever happens during this page view.
  function tick() {
    valid.forEach(({ el, startTime }) => {
      const completedAtRaw = el.dataset.completedAt;
      const endTime = completedAtRaw ? new Date(completedAtRaw).getTime() : Date.now();
      const elapsedSeconds = (endTime - startTime) / 1000;
      el.textContent = formatElapsed(Math.max(elapsedSeconds, 0));
    });
  }

  tick();
  setInterval(tick, 1000);
}

/**
 * Freezes the "Total time" header timer at completedAtIso - called from
 * handleActivityCompleted() on the "activity:completed" socket event
 * (both cameras just finished). Writing completedAtIso into the
 * element's own data-completed-at means the shared tick() loop in
 * initTimers() picks it up on its very next tick without needing a
 * separate interval or a module-level "is this activity done" flag.
 */
function freezeActivityTimer(completedAtIso) {
  document.querySelectorAll("[data-activity-timer]").forEach((el) => {
    el.dataset.completedAt = completedAtIso;
  });
}

// ---------------------------------------------------------------------
// 1b. Per-camera "Kit timer" - resets live on kit:advanced
// ---------------------------------------------------------------------

/**
 * Unlike the activity-wide "Total time" timer (a fixed set computed
 * once at page load), each Kit timer's start time can change during the
 * page's lifetime (every validate_kit resets it) - so this keeps a
 * mutable registry keyed by element, and a single shared interval reads
 * from it every tick. resetKitTimer() (called from handleKitAdvanced)
 * updates the registry; the interval always reflects the latest value.
 */
const _kitTimerRegistry = new Map(); // element -> startTime (ms epoch)

function initKitTimers() {
  document.querySelectorAll("[data-kit-timer]").forEach((el) => {
    const startTime = new Date(el.dataset.kitStartTime).getTime();
    if (isNaN(startTime)) {
      console.warn(
        "Kit timer: missing or invalid kit start time, cannot compute elapsed time.",
        { kitStartTime: el.dataset.kitStartTime }
      );
      el.textContent = "--:--:--";
      return;
    }
    _kitTimerRegistry.set(el, startTime);
  });

  if (_kitTimerRegistry.size === 0) return;

  function tick() {
    _kitTimerRegistry.forEach((startTime, el) => {
      const elapsedSeconds = (Date.now() - startTime) / 1000;
      el.textContent = formatElapsed(Math.max(elapsedSeconds, 0));
    });
  }

  tick();
  setInterval(tick, 1000);
}

/**
 * Resets one camera's Kit timer to a new start time (called from
 * handleKitAdvanced on "kit:advanced" - client's explicit requirement:
 * the timer should reset to 0 and start counting again the moment that
 * camera's kit is validated). Uses the server-provided kit_start_time
 * from the socket payload rather than Date.now() on the client, so
 * every viewer's timer is anchored to the same authoritative instant
 * regardless of small clock differences between devices.
 */
function resetKitTimer(panel, kitStartTimeIso) {
  const el = panel.querySelector("[data-kit-timer]");
  if (!el) return;
  const startTime = new Date(kitStartTimeIso).getTime();
  if (isNaN(startTime)) return;
  el.dataset.kitStartTime = kitStartTimeIso;
  _kitTimerRegistry.set(el, startTime);
}

// ---------------------------------------------------------------------
// 2. Socket.IO live detection sync
// ---------------------------------------------------------------------

function findCameraPanel(camId) {
  return document.querySelector(`.camera-panel[data-cam-id="${camId}"]`);
}

function findPartCard(panel, partName) {
  return panel.querySelector(`.part-card[data-part-name="${CSS.escape(partName)}"]`);
}

function updateSectionCounts(panel) {
  const completedCount = panel.querySelectorAll('[data-completed-cards] .part-card').length;
  const pendingCount = panel.querySelectorAll('[data-pending-cards] .part-card').length;
  const completedLabel = panel.querySelector('[data-completed-count]');
  const pendingLabel = panel.querySelector('[data-pending-count]');
  if (completedLabel) completedLabel.textContent = completedCount;
  if (pendingLabel) pendingLabel.textContent = pendingCount;
}

/**
 * Handles a "detection:green" event: an expected part was detected.
 * - Updates (or moves) the part's card with the new running count.
 * - Moves the card into the Completed section once count >= required.
 * - Clears any stale "Last detected" badge from every OTHER card on
 *   this panel before tagging the current one - fixes the earlier bug
 *   where the badge accumulated on multiple cards instead of following
 *   only the most recent detection.
 * - Shows the full-box pop-up (image + part/qty/time) for this camera
 *   only, replacing the completed/pending list for the configured
 *   duration.
 */
function handleGreenDetection(payload) {
  const panel = findCameraPanel(payload.cam_id);
  if (!panel) return;

  clearLastDetectedBadges(panel);

  const card = findPartCard(panel, payload.part_name);
  if (card) {
    const qtyEl = card.querySelector('[data-part-qty]');
    if (qtyEl) {
      qtyEl.textContent = `Qty: ${payload.count} / ${payload.quantity_required}`;
    }

    const isNowCompleted = payload.quantity_required > 0 && payload.count >= payload.quantity_required;
    const wasCompleted = card.classList.contains('part-card--completed');

    if (isNowCompleted && !wasCompleted) {
      card.classList.remove('part-card--pending');
      card.classList.add('part-card--completed');
      const warningEl = card.querySelector('.part-card__warning');
      if (warningEl) warningEl.remove();
      panel.querySelector('[data-completed-cards]').appendChild(card);
      updateSectionCounts(panel);
    }

    // Tag ONLY this card as last-detected - clearLastDetectedBadges()
    // above already stripped the badge from every other card on this
    // panel, so at most one badge exists at a time.
    if (!card.querySelector('.part-card__badge')) {
      const badge = document.createElement('span');
      badge.className = 'part-card__badge';
      badge.textContent = 'Last detected';
      card.appendChild(badge);
    }
  } else {
    console.warn('detection:green for a part not found on this panel - part configuration may have changed mid-activity.', payload);
  }

  showPopup(payload.cam_id, panel, {
    variant: 'green',
    partName: payload.part_name,
    count: payload.count,
    required: payload.quantity_required,
    imageUrl: payload.image_url,
    detectedAt: payload.detected_at,
    uptimeSec: payload.popup_uptime_sec,
  });

  playDetectionSound(payload.audio_url);
}

/**
 * Removes the "Last detected" badge from every part-card on this panel.
 * Called before tagging a new one, so exactly one card (or zero, before
 * the first detection) carries the badge at any time.
 */
function clearLastDetectedBadges(panel) {
  panel.querySelectorAll('.part-card__badge').forEach((badge) => badge.remove());
}

/**
 * Handles a "detection:red" event: an unexpected/unconfigured part was
 * detected for this camera. Shows the same full-box pop-up treatment as
 * green (client's explicit call), styled as a warning instead. Alert-
 * type differentiation (Validation Error vs Wrong Part Error) is still
 * a later build - this is only the visual pop-up.
 */
function handleRedDetection(payload) {
  const panel = findCameraPanel(payload.cam_id);
  if (!panel) return;

  showPopup(payload.cam_id, panel, {
    variant: 'red',
    partName: payload.detected_part,
    imageUrl: payload.image_url,
    detectedAt: payload.detected_at,
    uptimeSec: payload.popup_uptime_sec,
  });

  playDetectionSound(payload.audio_url);
}

/**
 * Plays a detection sound once. audio_url is only present in the socket
 * payload when the server decided a sound SHOULD play (green: this
 * camera's toggle is on; red: the table's saved default is enabled) -
 * a null/missing audio_url means silence, so this function does nothing
 * rather than needing its own enabled/disabled logic client-side. A
 * fresh Audio() instance per call so two rapid detections don't cut
 * each other off mid-playback.
 */
function playDetectionSound(audioUrl) {
  if (!audioUrl) return;
  const audio = new Audio(audioUrl);
  audio.play().catch((err) => {
    // Autoplay can be blocked until the user has interacted with the
    // page at least once (browser policy, not a bug in this code) -
    // log rather than throw, since a blocked sound shouldn't break the
    // rest of the monitor page's live updates.
    console.warn('Detection sound playback blocked or failed:', err);
  });
}

/**
 * Handles a "kit:advanced" event: this camera's kit index moved
 * forward. Clears all of that camera's part cards back to a pending,
 * zero-count state (the previous kit's detections remain in the
 * database as history - see cv_ingest/detection_data.py - this is only
 * a UI reset, not a data deletion), clears any last-detected badge
 * (a new kit has no detections yet), and updates the visible "Kit #N"
 * label. The OTHER camera is untouched (cam1/cam2 advance
 * independently, confirmed scope).
 */
/**
 * Handles a "kit:advanced" event: this camera's kit index moved
 * forward. Clears all of that camera's part cards back to a pending,
 * zero-count state (the previous kit's detections remain in the
 * database as history - see cv_ingest/detection_data.py - this is only
 * a UI reset, not a data deletion), clears any last-detected badge
 * (a new kit has no detections yet), updates the visible "Kit #N"
 * label, and resets that camera's Kit timer to 0 (client's explicit
 * requirement - see resetKitTimer()). The OTHER camera is untouched
 * (cam1/cam2 advance independently, confirmed scope).
 *
 * If payload.is_completed is true, this camera has just validated past
 * its last real kit (current_kit_index now exceeds quantity_required) -
 * the entire Completed/Pending section is replaced with a "Kits
 * Completed" state instead of being reset to a fresh pending list,
 * since there IS no next kit's parts to show. Independent per camera -
 * the other camera's own cards are untouched regardless of this one's
 * completion.
 */
/**
 * Updates the top-of-page progress bar for one camera (the "Cam 1 —
 * X/Y · Z%" row next to the status pill). This is server-rendered on
 * page load but was NOT previously updated live - after a socket-driven
 * kit advance, it stayed stale until the page was refreshed. Called
 * from handleKitAdvanced on every advance (completed or not), using the
 * same capping logic as the server's build_monitor_view(): kit_index
 * can be ONE past quantity_required once completed, but the displayed
 * count/percent never exceeds the target.
 */
function updateTopProgressBar(camId, newKitIndex) {
  const monitorPage = document.querySelector('.monitor-page');
  const target = parseInt((monitorPage && monitorPage.dataset.quantityRequired) || '0', 10);
  if (!target) return;

  const progressEl = document.querySelector(`[data-progress="${camId}"]`);
  if (!progressEl) return;

  const effectiveIndex = Math.min(newKitIndex, target);
  const percent = Math.round((effectiveIndex / target) * 10000) / 100; // 2 decimal places, matches server's round(x, 2)

  const labelEl = progressEl.querySelector('[data-progress-label]');
  const fillEl = progressEl.querySelector('[data-progress-fill]');
  if (labelEl) labelEl.textContent = `${effectiveIndex}/${target} \u00b7 ${percent}%`;
  if (fillEl) fillEl.style.width = `${percent}%`;
}

function handleKitAdvanced(payload) {
  const panel = findCameraPanel(payload.cam_id);
  if (!panel) return;

  resetKitTimer(panel, payload.kit_start_time);
  updateTopProgressBar(payload.cam_id, payload.new_kit_index);

  const kitLabel = panel.querySelector('[data-kit-index-label]');

  if (payload.is_completed) {
    if (kitLabel) kitLabel.textContent = 'Kits Completed';
    panel.setAttribute('data-camera-completed', '');

    // Client's explicit requirement: don't show a camera-wise kit timer
    // once that camera's kits are completed - there's no "current kit"
    // left for it to measure. Removed from the tick registry (not just
    // hidden) so it stops being recomputed every second for no reason.
    const timerEl = panel.querySelector('[data-kit-timer]');
    if (timerEl) {
      timerEl.hidden = true;
      _kitTimerRegistry.delete(timerEl);
    }

    const completedSection = panel.querySelector('[data-completed-section]');
    const pendingSection = panel.querySelector('[data-pending-section]');
    const completedCards = panel.querySelector('[data-completed-cards]');
    const pendingCards = panel.querySelector('[data-pending-cards]');
    [completedSection, pendingSection, completedCards, pendingCards].forEach((el) => {
      if (el) el.remove();
    });

    if (!panel.querySelector('[data-camera-done-state]')) {
      const doneState = document.createElement('div');
      doneState.className = 'camera-panel__done-state';
      doneState.setAttribute('data-camera-done-state', '');
      doneState.innerHTML = `
        <span class="camera-panel__done-icon" aria-hidden="true">&#10003;</span>
        <span class="camera-panel__done-text">Kits Completed</span>
      `;
      panel.querySelector('[data-panel-body]').appendChild(doneState);
    }
    return;
  }

  if (kitLabel) kitLabel.textContent = `Kit #${payload.new_kit_index}`;

  clearLastDetectedBadges(panel);

  const pendingZone = panel.querySelector('[data-pending-cards]');

  panel.querySelectorAll('.part-card').forEach((card) => {
    const qtyEl = card.querySelector('[data-part-qty]');
    const required = card.dataset.required || (qtyEl ? qtyEl.textContent.split('/')[1].trim() : '0');
    card.dataset.required = required;
    card.classList.remove('part-card--completed');
    card.classList.add('part-card--pending');

    if (!card.querySelector('.part-card__warning')) {
      const warning = document.createElement('span');
      warning.className = 'part-card__warning';
      warning.setAttribute('aria-hidden', 'true');
      warning.textContent = '\u26A0';
      card.appendChild(warning);
    }

    if (qtyEl) qtyEl.textContent = `Qty: 0 / ${required}`;

    pendingZone.appendChild(card);
  });

  updateSectionCounts(panel);
}

/**
 * Handles a "sound:toggled" event: another viewer (or this same tab)
 * flipped one camera's green-sound toggle. Updates that camera's icon
 * button to match, so every open monitor page for this activity stays
 * in sync (client's explicit requirement: "that also should reflect
 * across the client").
 */
function handleSoundToggled(payload) {
  const panel = findCameraPanel(payload.cam_id);
  if (!panel) return;

  const btn = panel.querySelector('[data-sound-toggle]');
  if (!btn) return;

  const isOn = payload.green_sound_enabled;
  btn.classList.toggle('sound-toggle-btn--on', isOn);
  btn.classList.toggle('sound-toggle-btn--off', !isOn);
  btn.setAttribute('aria-pressed', isOn ? 'true' : 'false');

  const icon = btn.querySelector('[data-sound-toggle-icon]');
  if (icon) icon.textContent = isOn ? '\u{1F50A}' : '\u{1F507}';
}

/**
 * Handles "activity:completed": BOTH cameras have finished all their
 * kits, and the server has already moved the activity from
 * live_activity_details to activity_history with status "completed"
 * (see cv_ingest/detection_data.complete_activity_if_both_cameras_done).
 * Client's explicit requirements, all handled here:
 *   1. Freeze "Total time" at the instant of completion (not still
 *      ticking) - delegates to freezeActivityTimer().
 *   2. Show a brief confirmation overlay, then auto-redirect to the
 *      Live Kitting Activities landing page - the activity document
 *      this page was watching no longer exists in the live collection,
 *      so staying on this URL after the redirect delay would otherwise
 *      dead-end on a now-nonexistent activity.
 */
function handleActivityCompleted(payload) {
  freezeActivityTimer(payload.completed_at);

  const overlay = document.querySelector('[data-activity-complete-overlay]');
  if (overlay) overlay.hidden = false;

  const monitorPage = document.querySelector('.monitor-page');
  const landingUrl = (monitorPage && monitorPage.dataset.landingUrl) || '/';

  window.setTimeout(() => {
    window.location.href = landingUrl;
  }, 2500);
}

/**
 * Wires up each camera panel's sound-toggle button: POSTs to
 * /api/toggle-sound on click. The button's own visual state is NOT
 * flipped optimistically here - it waits for the "sound:toggled" socket
 * event (server is the single source of truth, and every viewer
 * including this tab reacts to the same broadcast), so a failed request
 * never leaves the UI showing a state the server doesn't actually have.
 */
function initSoundToggles() {
  const monitorPage = document.querySelector('.monitor-page');
  if (!monitorPage) return;
  const tableId = monitorPage.dataset.tableId;

  document.querySelectorAll('[data-sound-toggle]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const panel = btn.closest('.camera-panel');
      const camId = panel ? panel.dataset.camId : null;
      if (!camId || !tableId) return;

      fetch('/api/toggle-sound', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ table_id: tableId, camid: camId }),
      })
        .then((res) => res.json())
        .then((data) => {
          if (!data.success) {
            console.warn('Toggle sound failed:', data.error);
          }
          // On success, the UI update comes from the "sound:toggled"
          // socket broadcast (including back to this same tab) - not
          // handled here, to keep a single code path for all viewers.
        })
        .catch((err) => console.warn('Toggle sound request failed:', err));
    });
  });
}

/**
 * Formats an ISO timestamp for the pop-up's metadata strip - local
 * 12-hour clock, same convention as the landing page's activity-start
 * time (see live-activities-list.js), kept minimal here (time only, no
 * timezone label - this is a same-session live event, not a
 * cross-timezone "when did this start" question).
 */
function formatPopupTime(isoString) {
  if (!isoString) return '';
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return '';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

/**
 * Shows the full-box pop-up (image area + metadata strip) for one
 * camera. Per the confirmed layout, the pop-up now covers this
 * camera's ENTIRE half of the page height - Back button row, monitor
 * header, and camera panel - not just the camera panel box (client's
 * explicit correction). It is a page-level element (sibling of
 * .monitor-header/.monitor-cameras, positioned via monitor.css's
 * left/right split), not nested inside the camera-panel, specifically
 * so it can visually extend above the panel. The camera-panel's own
 * body (completed/pending list) is still hidden underneath while the
 * pop-up shows, so nothing looks doubled-up.
 *
 * Uses the ONE fixed [data-popup][data-cam="..."] element already in
 * the template for this camera (show/hide + re-populate), rather than
 * creating/destroying a new element per event - avoids leaking timers
 * if detections arrive faster than the uptime window (a fresh event
 * simply restarts the timer on the same element instead of stacking
 * popups).
 */
function showPopup(camId, panel, { variant, partName, count, required, imageUrl, detectedAt, uptimeSec }) {
  const popupEl = document.querySelector(`.detection-popup[data-cam="${camId}"]`);
  const bodyEl = panel.querySelector('[data-panel-body]');
  if (!popupEl || !bodyEl) return;

  const monitorPage = document.querySelector('.monitor-page');
  const fallbackKey = variant === 'green' ? 'greenPopupUptimeSec' : 'redPopupUptimeSec';
  const defaultUptimeSec = parseFloat((monitorPage && monitorPage.dataset[fallbackKey]) || '2');
  const displaySeconds = uptimeSec || defaultUptimeSec;

  // Clear any in-flight hide timer from a previous popup on this same
  // camera, so a rapid second detection restarts the window instead of
  // being cut off early by the first one's timer.
  if (popupEl._hideTimer) {
    window.clearTimeout(popupEl._hideTimer);
  }

  popupEl.classList.remove('detection-popup--green', 'detection-popup--red');
  popupEl.classList.add(`detection-popup--${variant}`);

  const imageEl = popupEl.querySelector('[data-popup-image]');
  const imageAreaEl = popupEl.querySelector('[data-popup-image-area]');
  if (imageUrl) {
    imageEl.src = imageUrl;
    imageEl.alt = partName || '';
    imageAreaEl.hidden = false;
  } else {
    imageAreaEl.hidden = true;
  }

  // Format: "Detected: <name> | Qty: x/y" - one centered line. Red
  // (unmatched) detections have no meaningful required-qty to show
  // against, so they show just "Detected: <name>".
  const detectedLabel = `Detected: ${partName || ''}`;
  const qtyLabel = variant === 'green' && required ? ` | Qty: ${count} / ${required}` : '';
  popupEl.querySelector('[data-popup-part]').textContent = detectedLabel + qtyLabel;
  popupEl.querySelector('[data-popup-time]').textContent = formatPopupTime(detectedAt);

  popupEl.hidden = false;
  bodyEl.hidden = true;

  popupEl._hideTimer = window.setTimeout(() => {
    popupEl.hidden = true;
    bodyEl.hidden = false;
    popupEl._hideTimer = null;
  }, displaySeconds * 1000);
}

function initSocket() {
  const monitorPage = document.querySelector('.monitor-page');
  if (!monitorPage) return;

  const activityId = monitorPage.dataset.activityId;
  if (!activityId || typeof io === 'undefined') {
    console.warn('Socket.IO client not available or no activity id - live detection sync disabled.');
    return;
  }

  const socket = io();

  socket.on('connect', () => {
    socket.emit('join_activity', { activity_id: activityId });
  });

  socket.on('detection:green', handleGreenDetection);
  socket.on('detection:red', handleRedDetection);
  socket.on('kit:advanced', handleKitAdvanced);
  socket.on('sound:toggled', handleSoundToggled);
  socket.on('activity:completed', handleActivityCompleted);
}

document.addEventListener('DOMContentLoaded', () => {
  initTimers();
  initKitTimers();
  initSocket();
  initSoundToggles();
});
