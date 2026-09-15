/**
 * live-camera-history.js
 *
 * Per-camera "History" button on the monitor page's camera panels -
 * shows that CAMERA's progress on the CURRENTLY RUNNING activity so
 * far: the same color-coded kit circle grid + Kit Detail drill-down
 * already built for the completed-activity History section, but for
 * one camera's live, in-progress activity.
 *
 * Follows the EXACT same pattern as the existing "Current Settings"
 * modal in monitor.js (client's explicit choice, for consistency with
 * this file): fetch JSON fresh every open, render HTML client-side via
 * small composable functions, reset to a loading state before every
 * fetch so stale content is never briefly shown. This is a SEPARATE
 * file/modal from the settings one - two independent backdrops, never
 * open at the same time in practice but not mutually exclusive by
 * code (no shared state between them).
 */

function initLiveCameraHistoryModal() {
  const monitorPage = document.querySelector('.monitor-page');
  const backdrop = document.querySelector('[data-live-history-backdrop]');
  const closeBtn = document.querySelector('[data-live-history-close]');
  const body = document.querySelector('[data-live-history-body]');
  if (!monitorPage || !backdrop || !closeBtn || !body) return;

  const activityId = monitorPage.dataset.activityId;

  function closeModal() {
    backdrop.hidden = true;
  }

  function openModal(camId) {
    backdrop.hidden = false;
    body.innerHTML = '<p class="live-history-modal__loading">Loading history&hellip;</p>';
    loadCameraHistory(camId);
  }

  function loadCameraHistory(camId) {
    body.innerHTML = '<p class="live-history-modal__loading">Loading history&hellip;</p>';

    fetch(`/live-kitting-activities/${activityId}/history/${camId}`)
      .then((res) => res.json())
      .then((data) => {
        if (!data.success) {
          body.innerHTML = `<p class="live-history-modal__error">Could not load history: ${escapeHtml(data.error || 'Unknown error')}</p>`;
          return;
        }
        body.innerHTML = renderCameraHistory(data.report);
        wireCircleClicks(camId);
        formatDurationElements(body);
      })
      .catch((err) => {
        console.warn('Failed to fetch live camera history:', err);
        body.innerHTML = '<p class="live-history-modal__error">Could not load history. Check your connection and try again.</p>';
      });
  }

  function loadKitDetail(camId, kitIndex) {
    body.innerHTML = '<p class="live-history-modal__loading">Loading kit detail&hellip;</p>';

    fetch(`/live-kitting-activities/${activityId}/history/${camId}/${kitIndex}`)
      .then((res) => res.json())
      .then((data) => {
        if (!data.success) {
          body.innerHTML = `<p class="live-history-modal__error">Could not load kit detail: ${escapeHtml(data.error || 'Unknown error')}</p>`;
          return;
        }
        body.innerHTML = renderKitDetail(camId, data.detail);
        wireBackButton(camId);
        wireLightbox();
        formatDurationElements(body);
      })
      .catch((err) => {
        console.warn('Failed to fetch live kit detail:', err);
        body.innerHTML = '<p class="live-history-modal__error">Could not load kit detail. Check your connection and try again.</p>';
      });
  }

  function wireCircleClicks(camId) {
    body.querySelectorAll('.kit-circle[data-kit-index]').forEach((circle) => {
      circle.addEventListener('click', () => {
        loadKitDetail(camId, circle.dataset.kitIndex);
      });
    });
  }

  function wireBackButton(camId) {
    const backBtn = body.querySelector('[data-back-to-circles]');
    if (backBtn) {
      backBtn.addEventListener('click', () => loadCameraHistory(camId));
    }
  }

  // Every .camera-panel__history-btn on the page opens THIS modal,
  // scoped to its OWN camera-panel's data-cam-id - two buttons (one
  // per camera-panel, cam1 and cam2), one shared modal.
  document.querySelectorAll('.camera-panel__history-btn').forEach((btn) => {
    const panel = btn.closest('.camera-panel');
    if (!panel) return;
    const camId = panel.dataset.camId;
    btn.addEventListener('click', () => openModal(camId));
  });

  closeBtn.addEventListener('click', closeModal);
  backdrop.addEventListener('click', (event) => {
    if (event.target === backdrop) closeModal();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !backdrop.hidden) closeModal();
  });
}

// ---------------------------------------------------------------------------
// Rendering - camera history (circle grid)
// ---------------------------------------------------------------------------

