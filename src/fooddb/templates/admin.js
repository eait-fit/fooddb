(function () {
  var cell = function (tr, i) { var td = tr.children[i]; return td ? (td.dataset.v || td.textContent).trim() : ""; };
  var num = function (s) { var n = parseFloat(s.replace(/[,\s]/g, "")); return isNaN(n) ? null : n; };
  document.querySelectorAll("table[data-sortable]").forEach(function (t) {
    var body = t.tBodies[0], heads = Array.from(t.tHead.rows[0].cells);
    heads.forEach(function (th, i) {
      if (th.hasAttribute("data-nosort")) return;
      th.setAttribute("data-sort", "");
      th.addEventListener("click", function () {
        var dir = th.getAttribute("data-sort") === "asc" ? "desc" : "asc";
        heads.forEach(function (o) { if (o.hasAttribute("data-sort")) o.setAttribute("data-sort", ""); });
        th.setAttribute("data-sort", dir);
        var rows = Array.from(body.rows).filter(function (r) { return r.cells.length > 1; });
        rows.sort(function (a, b) {
          var x = cell(a, i), y = cell(b, i), nx = num(x), ny = num(y);
          var c = nx !== null && ny !== null ? nx - ny : x.localeCompare(y);
          return dir === "asc" ? c : -c;
        });
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  });
  document.querySelectorAll("input[data-filter]").forEach(function (input) {
    var t = document.getElementById(input.dataset.filter);
    input.addEventListener("input", function () {
      var q = input.value.toLowerCase();
      Array.from(t.tBodies[0].rows).forEach(function (r) {
        if (r.cells.length > 1) r.hidden = q !== "" && r.textContent.toLowerCase().indexOf(q) < 0;
      });
    });
  });
})();
