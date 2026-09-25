(function () {
  "use strict";

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  function toast(msg) {
    var el = $("#toast");
    if (!el) return;
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.hidden = true; }, 4000);
  }

  /* ---- countdown do trade lock ---- */
  function fmtDelta(ms) {
    if (ms <= 0) return "expirado";
    var s = Math.floor(ms / 1000);
    var d = Math.floor(s / 86400);
    var h = Math.floor((s % 86400) / 3600);
    var m = Math.floor((s % 3600) / 60);
    var sec = s % 60;
    var pad = function (n) { return n < 10 ? "0" + n : "" + n; };
    return (d > 0 ? d + "d " : "") + pad(h) + ":" + pad(m) + ":" + pad(sec);
  }

  function tickCountdowns() {
    $$(".countdown[data-lockuntil]").forEach(function (el) {
      var until = Date.parse(el.dataset.lockuntil);
      if (isNaN(until)) return;
      var delta = until - Date.now();
      el.textContent = fmtDelta(delta);
    });
  }
  tickCountdowns();
  setInterval(tickCountdowns, 1000);

  /* ---- tabs trade-ups / revenda ---- */
  $$(".tab").forEach(function (tab) {
    tab.addEventListener("click", function () {
      $$(".tab").forEach(function (t) { t.classList.remove("active"); });
      tab.classList.add("active");
      $("#sec-tradeups").hidden = tab.dataset.tab !== "tradeups";
      $("#sec-resale").hidden = tab.dataset.tab !== "resale";
    });
  });
  if (new URLSearchParams(location.search).get("tab") === "resale") {
    var resaleTab = document.querySelector('.tab[data-tab="resale"]');
    if (resaleTab) resaleTab.click();
  }

  /* ---- filtros (lado do servidor, com reload) ---- */
  var reloadTimer = null;
  function reloadWithFilters() {
    clearTimeout(reloadTimer);
    reloadTimer = setTimeout(function () {
      var params = new URLSearchParams();
      var minEv = $("#min-ev") ? $("#min-ev").value.trim() : "";
      var maxCost = $("#max-cost") ? $("#max-cost").value.trim() : "";
      var robust = $("#robust-chk") ? $("#robust-chk").checked : false;
      var tab = document.querySelector(".tab.active");
      if (minEv && parseFloat(minEv) > 0) params.set("min_ev", minEv);
      if (maxCost && parseFloat(maxCost) > 0) params.set("max_cost", maxCost);
      if (robust) params.set("robust", "1");
      if (tab && tab.dataset.tab === "resale") params.set("tab", "resale");
      var qs = params.toString();
      location.href = location.pathname + (qs ? "?" + qs : "");
    }, 400);
  }
  ["#robust-chk", "#min-ev", "#max-cost"].forEach(function (sel) {
    var el = $(sel);
    if (el) {
      el.addEventListener(el.type === "checkbox" ? "change" : "input", reloadWithFilters);
    }
  });
  $$(".preset").forEach(function (btn) {
    btn.addEventListener("click", function () {
      $("#max-cost").value = btn.dataset.max;
      $$(".preset").forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      reloadWithFilters();
    });
  });

  /* ---- expansão de linhas de trade-up ---- */
  $$(".row-toggle").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var detail = btn.closest("tr").nextElementSibling;
      if (!detail || !detail.classList.contains("row-detail")) return;
      detail.hidden = !detail.hidden;
      btn.textContent = detail.hidden ? "▾" : "▴";
    });
  });

  /* ---- ações: recolher / recalcular ---- */
  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : null
    }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  $$("[data-collect]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      btn.disabled = true;
      var label = btn.textContent;
      btn.textContent = "…";
      post("/collect/" + btn.dataset.collect)
        .then(function (data) { toast("Fonte " + btn.dataset.collect + ": " + data.stored + " leituras"); })
        .catch(function () { toast("Falha ao recolher (ver logs)"); })
        .finally(function () { btn.disabled = false; btn.textContent = label; });
    });
  });

  var btnCompute = $("#btn-compute");
  if (btnCompute) {
    btnCompute.addEventListener("click", function () {
      btnCompute.disabled = true;
      var label = btnCompute.textContent;
      btnCompute.textContent = "a calcular…";
      post("/compute")
        .then(function () { toast("Oportunidades recalculadas"); setTimeout(function () { location.reload(); }, 800); })
        .catch(function () { toast("Falha ao recalcular"); })
        .finally(function () { btnCompute.disabled = false; btnCompute.textContent = label; });
    });
  }

  /* ---- IA local (LM Studio) ---- */
  $$(".ai-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      btn.disabled = true;
      var label = btn.textContent;
      btn.textContent = "…";
      post("/api/ai/trend", { name: btn.dataset.name })
        .then(function (data) { toast(data.ok ? data.comment : data.error); })
        .catch(function () { toast("IA local indisponível"); })
        .finally(function () { btn.disabled = false; btn.textContent = label; });
    });
  });

  /* ---- auto-refresh 5 min (só se o separador estiver visível) ---- */
  setInterval(function () {
    if (!document.hidden) location.reload();
  }, 300000);
})();