function renderCameraHistory(report) {
  const camLabel = report.header.cam_id === 'cam1' ? 'Camera 1' : 'Camera 2';
  const progressLabel = report.header.camera_completed
    ? `Kits Completed (${escapeHtml(report.header.quantity_required)}/${escapeHtml(report.header.quantity_required)})`
    : `Kit #${escapeHtml(report.header.current_kit_index)} of ${escapeHtml(report.header.quantity_required)}`;

  const headerHtml = `
    <div class="live-history-modal__header">
      <h2>${camLabel} — History so far</h2>
      <div class="live-history-modal__meta">
        <span>Order ${escapeHtml(report.header.order_number)}</span>
        <span>|</span>
        <span>${escapeHtml(report.header.kit_name)}</span>
        <span>|</span>
        <span>${progressLabel}</span>
      </div>
    </div>
  `;

  const summaryHtml = `
    <div class="live-history-modal__summary">
      <div class="stat-row"><span>Validation Errors</span><strong>${escapeHtml(report.summary.error_counts.validation_error)}</strong></div>
      <div class="stat-row"><span>Wrong Part Errors</span><strong>${escapeHtml(report.summary.error_counts.wrong_part)}</strong></div>
      <div class="stat-row"><span>System Errors</span><strong>${escapeHtml(report.summary.error_counts.system_error)}</strong></div>
      <div class="stat-row"><span>Process Errors</span><strong>${escapeHtml(report.summary.error_counts.process_error)}</strong></div>
    </div>
  `;

  const timing = report.summary.timing;
  const timingHtml = `
    <div class="timing-table-wrap">
      <table class="timing-table">
        <thead><tr><th></th><th>Avg</th><th>Min</th><th>Max</th></tr></thead>
        <tbody>
          <tr>
            <td>Total Kit Time</td>
            <td class="report-duration" data-seconds="${timing.total_kit_time.avg_sec}">—</td>
            <td class="report-duration" data-seconds="${timing.total_kit_time.min_sec}">—</td>
            <td class="report-duration" data-seconds="${timing.total_kit_time.max_sec}">—</td>
          </tr>
          <tr>
            <td>Active Time</td>
            <td class="report-duration" data-seconds="${timing.active_time.avg_sec}">—</td>
            <td class="report-duration" data-seconds="${timing.active_time.min_sec}">—</td>
            <td class="report-duration" data-seconds="${timing.active_time.max_sec}">—</td>
          </tr>
        </tbody>
      </table>
    </div>
  `;

  const legendHtml = `
    <div class="live-history-modal__legend">
      <span class="legend-item"><span class="legend-swatch legend-swatch--green"></span>Clean</span>
      <span class="legend-item"><span class="legend-swatch legend-swatch--yellow"></span>Silent undercount</span>
      <span class="legend-item"><span class="legend-swatch legend-swatch--purple"></span>Silent wrong-part / missing / overcount</span>
      <span class="legend-item"><span class="legend-swatch legend-swatch--red"></span>Logged error</span>
      <span class="legend-item"><span class="legend-swatch legend-swatch--in-progress"></span>In progress</span>
    </div>
  `;

  const circlesHtml = `
    <div class="kit-circle-grid">
      ${report.cards.map(renderKitCircle).join('')}
    </div>
  `;

  return headerHtml + summaryHtml + timingHtml + legendHtml + circlesHtml;
}

function renderKitCircle(card) {
  if (card.color === 'in_progress') {
    return `
      <div class="kit-circle kit-circle--in-progress" title="Kit ${escapeHtml(card.kit_index)} — in progress">
        <span class="kit-circle__number">${escapeHtml(card.kit_index)}</span>
      </div>
    `;
  }

  const chipHtml = card.chip_badge
    ? `<span class="chip-badge">${escapeHtml(card.chip_badge)}</span>`
    : '';

  return `
    <button type="button"
            class="kit-circle kit-circle--${escapeHtml(card.color)}"
            data-kit-index="${escapeHtml(card.kit_index)}"
            title="Kit ${escapeHtml(card.kit_index)} — click for details">
      ${chipHtml}
      <span class="kit-circle__number">${escapeHtml(card.kit_index)}</span>
    </button>
  `;
}

// ---------------------------------------------------------------------------
// Rendering - kit detail
// ---------------------------------------------------------------------------

