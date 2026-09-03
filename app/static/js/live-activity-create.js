/**
 * Live Kitting Activity - Create (step 1) page behavior.
 *
 * - Enter in Order Number moves focus to EDP Number (no submit).
 * - Enter in EDP Number triggers an AJAX lookup scoped to the selected
 *   table; exact match only, no suggestions (confirmed scope). On
 *   success, auto-fills Kit Name + hidden Kit Id and enables Next.
 *   On failure, shows an inline error and keeps Next disabled.
 * - Changing the station or EDP number after a successful lookup clears
 *   the resolved kit, so a stale kit can never be submitted for a
 *   different EDP/table than what was actually looked up.
 * - On Next click, checks whether the selected table already has a live
 *   activity (confirmed scope: checked only on submit, not as the table
 *   is selected). If busy, blocks navigation and shows which order is
 *   occupying it. This is a UX check only - the real enforcement point
 *   is the server-side re-check at finalize (race-safe).
 * - If not busy, navigates (GET-style redirect via query params) to the
 *   camera-check page - nothing is written to the database yet.
 */
document.addEventListener("DOMContentLoaded", () => {
  const page = document.querySelector(".activity-form-page");
  if (!page) return;

  const lookupUrl = page.dataset.lookupEdpUrl;
  const checkBusyUrl = page.dataset.checkBusyUrl;
  const cameraCheckUrl = page.dataset.cameraCheckUrl;

  const form = document.getElementById("activity-form");
  const tableSelect = document.getElementById("table-select");
  const orderInput = document.getElementById("order-number");
  const edpInput = document.getElementById("edp-number");
  const kitNameInput = document.getElementById("kit-name");
  const kitIdInput = document.getElementById("kit-id");
  const unitsInput = document.getElementById("units-to-pack");
  const nextButton = document.getElementById("activity-next-button");
  const errorEl = document.getElementById("activity-form-error");

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = false;
  }

  function clearError() {
    errorEl.hidden = true;
    errorEl.textContent = "";
  }

  function clearResolvedKit() {
    kitNameInput.value = "";
    kitNameInput.placeholder = "Will populate automatically...";
    kitIdInput.value = "";
    nextButton.disabled = true;
  }

  orderInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      edpInput.focus();
      edpInput.select();
    }
  });

  edpInput.addEventListener("input", clearResolvedKit);
  tableSelect.addEventListener("change", clearResolvedKit);

  edpInput.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    clearError();

    const edpValue = edpInput.value.trim();
    if (!edpValue) {
      showError("Enter an EDP number.");
      return;
    }

    kitNameInput.value = "";
    kitNameInput.placeholder = "Looking up...";
    kitIdInput.value = "";
    nextButton.disabled = true;

    let response;
    try {
      response = await fetch(lookupUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          table_id: tableSelect.value,
          edp_number: edpValue,
        }),
      });
    } catch (err) {
      kitNameInput.placeholder = "Will populate automatically...";
      showError("Could not reach the server. Check your connection and try again.");
      return;
    }

    let data;
    try {
      data = await response.json();
    } catch (err) {
      kitNameInput.placeholder = "Will populate automatically...";
      showError("Unexpected server response. Try again.");
      return;
    }

    if (!data.success) {
      kitNameInput.placeholder = "Will populate automatically...";
      showError(data.error || "EDP number not found on this station.");
      return;
    }

    kitNameInput.value = data.kit_name;
    kitIdInput.value = data.kit_id;
    nextButton.disabled = false;
    unitsInput.focus();
    unitsInput.select();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearError();

    if (!kitIdInput.value) {
      showError("Look up a valid EDP number before continuing.");
      return;
    }

    nextButton.disabled = true;
    nextButton.textContent = "Checking...";

    let busyResponse;
    try {
      busyResponse = await fetch(checkBusyUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ table_id: tableSelect.value }),
      });
    } catch (err) {
      nextButton.disabled = false;
      nextButton.textContent = "Next \u2192";
      showError("Could not reach the server. Check your connection and try again.");
      return;
    }

    let busyData;
    try {
      busyData = await busyResponse.json();
    } catch (err) {
      nextButton.disabled = false;
      nextButton.textContent = "Next \u2192";
      showError("Unexpected server response. Try again.");
      return;
    }

    if (!busyData.success) {
      nextButton.disabled = false;
      nextButton.textContent = "Next \u2192";
      showError(busyData.error || "Could not check station availability.");
      return;
    }

    if (busyData.busy) {
      nextButton.disabled = false;
      nextButton.textContent = "Next \u2192";
      const stationLabel = tableSelect.options[tableSelect.selectedIndex].text;
      showError(`${stationLabel} is already busy with order "${busyData.order_number}". Complete or stop that activity first.`);
      return;
    }

    const params = new URLSearchParams({
      table_id: tableSelect.value,
      order_number: orderInput.value.trim(),
      edp_number: edpInput.value.trim(),
      kit_id: kitIdInput.value,
      kit_name: kitNameInput.value,
      quantity_required: unitsInput.value,
    });

    window.location.href = `${cameraCheckUrl}?${params.toString()}`;
  });
});
