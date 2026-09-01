/**
 * Table Settings page.
 *
 * Audio Settings table: file selection is staged locally (no upload until
 * "Save Audio Settings" is clicked) - matches the deferred-save decision
 * for this feature (unlike PQPR's immediate-upload-on-select pattern).
 * Preview plays the locally-selected (unsaved) file if one is pending,
 * otherwise the already-saved server file.
 *
 * Expected Client IP list: add/edit/delete happen against an in-memory
 * array; nothing reaches the server until "Save IP List" is clicked,
 * which replaces the whole list atomically.
 */

(function () {
  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value === null || value === undefined ? "" : String(value);
    return div.innerHTML;
  }

  function setStatus(el, message, type) {
    el.textContent = message;
    el.classList.remove("table-settings__status--error", "table-settings__status--success");
    if (type) el.classList.add("table-settings__status--" + type);
  }

  function postJson(url, payload) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (response) {
        return response
          .json()
          .catch(function () {
            return { success: false, error: "Unexpected server response." };
          })
          .then(function (data) {
            return { ok: response.ok, data: data };
          });
      })
      .catch(function () {
        return { ok: false, data: { success: false, error: "Network error." } };
      });
  }

  // --- Audio Settings ---------------------------------------------------

  function initAudioSettings() {
    const table = document.getElementById("audio-settings-table");
    if (!table) return;

    const saveUrl = table.dataset.saveUrl;
    const saveBtn = document.getElementById("save-audio-settings-btn");
    const statusEl = document.getElementById("audio-settings-status");
    const pendingFiles = {}; // slot_id -> File (selected but not yet saved)

    table.querySelectorAll(".audio-file-input").forEach(function (input) {
      input.addEventListener("change", function () {
        const row = input.closest("tr");
        const slotId = row.dataset.slotId;
        const file = input.files[0];
        if (!file) return;

        pendingFiles[slotId] = file;

        const nameEl = document.getElementById("audio-filename-" + slotId);
        nameEl.textContent = file.name + " (unsaved)";

        const previewBtn = document.getElementById("audio-preview-" + slotId);
        previewBtn.disabled = false;
      });
    });

    table.querySelectorAll(".audio-preview-btn").forEach(function (btn) {
      const row = btn.closest("tr");
      const slotId = row.dataset.slotId;
      const player = document.getElementById("audio-player-" + slotId);

      btn.addEventListener("click", function () {
        if (!player.paused && !player.ended) {
          player.pause();
          return;
        }

        const pending = pendingFiles[slotId];
        player.src = pending ? URL.createObjectURL(pending) : btn.dataset.audioUrl;
        player.play().catch(function () {
          setStatus(
            document.getElementById("audio-settings-status"),
            "Could not play this audio file.",
            "error"
          );
        });
      });

      player.addEventListener("play", function () {
        btn.innerHTML = "&#10074;&#10074; Pause";
      });
      player.addEventListener("pause", function () {
        btn.innerHTML = "&#9654; Play";
      });
      player.addEventListener("ended", function () {
        btn.innerHTML = "&#9654; Play";
      });
    });

    if (!saveBtn) return;

    saveBtn.addEventListener("click", function () {
      const formData = new FormData();

      table.querySelectorAll("tbody tr").forEach(function (row) {
        const slotId = row.dataset.slotId;
        const checked = row.querySelector('input[name="default-' + slotId + '"]:checked');
        formData.append("default_" + slotId, checked ? checked.value : "enabled");
        if (pendingFiles[slotId]) {
          formData.append("audio_" + slotId, pendingFiles[slotId]);
        }
      });

      setStatus(statusEl, "Saving...", null);
      saveBtn.disabled = true;

      fetch(saveUrl, { method: "POST", body: formData })
        .then(function (response) {
          return response
            .json()
            .catch(function () {
              return { success: false, error: "Unexpected server response." };
            })
            .then(function (data) {
              return { ok: response.ok, data: data };
            });
        })
        .then(function (result) {
          saveBtn.disabled = false;
          if (!result.ok || !result.data.success) {
            setStatus(statusEl, (result.data && result.data.error) || "Could not save.", "error");
            return;
          }

          const audioSettings = result.data.audio_settings || {};
          table.querySelectorAll("tbody tr").forEach(function (row) {
            const slotId = row.dataset.slotId;
            const slotData = audioSettings[slotId] || {};
            const nameEl = document.getElementById("audio-filename-" + slotId);
            const previewBtn = document.getElementById("audio-preview-" + slotId);
            const label = row.querySelector('label.btn[for="audio-input-' + slotId + '"]');

            if (slotData.original_filename) {
              nameEl.textContent = slotData.original_filename;
              previewBtn.disabled = false;
              if (label && label.firstChild) label.firstChild.textContent = "Replace";
            } else {
              nameEl.textContent = "No file uploaded";
            }
            delete pendingFiles[slotId];
          });

          setStatus(statusEl, "Audio settings saved.", "success");
        })
        .catch(function () {
          saveBtn.disabled = false;
          setStatus(statusEl, "Could not save. Please check your connection.", "error");
        });
    });
  }

  // --- Expected Client IP list --------------------------------------------

  function initIpList() {
    const widget = document.getElementById("ip-list-widget");
    if (!widget) return;

    const saveUrl = widget.dataset.saveUrl;
    let ips = [];
    try {
      ips = JSON.parse(widget.dataset.initialIps || "[]");
    } catch (e) {
      ips = [];
    }

    const tbody = document.getElementById("ip-list-table-body");
    const newInput = document.getElementById("ip-new-input");
    const addBtn = document.getElementById("ip-add-btn");
    const saveBtn = document.getElementById("save-ip-list-btn");
    const statusEl = document.getElementById("ip-list-status");

    function render() {
      if (ips.length === 0) {
        tbody.innerHTML =
          '<tr><td colspan="2" class="ip-list__empty">No IP addresses configured yet.</td></tr>';
        return;
      }
      tbody.innerHTML = ips
        .map(function (ip, index) {
          return (
            '<tr data-index="' + index + '">' +
            '<td><input type="text" class="ip-edit-input" value="' + escapeHtml(ip) + '"></td>' +
            '<td><button type="button" class="btn btn--danger ip-delete-btn">Delete</button></td>' +
            "</tr>"
          );
        })
        .join("");
    }

    render();

    addBtn.addEventListener("click", function () {
      const value = newInput.value.trim();
      if (!value) return;
      ips.push(value);
      newInput.value = "";
      render();
      newInput.focus();
    });

    newInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        addBtn.click();
      }
    });

    tbody.addEventListener("click", function (e) {
      const btn = e.target.closest(".ip-delete-btn");
      if (!btn) return;
      const row = btn.closest("tr");
      const index = parseInt(row.dataset.index, 10);
      ips.splice(index, 1);
      render();
    });

    tbody.addEventListener("input", function (e) {
      if (!e.target.classList.contains("ip-edit-input")) return;
      const row = e.target.closest("tr");
      const index = parseInt(row.dataset.index, 10);
      ips[index] = e.target.value;
    });

    saveBtn.addEventListener("click", function () {
      setStatus(statusEl, "Saving...", null);
      saveBtn.disabled = true;

      postJson(saveUrl, { ips: ips }).then(function (result) {
        saveBtn.disabled = false;
        if (!result.ok || !result.data.success) {
          setStatus(statusEl, (result.data && result.data.error) || "Could not save.", "error");
          return;
        }
        ips = result.data.ips || [];
        render();
        setStatus(statusEl, "IP list saved.", "success");
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initAudioSettings();
    initIpList();
  });
})();