function renderKitDetail(camId, detail) {
  const camLabel = camId === 'cam1' ? 'Camera 1' : 'Camera 2';

  const headerHtml = `
    <button type="button" class="btn btn--secondary btn--small" data-back-to-circles>&larr; Back</button>
    <div class="kit-detail-header__crumbs">
      <span class="kit-detail-header__cam">${camLabel}</span>
      <span>|</span>
      <span>Kit #${escapeHtml(detail.header.kit_index)}</span>
      <span>|</span>
      <span>Order ${escapeHtml(detail.header.order_number)}</span>
      <span>|</span>
      <span>${escapeHtml(detail.header.kit_name)}</span>
    </div>
  `;

  const analyticsHtml = `
    <section class="kit-detail-analytics">
      <div class="analytics-stat">
        <span class="analytics-stat__label">Total Kit Time</span>
        <strong class="report-duration" data-seconds="${detail.analytics.total_kit_time_sec}">—</strong>
      </div>
      <div class="analytics-stat">
        <span class="analytics-stat__label">Active Time</span>
        <strong class="report-duration" data-seconds="${detail.analytics.active_time_sec}">—</strong>
      </div>
      <div class="analytics-stat">
        <span class="analytics-stat__label">Avg Detection Gap</span>
        <strong class="report-duration" data-seconds="${detail.analytics.avg_detection_gap_sec}">—</strong>
      </div>
    </section>
  `;

  const wrongPartHtml = detail.wrong_part_section.length
    ? `
      <section class="kit-detail-section kit-detail-section--wrong-part">
        <h3 class="kit-detail-section__heading"><span class="kit-detail-section__icon">&#9888;</span>Wrong Parts Detected</h3>
        ${detail.wrong_part_section.map(renderWrongPartGroup).join('')}
      </section>
    `
    : '';

  const anomaliesHtml = detail.anomalies_section
    ? `
      <section class="kit-detail-section kit-detail-section--anomalies">
        <h3 class="kit-detail-section__heading"><span class="kit-detail-section__icon">&#9888;</span>Errors &amp; Anomalies</h3>
        ${renderAnomaliesBox(detail.anomalies_section)}
      </section>
    `
    : '';

  const partsHtml = `
    <section class="kit-detail-section">
      <h3 class="kit-detail-section__heading">Parts</h3>
      <div class="part-card-grid">
        ${detail.part_cards.map(renderPartCard).join('')}
      </div>
    </section>
  `;

  return `<div class="live-kit-detail">${headerHtml}${analyticsHtml}${wrongPartHtml}${anomaliesHtml}${partsHtml}</div>`;
}

function renderWrongPartGroup(group) {
  const resolutionHtml = group.resolution
    ? `<span class="anomaly-box__resolution">Resolution: ${group.resolution.chosen_option === 'system_error' ? 'System Error' : 'Process Error'}</span>`
    : '';

  return `
    <div class="anomaly-box">
      <div class="anomaly-box__top">
        <span class="anomaly-box__badge">WRONG PART</span>
        ${resolutionHtml}
      </div>
      <div class="anomaly-box__part-name">${escapeHtml(group.part_name)}</div>
      ${renderImageRow(group.images, group.part_name)}
    </div>
  `;
}

function renderAnomaliesBox(section) {
  const resolutionHtml = section.resolution
    ? `<span class="anomaly-box__resolution">Resolution: ${section.resolution.chosen_option === 'system_error' ? 'System Error' : 'Process Error'}</span>`
    : '';

  const issueTypes = section.issues.map((i) => i.issue.toUpperCase()).join(', ');
  const partNames = section.issues.map((i) => i.part_name).join(', ');

  const imageHtml = section.image_url
    ? `<div class="image-thumb-row"><img src="${escapeHtml(section.image_url)}" class="image-thumb" alt="Validation snapshot" data-full="${escapeHtml(section.image_url)}"></div>`
    : '';

  return `
    <div class="anomaly-box">
      <div class="anomaly-box__top">
        <span class="anomaly-box__badge">${escapeHtml(issueTypes)}</span>
        ${resolutionHtml}
      </div>
      <div class="anomaly-box__parts">${escapeHtml(partNames)}</div>
      ${imageHtml}
    </div>
  `;
}

function renderPartCard(part) {
  return `
    <div class="part-card part-card--${escapeHtml(part.color)}">
      <div class="part-card__header">
        <div>
          <span class="part-card__label">PART:</span>
          <div class="part-card__name">${escapeHtml(part.part_name)}</div>
        </div>
        <span class="part-card__count">${escapeHtml(part.found)}/${escapeHtml(part.required)}</span>
      </div>
      ${renderImageRow(part.images, part.part_name)}
    </div>
  `;
}

