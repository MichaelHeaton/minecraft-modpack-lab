/* Search / filter + pack switcher. file:// safe. */
(function () {
  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }
  function qsa(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function normalize(s) {
    return (s || "").toLowerCase().trim();
  }

  function applyFilter() {
    var search = qs("[data-filter-search]");
    var failOnly = qs("[data-filter-fail]");
    var packOnly = qs("[data-filter-pack]");
    var q = search ? normalize(search.value) : "";
    var wantFail = failOnly && failOnly.checked;
    var wantPack = packOnly && packOnly.checked;

    qsa("[data-filter-row]").forEach(function (row) {
      var text = normalize(row.getAttribute("data-filter-text") || row.textContent);
      var isFail = row.getAttribute("data-status") === "fail";
      var isPack = row.getAttribute("data-origin") === "pack";
      var ok = true;
      if (q && text.indexOf(q) === -1) ok = false;
      if (wantFail && !isFail) ok = false;
      if (wantPack && !isPack) ok = false;
      row.hidden = !ok;
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var search = qs("[data-filter-search]");
    var failOnly = qs("[data-filter-fail]");
    var packOnly = qs("[data-filter-pack]");
    if (search) search.addEventListener("input", applyFilter);
    if (failOnly) failOnly.addEventListener("change", applyFilter);
    if (packOnly) packOnly.addEventListener("change", applyFilter);

    var sel = qs("[data-pack-switch]");
    if (sel) {
      sel.addEventListener("change", function () {
        if (sel.value) window.location.href = sel.value;
      });
    }
  });
})();
