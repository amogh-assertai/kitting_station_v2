/**
 * Live Kitting Activity - Monitor page behavior.
 *
 * Two independent concerns in this file:
 *
 * 1. Elapsed-time timers (unchanged from the original UI-only build) -
 *    "Total time" (header) and each camera panel's timer show the
 *    activity's running time, computed client-side against created_at.
 *
 * 2. Socket.IO live detection sync - every browser tab viewing this
 *    activity's monitor page joins a server-side room keyed by activity
 *    id, and reacts to three events pushed from cv_ingest/routes.py
 *    when the DeepStream application posts a detection:
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
 *        (cam1/cam2 advance independently).
 *      - "sound:toggled"    -> a viewer flipped one camera's green-sound
 *        toggle; every viewer's icon updates to match, so the toggle
 *        state stays in sync across all open monitor pages for this
 *        activity.
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
// 1. Elapsed-time timers (unchanged)
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

  function tick() {
    valid.forEach(({ el, startTime }) => {
      const elapsedSeconds = (Date.now() - startTime) / 1000;
      el.textContent = formatElapsed(Math.max(elapsedSeconds, 0));
    });
  }

  tick();
  setInterval(tick, 1000);
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
function handleKitAdvanced(payload) {
  const panel = findCameraPanel(payload.cam_id);
  if (!panel) return;

  const kitLabel = panel.querySelector('[data-kit-index-label]');
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
}

document.addEventListener('DOMContentLoaded', () => {
  initTimers();
  initSocket();
  initSoundToggles();
});