function renderImageRow(images, altText) {
  if (!images.length) {
    return '<p class="kit-detail-no-images">No images captured</p>';
  }
  return `
    <div class="image-thumb-row">
      ${images.map((img) => `<img src="${escapeHtml(img.url)}" class="image-thumb" alt="${escapeHtml(altText)} detection" data-full="${escapeHtml(img.url)}">`).join('')}
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Shared helpers - duration formatting + lightbox, ported from
// activity-report.js / kit-detail.js (History's own JS) since this
// modal is a separate page/context and can't share a <script> tag with
// those files without loading History's whole JS bundle on every
// monitor page load. Kept in sync BY HAND - same duplication
// convention as the Python side (history_data.py /
// live_activity_report_data.py).
// ---------------------------------------------------------------------------

function formatDuration(totalSeconds) {
  if (totalSeconds === null || totalSeconds === undefined || totalSeconds === 'None' || isNaN(totalSeconds)) {
    return '—';
  }
  const seconds = Math.round(parseFloat(totalSeconds));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60) return `${minutes}m ${remainingSeconds}s`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h ${remainingMinutes}m`;
}

function formatDurationElements(container) {
  container.querySelectorAll('.report-duration[data-seconds]').forEach((el) => {
    el.textContent = formatDuration(el.dataset.seconds);
  });
}

// Lightbox - same behavior as kit-detail.js's (click-to-open,
// wraparound prev/next across every image currently in the modal,
// zoom via click-toggle + scroll wheel, escape/backdrop/× to close).
// Re-wired every time renderKitDetail's content replaces the modal
// body, since the .image-thumb elements are destroyed/recreated on
// every fetch.
function wireLightbox() {
  const lightbox = document.querySelector('[data-live-lightbox]');
  const lightboxImage = document.querySelector('[data-live-lightbox-image]');
  const closeBtn = document.querySelector('[data-live-lightbox-close]');
  const prevBtn = document.querySelector('[data-live-lightbox-prev]');
  const nextBtn = document.querySelector('[data-live-lightbox-next]');
  if (!lightbox || !lightboxImage || !closeBtn || !prevBtn || !nextBtn) return;

  const thumbs = Array.from(document.querySelectorAll('[data-live-history-body] .image-thumb'));
  if (thumbs.length === 0) return;

  let currentIndex = 0;
  let zoomLevel = 1;

  function applyZoom() {
    lightboxImage.style.transform = `scale(${zoomLevel})`;
  }

  function showImage(index) {
    currentIndex = (index + thumbs.length) % thumbs.length;
    const thumb = thumbs[currentIndex];
    lightboxImage.src = thumb.dataset.full || thumb.src;
    lightboxImage.alt = thumb.alt;
    zoomLevel = 1;
    applyZoom();
  }

  function openLightbox(index) {
    showImage(index);
    lightbox.hidden = false;
    lightbox.style.display = 'flex';
  }

  function closeLightbox() {
    lightbox.hidden = true;
    lightbox.style.display = 'none';
  }

  thumbs.forEach((thumb, index) => {
    thumb.addEventListener('click', () => openLightbox(index));
  });

  closeBtn.onclick = closeLightbox;
  prevBtn.onclick = () => showImage(currentIndex - 1);
  nextBtn.onclick = () => showImage(currentIndex + 1);

  lightbox.onclick = (event) => {
    if (event.target === lightbox) closeLightbox();
  };
  lightboxImage.onclick = () => {
    zoomLevel = zoomLevel === 1 ? 2 : 1;
    applyZoom();
  };
  lightboxImage.onwheel = (event) => {
    event.preventDefault();
    const delta = event.deltaY < 0 ? 0.2 : -0.2;
    zoomLevel = Math.min(4, Math.max(1, zoomLevel + delta));
    applyZoom();
  };

  document.addEventListener('keydown', (event) => {
    if (lightbox.hidden) return;
    if (event.key === 'Escape') closeLightbox();
    if (event.key === 'ArrowLeft') showImage(currentIndex - 1);
    if (event.key === 'ArrowRight') showImage(currentIndex + 1);
  });
}

document.addEventListener('DOMContentLoaded', initLiveCameraHistoryModal);
