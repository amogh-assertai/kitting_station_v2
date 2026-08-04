/**
 * Current Kits Configuration - list table.
 *
 * - Formats server-rendered ISO timestamps client-side (same pattern as
 *   pqpr-upload.js) and fills in row numbers.
 * - Live search (debounced, matches PQPR's 250ms pattern): case-insensitive
 *   match on kit name, EDP number, or part name. Empty query re-shows the
 *   full list. Re-renders the table body from the search response.
 * - Deletes a kit via AJAX with a confirm step. Uses event delegation on
 *   the table body so it works for both server-rendered rows and rows
 *   rendered client-side from search results.
 *
 * Row markup in kitRowHtml() mirrors app/templates/configuration/_kit_row.html
 * (the server renders that for the initial page load; this renders the
 * same structure for search results). Keep both in sync if fields change.
 */

(function () {
  const DEBOUNCE_MS = 250;

  function debounce(fn, delay) {
    let timer = null;
    return function () {
      const args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(null, args);
      }, delay);
    };
  }

  function formatTimestamp(isoString) {
    if (!isoString) return "";
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return isoString;
    return date.toLocaleString();
  }

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value === null || value === undefined ? "" : String(value);
    return div.innerHTML;
  }

  function kitRowHtml(kit, editUrlTemplate, deleteUrlTemplate) {
    const kitId = encodeURIComponent(kit.id);
    const editUrl = editUrlTemplate.replace("__KIT_ID__", kitId);
    const deleteUrl = deleteUrlTemplate.replace("__KIT_ID__", kitId);

    return (
      '<tr data-kit-id="' + escapeHtml(kit.id) + '">' +
      '<td class="kit-row-index"></td>' +
      "<td>" + escapeHtml(kit.serial_number) + "</td>" +
      "<td>" + escapeHtml(kit.kit_name) + "</td>" +
      "<td>" + escapeHtml(kit.edp_number) + "</td>" +
      "<td>" +
      escapeHtml(kit.total_parts) +
      '<span class="kits-table__sub">Cam1: ' +
      escapeHtml(kit.cam1_count) +
      " · Cam2: " +
      escapeHtml(kit.cam2_count) +
      "</span></td>" +
      '<td class="kit-updated-at" data-updated-at="' +
      escapeHtml(kit.updated_at) +
      '">' +
      escapeHtml(formatTimestamp(kit.updated_at)) +
      "</td>" +
      '<td class="kits-table__actions">' +
      '<a href="' + editUrl + '" class="btn btn--secondary">Edit</a>' +
      '<button type="button" class="btn btn--danger kit-delete-btn" data-delete-url="' +
      deleteUrl +
      '" data-kit-name="' +
      escapeHtml(kit.kit_name) +
      '">Delete</button>' +
      "</td></tr>"
    );
  }

  function renumberRows(tbody) {
    tbody.querySelectorAll("tr").forEach(function (row, i) {
      const cell = row.querySelector(".kit-row-index");
      if (cell) cell.textContent = i + 1;
    });
  }

  function formatExistingTimestamps(tbody) {
    tbody.querySelectorAll(".kit-updated-at").forEach(function (el) {
      const iso = el.dataset.updatedAt;
      if (iso) el.textContent = formatTimestamp(iso);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    const table = document.getElementById("kits-table");
    if (!table) return;

    const tbody = document.getElementById("kits-table-body");
    const emptyMessage = document.getElementById("kits-empty-message");
    const searchInput = document.getElementById("kits-search-input");
    const searchStatus = document.getElementById("kits-search-status");
    const searchUrl = table.dataset.searchUrl;
    const editUrlTemplate = table.dataset.editUrlTemplate;
    const deleteUrlTemplate = table.dataset.deleteUrlTemplate;

    // Initial server-rendered rows: format timestamps + fill row numbers.
    formatExistingTimestamps(tbody);
    renumberRows(tbody);

    function renderKits(kits) {
      if (kits.length === 0) {
        tbody.innerHTML = "";
        if (emptyMessage) {
          emptyMessage.textContent = "No kits match your search.";
          emptyMessage.hidden = false;
        }
        return;
      }
      if (emptyMessage) emptyMessage.hidden = true;
      tbody.innerHTML = kits
        .map(function (kit) {
          return kitRowHtml(kit, editUrlTemplate, deleteUrlTemplate);
        })
        .join("");
      renumberRows(tbody);
    }

    function runSearch() {
      const q = searchInput.value.trim();
      fetch(searchUrl + "?q=" + encodeURIComponent(q))
        .then(function (response) {
          return response
            .json()
            .catch(function () {
              return { success: false, results: [], error: "Unexpected server response." };
            })
            .then(function (data) {
              return { ok: response.ok, data: data };
            });
        })
        .then(function (result) {
          if (!result.ok || !result.data.success) {
            if (searchStatus) {
              searchStatus.textContent = (result.data && result.data.error) || "Search failed.";
            }
            return;
          }
          if (searchStatus) searchStatus.textContent = "";
          renderKits(result.data.results || []);
        })
        .catch(function () {
          if (searchStatus) {
            searchStatus.textContent = "Search failed. Please check your connection.";
          }
        });
    }

    if (searchInput) {
      searchInput.addEventListener("input", debounce(runSearch, DEBOUNCE_MS));
    }

    // Event delegation so delete works for rows added by search re-render too.
    tbody.addEventListener("click", function (e) {
      const btn = e.target.closest(".kit-delete-btn");
      if (!btn) return;

      const kitName = btn.dataset.kitName || "this kit";
      if (!window.confirm('Delete kit "' + kitName + '"? This cannot be undone.')) {
        return;
      }

      btn.disabled = true;

      fetch(btn.dataset.deleteUrl, { method: "POST" })
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
          if (!result.ok || !result.data.success) {
            alert((result.data && result.data.error) || "Could not delete kit.");
            btn.disabled = false;
            return;
          }
          const row = btn.closest("tr");
          if (row) row.remove();
          renumberRows(tbody);
          if (!tbody.querySelector("tr") && emptyMessage) {
            emptyMessage.textContent = 'No kits configured yet. Click "Create New Kit" to add one.';
            emptyMessage.hidden = false;
          }
        })
        .catch(function () {
          alert("Could not delete kit. Please check your connection.");
          btn.disabled = false;
        });
    });
  });
})();
