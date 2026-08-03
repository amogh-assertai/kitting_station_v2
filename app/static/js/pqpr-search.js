/**
 * PQPR search panels.
 *
 * Left panel: type a kit name or EDP # -> suggestions -> click one (or
 *   press Enter / click Search) -> shows that kit's component list.
 * Right panel: type a component name -> suggestions -> click one (or
 *   press Enter / click Search) -> shows every kit using it, Top 10
 *   kits flagged and listed first.
 *
 * Every fetch has explicit error handling so a server-side failure shows
 * a visible message instead of silently doing nothing.
 */

(function () {
  const DEBOUNCE_MS = 250;

  function debounce(fn, delay) {
    let timer = null;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(null, args), delay);
    };
  }

  function clearSuggestions(listEl) {
    listEl.innerHTML = "";
    listEl.hidden = true;
  }

  function renderSuggestions(listEl, items, renderLabel, onSelect, emptyMessage) {
    listEl.innerHTML = "";

    if (items.length === 0) {
      const li = document.createElement("li");
      li.className = "search-box__suggestion search-box__suggestion--empty";
      li.textContent = emptyMessage;
      listEl.appendChild(li);
      listEl.hidden = false;
      return;
    }

    items.forEach(function (item) {
      const li = document.createElement("li");
      li.className = "search-box__suggestion";
      if (item.is_top10) {
        const badge = document.createElement("span");
        badge.className = "top10-badge";
        badge.textContent = "TOP 10";
        li.appendChild(badge);
      }
      const label = document.createElement("span");
      label.textContent = renderLabel(item);
      li.appendChild(label);
      li.addEventListener("click", function () {
        onSelect(item);
        listEl.hidden = true;
      });
      listEl.appendChild(li);
    });
    listEl.hidden = false;
  }

  function fetchJson(url) {
    return fetch(url)
      .then(function (res) {
        return res
          .json()
          .catch(function () {
            return { success: false, results: [], error: "Unexpected server response." };
          })
          .then(function (data) {
            return { ok: res.ok, data: data };
          });
      })
      .catch(function () {
        return { ok: false, data: { success: false, results: [], error: "Network error." } };
      });
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function initKitSearch(panels) {
    const input = document.getElementById("kit-search-input");
    const searchBtn = document.getElementById("kit-search-btn");
    const suggestionsEl = document.getElementById("kit-suggestions");
    const detailsEl = document.getElementById("kit-details");
    const searchUrl = panels.dataset.searchKitsUrl;
    const detailsUrl = panels.dataset.kitDetailsUrl;

    function showKitDetails(kit) {
      input.value = kit.kit_name + " (" + kit.edp + ")";
      fetchJson(detailsUrl + "?edp=" + encodeURIComponent(kit.edp)).then(function (
        result
      ) {
        if (!result.ok || !result.data.success) {
          detailsEl.innerHTML =
            '<p class="details-panel__empty">' +
            escapeHtml(result.data.error || "Could not load kit details.") +
            "</p>";
          return;
        }
        renderKitDetails(result.data);
      });
    }

    function renderKitDetails(data) {
      let html = "";
      if (data.is_top10) {
        html += '<span class="top10-badge top10-badge--inline">TOP 10</span>';
      }
      html +=
        '<h3 class="details-panel__heading">' +
        escapeHtml(data.kit_name) +
        ' <span class="details-panel__subheading">EDP ' +
        escapeHtml(data.edp) +
        "</span></h3>";

      if (data.components.length === 0) {
        html +=
          '<p class="details-panel__empty">No components listed for this kit.</p>';
      } else {
        html +=
          '<table class="details-table"><thead><tr><th>Component</th><th>Qty</th></tr></thead><tbody>';
        data.components.forEach(function (c) {
          html +=
            "<tr><td>" +
            escapeHtml(c.name) +
            "</td><td>" +
            escapeHtml(String(c.qty)) +
            "</td></tr>";
        });
        html += "</tbody></table>";
      }
      detailsEl.innerHTML = html;
    }

    function runSearch(immediate) {
      const q = input.value.trim();
      if (q.length === 0) {
        clearSuggestions(suggestionsEl);
        return;
      }
      fetchJson(searchUrl + "?q=" + encodeURIComponent(q)).then(function (result) {
        if (!result.ok) {
          detailsEl.innerHTML =
            '<p class="details-panel__empty">' +
            escapeHtml(result.data.error || "Search failed.") +
            "</p>";
          return;
        }
        const results = result.data.results || [];

        // On an explicit search (button/Enter): jump straight to the
        // single match, or say plainly that nothing matched.
        if (immediate) {
          if (results.length === 1) {
            showKitDetails(results[0]);
            suggestionsEl.hidden = true;
            return;
          }
          if (results.length === 0) {
            detailsEl.innerHTML =
              '<p class="details-panel__empty">Kit name/EDP "' +
              escapeHtml(q) +
              '" not present in the uploaded PQPR file.</p>';
          }
        }

        renderSuggestions(
          suggestionsEl,
          results,
          function (item) {
            return item.kit_name + " (" + item.edp + ")";
          },
          showKitDetails,
          'No matching kit for "' + q + '".'
        );
      });
    }

    input.addEventListener(
      "input",
      debounce(function () {
        runSearch(false);
      }, DEBOUNCE_MS)
    );

    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        runSearch(true);
      }
    });

    searchBtn.addEventListener("click", function () {
      runSearch(true);
    });

    document.addEventListener("click", function (e) {
      if (!suggestionsEl.contains(e.target) && e.target !== input) {
        suggestionsEl.hidden = true;
      }
    });
  }

  function initComponentSearch(panels) {
    const input = document.getElementById("component-search-input");
    const searchBtn = document.getElementById("component-search-btn");
    const suggestionsEl = document.getElementById("component-suggestions");
    const detailsEl = document.getElementById("component-details");
    const searchUrl = panels.dataset.searchComponentsUrl;
    const detailsUrl = panels.dataset.componentDetailsUrl;

    function showComponentDetails(componentName) {
      input.value = componentName;
      fetchJson(
        detailsUrl + "?component=" + encodeURIComponent(componentName)
      ).then(function (result) {
        if (!result.ok || !result.data.success) {
          detailsEl.innerHTML =
            '<p class="details-panel__empty">' +
            escapeHtml(result.data.error || "Could not load component details.") +
            "</p>";
          return;
        }
        renderComponentDetails(result.data);
      });
    }

    function renderComponentDetails(data) {
      let html = '<h3 class="details-panel__heading">' + escapeHtml(data.component) + "</h3>";

      if (data.kits.length === 0) {
        html +=
          '<p class="details-panel__empty">This component is not used in any kit.</p>';
      } else {
        html +=
          '<table class="details-table"><thead><tr><th></th><th>Kit</th><th>EDP</th><th>Qty</th></tr></thead><tbody>';
        data.kits.forEach(function (k) {
          html +=
            "<tr><td>" +
            (k.is_top10 ? '<span class="top10-badge">TOP 10</span>' : "") +
            "</td><td>" +
            escapeHtml(k.kit_name) +
            "</td><td>" +
            escapeHtml(k.edp) +
            "</td><td>" +
            escapeHtml(String(k.qty)) +
            "</td></tr>";
        });
        html += "</tbody></table>";
      }
      detailsEl.innerHTML = html;
    }

    function runSearch(immediate) {
      const q = input.value.trim();
      if (q.length === 0) {
        clearSuggestions(suggestionsEl);
        return;
      }
      fetchJson(searchUrl + "?q=" + encodeURIComponent(q)).then(function (result) {
        if (!result.ok) {
          detailsEl.innerHTML =
            '<p class="details-panel__empty">' +
            escapeHtml(result.data.error || "Search failed.") +
            "</p>";
          return;
        }
        const results = result.data.results || [];

        if (immediate) {
          if (results.length === 1) {
            showComponentDetails(results[0]);
            suggestionsEl.hidden = true;
            return;
          }
          if (results.length === 0) {
            detailsEl.innerHTML =
              '<p class="details-panel__empty">Component "' +
              escapeHtml(q) +
              '" not present in the uploaded PQPR file.</p>';
          }
        }

        renderSuggestions(
          suggestionsEl,
          results.map(function (name) {
            return { name: name };
          }),
          function (item) {
            return item.name;
          },
          function (item) {
            showComponentDetails(item.name);
          },
          'No matching component for "' + q + '".'
        );
      });
    }

    input.addEventListener(
      "input",
      debounce(function () {
        runSearch(false);
      }, DEBOUNCE_MS)
    );

    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        runSearch(true);
      }
    });

    searchBtn.addEventListener("click", function () {
      runSearch(true);
    });

    document.addEventListener("click", function (e) {
      if (!suggestionsEl.contains(e.target) && e.target !== input) {
        suggestionsEl.hidden = true;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    const panels = document.getElementById("pqpr-search-panels");
    if (!panels) return;
    initKitSearch(panels);
    initComponentSearch(panels);
  });
})();
