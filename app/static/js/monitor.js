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
 *      - "detection:red"    -> unexpected part detected, but NOT raised
 *        as a blocking red-screen (neglected part, or the camera's
 *        alert_wrong_part_error switch is off) - same brief full-box
 *        pop-up treatment as green, auto-hides.
 *      - "error:red"        -> NEW - a BLOCKING red-screen (wrong_part
 *        or validation_error, master switch on). Stays on screen, red
 *        audio loops, until the operator picks System Error/Process
 *        Error (+ optional comment) and submits.
 *      - "error:resolved"   -> NEW - the red-screen was resolved (any
 *        viewer). Stops audio, hides the red-screen, unlocks the
 *        camera. validation_error also advances the kit (reuses
 *        handleKitAdvanced); wrong_part does not.
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
      // Existing cards live directly in [data-completed-cards]/[data-pending-cards]
      // OR inside a .part-card-wrapper (new cards created by this
      // function - see below) - moving the card's own closest
      // relevant node (wrapper if present, else the card itself) keeps
      // both shapes working.
      const nodeToMove = card.closest('.part-card-wrapper') || card;
      panel.querySelector('[data-completed-cards]').appendChild(nodeToMove);
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
  } else if (payload.neglected) {
    // A neglected part has no Pending-section placeholder to find
    // (it's not in parts_configured at all), so the FIRST time it's
    // detected in a kit there is nothing for findPartCard() to return.
    // Build the card live, matching the same markup shape
    // build_monitor_view/monitor.html produce on a page load - grouped
    // by name (client: "count increments like a normal part"), so a
    // SECOND detection of the same neglected part goes through the
    // normal "found existing card" branch above instead of creating a
    // duplicate.
    createNeglectedCard(panel, payload);
  } else if (payload.wrong_part) {
    // NEW this round - a genuine wrong_part detection where
    // alert_wrong_part_error is OFF for this camera/kit now ALSO plays
    // green (client's correction), but unlike neglected it is NEVER
    // grouped/counted - same createWrongPartCard() used by the
    // non-blocking detection:red path and the blocking error:red path,
    // so all three wrong_part entry points produce an identical
    // INDIVIDUAL card, just reached via a different pop-up color this
    // time. No resolutionCode yet - a switch-off wrong_part is never
    // gated behind a red-screen, so there is no operator resolution to
    // show a badge for.
    createWrongPartCard(panel, {
      partName: payload.part_name,
      resolutionCode: null,
    });
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
 * Builds and appends a NEW neglected-part card into the Completed
 * section - same markup shape as the server-rendered version (see
 * monitor.html), wrapped in .part-card-wrapper so a future resolution
 * badge slot exists even though a neglected card never actually gets
 * one (only wrong_part cards do - kept consistent so
 * clearLastDetectedBadges()/findPartCard()'s DOM traversal doesn't need
 * two different card shapes to reason about).
 */
function createNeglectedCard(panel, payload) {
  const wrapper = document.createElement('div');
  wrapper.className = 'part-card-wrapper';

  const card = document.createElement('div');
  card.className = 'part-card part-card--completed part-card--neglected';
  card.dataset.partName = payload.part_name;
  card.dataset.cardType = 'neglected';

  const nameEl = document.createElement('span');
  nameEl.className = 'part-card__name';
  nameEl.textContent = payload.part_name;
  card.appendChild(nameEl);

  const qtyEl = document.createElement('span');
  qtyEl.className = 'part-card__qty';
  qtyEl.setAttribute('data-part-qty', '');
  qtyEl.textContent = `Qty: ${payload.count} / 0`;
  card.appendChild(qtyEl);

  const labelEl = document.createElement('span');
  labelEl.className = 'part-card__type-label';
  labelEl.textContent = 'Neglected';
  card.appendChild(labelEl);

  const badge = document.createElement('span');
  badge.className = 'part-card__badge';
  badge.textContent = 'Last detected';
  card.appendChild(badge);

  wrapper.appendChild(card);
  panel.querySelector('[data-completed-cards]').appendChild(wrapper);
  updateSectionCounts(panel);
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
 * detected for this camera, but NOT raised as a blocking red-screen
 * (alert_wrong_part_error master switch is off for this kit/camera -
 * see cv_ingest/detection_data.py; neglected parts now take the green
 * path above instead of ever reaching this handler). Same brief,
 * non-blocking pop-up treatment as green, styled as a warning,
 * auto-hides after popup_uptime_sec. This is DISTINCT from "error:red"
 * (below), which is the actual blocking red-screen. ALSO creates a new
 * individual wrong_part card in Completed (client: "every wrong_part
 * gets its own separate card") - unlike neglected, this is NEVER
 * grouped/counted, so a card is created fresh on every single
 * occurrence, even repeats of the same part name.
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

  createWrongPartCard(panel, {
    partName: payload.detected_part,
    resolutionCode: null,
  });

  playDetectionSound(payload.audio_url);
}

/**
 * Builds and appends ONE new wrong_part card - always a fresh card,
 * never reused/grouped (client's explicit rule - each occurrence has
 * its own independent resolution). resolutionCode is null until/unless
 * this specific occurrence's red-screen gets resolved (see
 * handleErrorResolved below), in which case the S/P badge is added to
 * THIS exact wrapper - the card element is stored on the popup's
 * dataset so handleErrorResolved can find it again without re-querying
 * by part name (which would be ambiguous with multiple same-name
 * cards).
 */
function createWrongPartCard(panel, { partName, resolutionCode }) {
  const wrapper = document.createElement('div');
  wrapper.className = 'part-card-wrapper';

  const card = document.createElement('div');
  card.className = 'part-card part-card--completed part-card--wrong_part';
  card.dataset.partName = partName;
  card.dataset.cardType = 'wrong_part';

  const nameEl = document.createElement('span');
  nameEl.className = 'part-card__name';
  nameEl.textContent = partName;
  card.appendChild(nameEl);

  const labelEl = document.createElement('span');
  labelEl.className = 'part-card__type-label';
  labelEl.textContent = 'Wrong-part';
  card.appendChild(labelEl);

  wrapper.appendChild(card);

  if (resolutionCode) {
    appendResolutionBadge(wrapper, resolutionCode);
  }

  panel.querySelector('[data-completed-cards]').appendChild(wrapper);
  updateSectionCounts(panel);
  return wrapper;
}

/**
 * Appends the S/P badge OUTSIDE the card (client's explicit call:
 * "indicated by P or S outside the card but associated very near to
 * card") - a sibling inside the same .part-card-wrapper, matching the
 * server-rendered shape in monitor.html exactly.
 */
function appendResolutionBadge(wrapper, resolutionCode) {
  const existing = wrapper.querySelector('.part-card__resolution-badge');
  if (existing) existing.remove();
  const badge = document.createElement('span');
  badge.className = 'part-card__resolution-badge';
  badge.textContent = resolutionCode;
  badge.title = resolutionCode === 'S' ? 'System Error' : 'Process Error';
  wrapper.appendChild(badge);
}

// ---------------------------------------------------------------------
// 2b. Blocking red-screen (error:red / error:resolved) - NEW this
// session. Distinct from the brief detection:red popup above: this
// STAYS on screen (no auto-hide timer), shows two resolution buttons
// (System Error / Process Error) + an optional comment box, loops/holds
// the red audio, and locks the camera's whole panel until the operator
// submits. Every viewer of this activity sees and can resolve the same
// red-screen (server is the single source of truth - see
// cv_ingest/detection_data.py's current_kit_errors_cam{N}).
// ---------------------------------------------------------------------

/**
 * Tracks in-flight looping audio per camera, so handleErrorResolved can
 * stop exactly the right <audio> element (a fresh Audio() per replay
 * would leak/overlap otherwise, unlike the brief green/red pop-up sound
 * which only ever plays once).
 */
const _errorAudioRegistry = new Map(); // camId -> HTMLAudioElement

/**
 * Builds a human-readable line for one issue entry, e.g.
 * "Part A required 2 found 0 (missing)" - matches the client's own
 * phrasing exactly. "unrecognized" (wrong_part's synthetic issue) has
 * no required/found numbers, so it renders as just the part name.
 */
function formatIssueLine(issue) {
  if (issue.issue === 'unrecognized') {
    return `Detected: ${issue.part_name} (unrecognized part)`;
  }
  return `${issue.part_name} required ${issue.required} found ${issue.found} (${issue.issue})`;
}

/**
 * Renders and locks in the blocking red-screen for one camera. Reused
 * by both handleErrorRed() (a live "error:red" socket event) and
 * initActiveErrorsOnLoad() (a viewer opening the page while an error is
 * ALREADY active - server-rendered current_kit_errors_cam{N}, see
 * monitor.html/activities_data.build_monitor_view), so both paths
 * produce identical UI.
 */
function showErrorScreen(camId, { errorType, issues, imageUrl, audioUrl }) {
  const panel = findCameraPanel(camId);
  if (!panel) return;

  const popupEl = document.querySelector(`.detection-popup[data-cam="${camId}"]`);
  const bodyEl = panel.querySelector('[data-panel-body]');
  if (!popupEl || !bodyEl) return;

  // A locked camera's brief-popup auto-hide timer (if one happened to
  // be in flight) must not fire and reveal the normal panel underneath
  // the red-screen - clear it defensively.
  if (popupEl._hideTimer) {
    window.clearTimeout(popupEl._hideTimer);
    popupEl._hideTimer = null;
  }

  popupEl.classList.remove('detection-popup--green', 'detection-popup--red');
  popupEl.classList.add('detection-popup--red', 'detection-popup--blocking');

  const imageEl = popupEl.querySelector('[data-popup-image]');
  const imageAreaEl = popupEl.querySelector('[data-popup-image-area]');
  if (imageUrl) {
    imageEl.src = imageUrl;
    imageEl.alt = '';
    imageAreaEl.hidden = false;
  } else {
    imageAreaEl.hidden = true;
  }

  const label = errorType === 'validation_error' ? 'Validation Error' : 'Wrong Part Error';
  popupEl.querySelector('[data-popup-part]').textContent = label;
  popupEl.querySelector('[data-popup-time]').textContent = '';

  const issuesEl = popupEl.querySelector('[data-error-issues]');
  if (issuesEl) {
    issuesEl.innerHTML = '';
    issues.forEach((issue) => {
      const line = document.createElement('div');
      line.className = 'detection-popup__issue-line';
      line.textContent = formatIssueLine(issue);
      issuesEl.appendChild(line);
    });
  }

  const commentEl = popupEl.querySelector('[data-error-comment]');
  if (commentEl) commentEl.value = '';

  popupEl.hidden = false;
  bodyEl.hidden = true;
  panel.setAttribute('data-camera-locked', '');

  playErrorAudioLoop(camId, audioUrl);
}

/**
 * Plays the red audio on a loop while the red-screen is active (client:
 * "audio plays... until operator choose... and click submit") - unlike
 * the brief pop-up's one-shot playDetectionSound(). Stored in
 * _errorAudioRegistry so handleErrorResolved can stop this exact
 * element later.
 */
function playErrorAudioLoop(camId, audioUrl) {
  //console.log('[DEBUG red-screen audio]', { camId, audioUrl }); // TEMP - remove after diagnosing
  stopErrorAudio(camId);
  if (!audioUrl) return;
  const audio = new Audio(audioUrl);
  audio.loop = true;
  audio.play().catch((err) => {
    console.warn('Error red-screen audio playback blocked or failed:', err);
  });
  _errorAudioRegistry.set(camId, audio);
}
function stopErrorAudio(camId) {
  const existing = _errorAudioRegistry.get(camId);
  if (existing) {
    existing.pause();
    existing.currentTime = 0;
    _errorAudioRegistry.delete(camId);
  }
}

/**
 * Handles "error:red": either a wrong_part detection or a validate_kit
 * call just raised a BLOCKING red-screen (camera's relevant master
 * switch was on - see cv_ingest/detection_data.py). Stays until
 * resolved; no popup_uptime_sec, no auto-hide.
 */
function handleErrorRed(payload) {
  showErrorScreen(payload.cam_id, {
    errorType: payload.error.error_type,
    issues: payload.error.issues,
    imageUrl: payload.image_url,
    audioUrl: payload.audio_url,
  });

  // NEW - a BLOCKING wrong_part red-screen never passes through
  // handleRedDetection() (that's only the non-blocking brief path), so
  // its card has to be created here instead. validation_error has no
  // matching card at all (its issues live only in the red-screen
  // itself / detections.errors - never in wrong_part_cards), so this
  // only fires for error_type === "wrong_part". Stored on the popup
  // element's dataset so handleErrorResolved can find THIS exact card
  // later without an ambiguous by-name lookup (multiple wrong_part
  // cards can share the same part_name).
  if (payload.error.error_type === 'wrong_part') {
    const panel = findCameraPanel(payload.cam_id);
    if (panel) {
      const partName = payload.error.issues && payload.error.issues[0]
        ? payload.error.issues[0].part_name
        : null;
      const wrapper = createWrongPartCard(panel, { partName, resolutionCode: null });
      const popupEl = document.querySelector(`.detection-popup[data-cam="${payload.cam_id}"]`);
      if (popupEl) popupEl._pendingWrongPartCard = wrapper;
    }
  }
}

/**
 * Handles "error:resolved": an operator (on any viewer's tab) submitted
 * system_error/process_error for this camera's red-screen. Every
 * viewer, including the one that submitted it, reacts to this same
 * broadcast (server is the single source of truth) - stops audio, hides
 * the red-screen, unlocks the panel, and:
 *   - validation_error: behaves exactly like a normal "kit:advanced" -
 *     reuses handleKitAdvanced's own reset/completed logic so the two
 *     code paths can never drift apart.
 *   - wrong_part: kit index unchanged - just reveals the panel body
 *     again, exactly as it was before the red-screen interrupted it,
 *     and appends the S/P badge to the card handleErrorRed created
 *     (client: "operator choise... indicated by P or S outside the
 *     card but associated very near to card").
 */
function handleErrorResolved(payload) {
  const panel = findCameraPanel(payload.cam_id);
  if (!panel) return;

  stopErrorAudio(payload.cam_id);

  const popupEl = document.querySelector(`.detection-popup[data-cam="${payload.cam_id}"]`);
  if (popupEl) {
    popupEl.hidden = true;
    popupEl.classList.remove('detection-popup--blocking');
  }

  panel.removeAttribute('data-camera-locked');

  if (payload.error_type === 'validation_error') {
    // Resolving a validation_error IS the advance (client's explicit
    // rule) - reuse the exact same UI-reset path a normal validate
    // would trigger, so Completed/Pending reset, the Kit timer resets,
    // "Kit #N" updates, and the top progress bar updates identically.
    handleKitAdvanced({
      cam_id: payload.cam_id,
      new_kit_index: payload.new_kit_index,
      is_completed: payload.is_completed,
      kit_start_time: payload.kit_start_time,
    });
  } else {
    // wrong_part: kit index untouched - just reveal the panel body
    // that was hidden underneath the red-screen.
    const bodyEl = panel.querySelector('[data-panel-body]');
    if (bodyEl) bodyEl.hidden = false;

    if (popupEl && popupEl._pendingWrongPartCard && payload.resolution_code) {
      appendResolutionBadge(popupEl._pendingWrongPartCard, payload.resolution_code);
      popupEl._pendingWrongPartCard = null;
    }
  }
}

/**
 * Handles "config:updated" (NEW this round) - fires when an operator
 * edits the kit currently running as THIS activity in Current Kits
 * Configuration (client's ask: "check if any live activity is there
 * and update the configuration of live activity also... broadcast an
 * update so viewers see new config-driven behavior without
 * refreshing"). No visible element on this page currently mirrors
 * parts_configured/neglect_parts/camerawise_alert_config directly - the
 * per-part alert flags and camera master switches only ever affect
 * SERVER-side detection/validate logic, which already re-reads the
 * activity doc fresh on every single call, so the propagation itself
 * needs no client-side action to "take effect." This handler exists so
 * the change is at least visible for confirmation/debugging without
 * opening devtools, and as the hook point if a future build DOES want
 * to reflect live config changes visually (e.g. a toast, or an updated
 * on-screen alert-config summary).
 */
function handleConfigUpdated(payload) {
  console.log('Kit configuration updated for this activity - new detections/validations will use the updated config.', payload);
}

/**
 * Wires the red-screen's two resolution buttons + optional comment box
 * + Submit. One shared handler for both camera's fixed popup elements
 * (same "one fixed element per camera, re-populate on each event"
 * convention as showPopup()). POSTs to /api/resolve-error; the actual
 * UI teardown happens on the "error:resolved" broadcast, not here
 * (same reasoning as initSoundToggles - server is the single source of
 * truth, every viewer including this tab reacts to the same event).
 */
function initErrorResolutionControls() {
  const monitorPage = document.querySelector('.monitor-page');
  if (!monitorPage) return;
  const tableId = monitorPage.dataset.tableId;

  document.querySelectorAll('.detection-popup').forEach((popupEl) => {
    const camId = popupEl.dataset.cam;
    let chosenOption = null;

    const systemBtn = popupEl.querySelector('[data-error-option="system_error"]');
    const processBtn = popupEl.querySelector('[data-error-option="process_error"]');
    const submitBtn = popupEl.querySelector('[data-error-submit]');

    function selectOption(option, activeBtn, inactiveBtn) {
      chosenOption = option;
      if (activeBtn) activeBtn.classList.add('error-option-btn--selected');
      if (inactiveBtn) inactiveBtn.classList.remove('error-option-btn--selected');
      if (submitBtn) submitBtn.disabled = false;
    }

    if (systemBtn) {
      systemBtn.addEventListener('click', () => selectOption('system_error', systemBtn, processBtn));
    }
    if (processBtn) {
      processBtn.addEventListener('click', () => selectOption('process_error', processBtn, systemBtn));
    }

    if (submitBtn) {
      submitBtn.addEventListener('click', () => {
        if (!chosenOption || !tableId) return;
        const commentEl = popupEl.querySelector('[data-error-comment]');
        const comment = commentEl ? commentEl.value : '';

        submitBtn.disabled = true;

        fetch('/api/resolve-error', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            table_id: tableId,
            camid: camId,
            chosen_option: chosenOption,
            comment: comment,
          }),
        })
          .then((res) => res.json())
          .then((data) => {
            if (!data.success) {
              console.warn('Resolve error failed:', data.message);
              submitBtn.disabled = false;
            }
            // On success, teardown comes from the "error:resolved"
            // socket broadcast (including back to this same tab) -
            // not handled here, single code path for all viewers.
            chosenOption = null;
            if (systemBtn) systemBtn.classList.remove('error-option-btn--selected');
            if (processBtn) processBtn.classList.remove('error-option-btn--selected');
          })
          .catch((err) => {
            console.warn('Resolve error request failed:', err);
            submitBtn.disabled = false;
          });
      });
    }
  });
}

