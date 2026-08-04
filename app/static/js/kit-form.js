/**
 * Create/Edit Kit form.
 *
 * Adds/removes part and neglect-part rows client-side, and saves the
 * whole kit (fields + parts + neglect parts) via a single AJAX POST -
 * create or update depending on whether an existing kit id is present
 * (data-kit-id on #kit-form).
 *
 * Row markup here mirrors app/templates/configuration/_part_row.html and
 * _neglect_row.html (the server renders those for prefill on edit; this
 * file renders the same structure for rows added client-side). Keep
 * both in sync if fields change.
 */

(function () {
  function partRowHtml() {
    return (
      '<tr class="part-row">' +
      '<td><input type="text" class="part-name-input" placeholder="Part name"></td>' +
      '<td><input type="number" class="part-qty-input" min="1" value="1"></td>' +
      '<td><select class="part-camera-input">' +
      '<option value="cam1">Camera 1</option>' +
      '<option value="cam2">Camera 2</option>' +
      "</select></td>" +
      '<td class="alert-config-cell">' +
      '<label><input type="checkbox" class="alert-missing-input"> Missing</label>' +
      '<label><input type="checkbox" class="alert-undercount-input"> Undercount</label>' +
      '<label><input type="checkbox" class="alert-overcount-input"> Overcount</label>' +
      "</td>" +
      '<td><input type="text" class="part-class-resemblance-input" placeholder="Optional"></td>' +
      '<td><button type="button" class="btn btn--danger part-delete-btn">Delete</button></td>' +
      "</tr>"
    );
  }

  function neglectRowHtml() {
    return (
      '<tr class="neglect-row">' +
      '<td><input type="text" class="neglect-name-input" placeholder="Part name"></td>' +
      '<td><select class="neglect-camera-input">' +
      '<option value="cam1">Camera 1</option>' +
      '<option value="cam2">Camera 2</option>' +
      "</select></td>" +
      '<td><button type="button" class="btn btn--danger neglect-delete-btn">Delete</button></td>' +
      "</tr>"
    );
  }

  function setStatus(el, message, type) {
    el.textContent = message;
    el.classList.remove("kit-form__status--error", "kit-form__status--success");
    if (type) el.classList.add("kit-form__status--" + type);
  }

  function collectParts(tableBody) {
    const parts = [];
    tableBody.querySelectorAll(".part-row").forEach(function (row) {
      parts.push({
        part_name: row.querySelector(".part-name-input").value.trim(),
        quantity_required: row.querySelector(".part-qty-input").value,
        camera: row.querySelector(".part-camera-input").value,
        alert_missing: row.querySelector(".alert-missing-input").checked,
        alert_undercount: row.querySelector(".alert-undercount-input").checked,
        alert_overcount: row.querySelector(".alert-overcount-input").checked,
        class_resemblance: row.querySelector(".part-class-resemblance-input").value.trim(),
      });
    });
    return parts;
  }

  function collectNeglectParts(tableBody) {
    const neglectParts = [];
    tableBody.querySelectorAll(".neglect-row").forEach(function (row) {
      neglectParts.push({
        part_name: row.querySelector(".neglect-name-input").value.trim(),
        camera: row.querySelector(".neglect-camera-input").value,
      });
    });
    return neglectParts;
  }

  document.addEventListener("DOMContentLoaded", function () {
    const form = document.getElementById("kit-form");
    if (!form) return;

    const createUrl = form.dataset.createUrl;
    const updateUrl = form.dataset.updateUrl;
    const listUrl = form.dataset.listUrl;
    const kitId = form.dataset.kitId;

    const kitSerialInput = document.getElementById("kit-serial-input");
    const kitNameInput = document.getElementById("kit-name-input");
    const kitEdpInput = document.getElementById("kit-edp-input");
    const partsTableBody = document.querySelector("#parts-table tbody");
    const neglectTableBody = document.querySelector("#neglect-table tbody");
    const statusEl = document.getElementById("kit-form-status");

    document.getElementById("add-part-btn").addEventListener("click", function () {
      partsTableBody.insertAdjacentHTML("beforeend", partRowHtml());
    });

    document.getElementById("add-neglect-btn").addEventListener("click", function () {
      neglectTableBody.insertAdjacentHTML("beforeend", neglectRowHtml());
    });

    partsTableBody.addEventListener("click", function (e) {
      if (e.target.classList.contains("part-delete-btn")) {
        e.target.closest("tr").remove();
      }
    });

    neglectTableBody.addEventListener("click", function (e) {
      if (e.target.classList.contains("neglect-delete-btn")) {
        e.target.closest("tr").remove();
      }
    });

    document.getElementById("save-kit-btn").addEventListener("click", function () {
      const serialNumber = kitSerialInput.value.trim();
      const kitName = kitNameInput.value.trim();
      const edpNumber = kitEdpInput.value.trim();

      if (!serialNumber || !kitName || !edpNumber) {
        setStatus(statusEl, "Serial number, kit name, and EDP number are required.", "error");
        return;
      }

      const payload = {
        serial_number: serialNumber,
        kit_name: kitName,
        edp_number: edpNumber,
        parts: collectParts(partsTableBody),
        neglect_parts: collectNeglectParts(neglectTableBody),
      };

      const url = kitId ? updateUrl : createUrl;
      setStatus(statusEl, "Saving...", null);

      fetch(url, {
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
        .then(function (result) {
          if (!result.ok || !result.data.success) {
            setStatus(
              statusEl,
              (result.data && result.data.error) || "Could not save kit.",
              "error"
            );
            return;
          }
          window.location.href = listUrl;
        })
        .catch(function () {
          setStatus(statusEl, "Could not save kit. Please check your connection.", "error");
        });
    });
  });
})();
