/**
 * PQPR upload widget.
 *
 * - Uploads/replaces the PQPR Excel file via AJAX (no page reload).
 * - Triggers download of the currently stored file.
 * - Updates filename/timestamp/button state in place after a successful upload.
 */

(function () {
  function formatTimestamp(isoString) {
    if (!isoString) return "";
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return isoString;
    return "Uploaded: " + date.toLocaleString();
  }

  function setStatus(el, message, type) {
    el.textContent = message;
    el.classList.remove("upload-widget__status--error", "upload-widget__status--success");
    if (type) {
      el.classList.add("upload-widget__status--" + type);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    const widget = document.getElementById("pqpr-upload-widget");
    if (!widget) return;

    const uploadUrl = widget.dataset.uploadUrl;
    const downloadUrl = widget.dataset.downloadUrl;

    const fileInput = document.getElementById("pqpr-file-input");
    const downloadBtn = document.getElementById("pqpr-download-btn");
    const filenameEl = document.getElementById("pqpr-filename");
    const timestampEl = document.getElementById("pqpr-timestamp");
    const uploadLabelEl = document.getElementById("pqpr-upload-label");
    const statusEl = document.getElementById("pqpr-upload-status");

    // Format the server-rendered initial timestamp on load.
    if (timestampEl && timestampEl.dataset.uploadedAt) {
      timestampEl.textContent = formatTimestamp(timestampEl.dataset.uploadedAt);
    }

    downloadBtn.addEventListener("click", function () {
      if (downloadBtn.disabled) return;
      window.location.href = downloadUrl;
    });

    fileInput.addEventListener("change", function () {
      const file = fileInput.files[0];
      if (!file) return;

      const formData = new FormData();
      formData.append("pqpr_file", file);

      setStatus(statusEl, "Uploading...", null);

      fetch(uploadUrl, {
        method: "POST",
        body: formData,
      })
        .then(function (response) {
          return response.json().then(function (data) {
            return { ok: response.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok || !result.data.success) {
            const message =
              (result.data && result.data.error) || "Upload failed. Please try again.";
            setStatus(statusEl, message, "error");
            return;
          }

          const meta = result.data.meta;
          filenameEl.textContent = meta.original_filename;
          filenameEl.classList.remove("upload-widget__empty");
          timestampEl.dataset.uploadedAt = meta.uploaded_at;
          timestampEl.textContent = formatTimestamp(meta.uploaded_at);
          uploadLabelEl.textContent = "Replace File";
          downloadBtn.disabled = false;

          const noDataNote = document.getElementById("pqpr-no-data-note");
          const searchPanels = document.getElementById("pqpr-search-panels");
          if (noDataNote) noDataNote.hidden = true;
          if (searchPanels) searchPanels.hidden = false;

          setStatus(statusEl, "Upload successful.", "success");
        })
        .catch(function () {
          setStatus(statusEl, "Upload failed. Please check your connection.", "error");
        })
        .finally(function () {
          fileInput.value = "";
        });
    });
  });
})();