/**
 * On page load, renders any camera that already has an active,
 * unresolved error - persistence for a viewer who opens (or refreshes)
 * the monitor page WHILE a red-screen is showing on some other client
 * (client's explicit requirement). Data comes server-rendered via
 * data-* attributes on each camera panel (see monitor.html /
 * activities_data.build_monitor_view's is_locked/active_error fields) -
 * no extra request needed.
 */
function initActiveErrorsOnLoad() {
  document.querySelectorAll('.camera-panel[data-camera-locked]').forEach((panel) => {
    const camId = panel.dataset.camId;
    const errorDataEl = panel.querySelector('[data-active-error]');
    if (!errorDataEl) return;
    try {
      const error = JSON.parse(errorDataEl.textContent);
      const imageUrl = error.image_path ? `/api/detection-image/${error.image_path}` : null;
      showErrorScreen(camId, {
        errorType: error.error_type,
        issues: error.issues,
        imageUrl,
        audioUrl: null, // don't replay audio just for a page load/refresh - only on the live event that raised it
      });
    } catch (err) {
      console.warn('Could not parse active error data on load:', err);
    }
  });
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

  // FIX - neglected/wrong_part cards belong to the kit that just
  // finished, not the new one starting now (client: "it should go off
  // after kit increments automatically"). They are REMOVED entirely
  // here (their own wrapper included, so no orphaned empty
  // .part-card-wrapper is left behind) rather than reset-and-moved to
  // Pending like a normal configured part - a fresh kit has no
  // detections yet, so there is nothing valid to show until (if ever)
  // the next kit gets its own neglected/wrong_part occurrence.
  panel.querySelectorAll('.part-card--neglected, .part-card--wrong_part').forEach((card) => {
    const node = card.closest('.part-card-wrapper') || card;
    node.remove();
  });

  panel.querySelectorAll('.part-card:not(.part-card--neglected):not(.part-card--wrong_part)').forEach((card) => {
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
/**
 * Handles "kit:validated" (NEW this session) - fires on EVERY clean
 * kit advance (no validation_error), showing a brief confirmation
 * pop-up before the panel reverts to its normal state (client's
 * report: "on validation, nothing shows... show kit 1 completed, next
 * kit 2"). Reuses the SAME .detection-popup element/positioning as the
 * green/red pop-ups, with its OWN two variants:
 *   - Normal advance: GREEN, "Kit <old> completed | Next: Kit <new>",
 *     with the validation image if one was sent.
 *   - Final advance (is_completed true): BLUE (client's explicit
 *     third color, distinct from green/red/blocking-red) - image area
 *     replaced with solid blue + centered "All kits in Cam<N>
 *     completed" text, no "next kit" line.
 * "kit:advanced" (unchanged, still emitted alongside this by routes.py)
 * has already reset the panel underneath by the time this pop-up
 * hides - same layering as the existing green/red pop-up, which also
 * covers a panel that has already been updated live underneath it.
 */
function handleKitValidated(payload) {
  const panel = findCameraPanel(payload.cam_id);
  if (!panel) return;

  const popupEl = document.querySelector(`.detection-popup[data-cam="${payload.cam_id}"]`);
  const bodyEl = panel.querySelector('[data-panel-body]');
  if (!popupEl || !bodyEl) return;

  if (popupEl._hideTimer) {
    window.clearTimeout(popupEl._hideTimer);
  }

  popupEl.classList.remove('detection-popup--green', 'detection-popup--red', 'detection-popup--blocking', 'detection-popup--blue');

  const imageEl = popupEl.querySelector('[data-popup-image]');
  const imageAreaEl = popupEl.querySelector('[data-popup-image-area]');
  const partEl = popupEl.querySelector('[data-popup-part]');
  const timeEl = popupEl.querySelector('[data-popup-time]');

  if (payload.is_completed) {
    popupEl.classList.add('detection-popup--blue');
    // Image area is replaced with solid blue + centered text (client's
    // exact wording: "in image section show full blue color with text
    // in middle saying all kits in cam1/2 completed") - the validation
    // image, if any was sent, is NOT shown for this variant, since the
    // client's spec for this state is the solid-color + text treatment
    // specifically, not a photo.
    imageAreaEl.hidden = false;
    imageEl.hidden = true;
    let overlayText = imageAreaEl.querySelector('[data-popup-blue-text]');
    if (!overlayText) {
      overlayText = document.createElement('span');
      overlayText.setAttribute('data-popup-blue-text', '');
      overlayText.className = 'detection-popup__blue-text';
      imageAreaEl.appendChild(overlayText);
    }
    overlayText.hidden = false;
    const camLabel = payload.cam_id === 'cam1' ? 'Cam1' : 'Cam2';
    overlayText.textContent = `All kits in ${camLabel} completed`;
    partEl.textContent = '';
    timeEl.textContent = '';
  } else {
    const overlayText = imageAreaEl.querySelector('[data-popup-blue-text]');
    if (overlayText) overlayText.hidden = true;
    imageEl.hidden = false;

    if (payload.image_url) {
      imageEl.src = payload.image_url;
      imageEl.alt = '';
      imageAreaEl.hidden = false;
    } else {
      imageAreaEl.hidden = true;
    }
    partEl.textContent = `Kit ${payload.old_kit_index} completed | Next: Kit ${payload.new_kit_index}`;
    timeEl.textContent = '';
  }

  const monitorPage = document.querySelector('.monitor-page');
  const defaultUptimeSec = parseFloat((monitorPage && monitorPage.dataset.validatePopupUptimeSec) || '3');
  const displaySeconds = payload.popup_uptime_sec || defaultUptimeSec;

  popupEl.hidden = false;
  bodyEl.hidden = true;

  popupEl._hideTimer = window.setTimeout(() => {
    popupEl.hidden = true;
    bodyEl.hidden = false;
    popupEl._hideTimer = null;
  }, displaySeconds * 1000);

  playDetectionSound(payload.audio_url);
}

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

  popupEl.classList.remove('detection-popup--green', 'detection-popup--red', 'detection-popup--blocking');
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
  socket.on('kit:validated', handleKitValidated);
  socket.on('kit:advanced', handleKitAdvanced);
  socket.on('sound:toggled', handleSoundToggled);
  socket.on('activity:completed', handleActivityCompleted);
  socket.on('error:red', handleErrorRed);
  socket.on('error:resolved', handleErrorResolved);
  socket.on('config:updated', handleConfigUpdated);
}

document.addEventListener('DOMContentLoaded', () => {
  initTimers();
  initKitTimers();
  initSocket();
  initSoundToggles();
  initErrorResolutionControls();
  initActiveErrorsOnLoad();
});
