// ==UserScript==
// @name         Long/Short Tracker v2.0.6 - Nút Đặt Lệnh Binance Futures (Alt+B)
// @namespace    http://localhost:8000/
// @version      2.0.6
// @description  Đọc Entry, SL, TP, Volume từ chỉ báo Long/Short Tracker trên TradingView và gửi lệnh sang Bot Binance Futures bằng nút bấm hoặc phím tắt Alt+B.
// @author       Antigravity
// @match        *://*.tradingview.com/chart/*
// @grant        none
// ==/UserScript==

(function () {
  "use strict";
  const oldPanel = document.getElementById("ls-tracker-floating-panel");
  if (oldPanel) oldPanel.remove();

  const BOT_URL = "http://localhost:8000";
  let autoSyncEnabled = true;

  function parseTvNumber(str) {
    if (str === null || str === undefined) return NaN;
    const cleaned = String(str).replace(/−/g, "-").replace(/,/g, "").replace(/[^0-9.\-]/g, "");
    if (!cleaned || cleaned === "-" || cleaned === ".") return NaN;
    return parseFloat(cleaned);
  }

  function detectTradingViewSymbol() {
    const el = document.querySelector('#header-toolbar-symbol-search');
    if (el && el.textContent) return el.textContent.trim().toUpperCase();
    const m = document.title.match(/^([A-Z0-9._\-]+)/i);
    return m ? m[1].toUpperCase() : "BTCUSDT";
  }

  function isValidTrackerTuple(dir, entry, sl, tp) {
    if ((dir !== 1 && dir !== -1) || !(entry > 0) || !(sl > 0) || entry === sl) return false;
    if (dir === 1 && !(sl < entry)) return false;
    if (dir === -1 && !(sl > entry)) return false;
    if (tp > 0) {
      if (dir === 1 && !(tp > entry)) return false;
      if (dir === -1 && !(tp < entry)) return false;
    }
    return true;
  }

  function readIndicatorValuesFromLegend() {
    const candidates = Array.from(document.querySelectorAll('[data-name="legend-source-item"], [class*="sourcesWrapper"] > div'));
    for (const item of candidates) {
      const rawText = (item.textContent || "").replace(/−/g, "-");
      const lower = rawText.toLowerCase();
      if (!lower.includes("long/short") && !lower.includes("tracker") && !lower.includes("bot-trade")) continue;

      const matches = rawText.match(/-?\d+(?:,\d{3})*(?:\.\d+)?/g);
      if (matches && matches.length >= 9) {
        const allNums = matches.map((m) => parseTvNumber(m)).filter((n) => !isNaN(n));
        for (let i = allNums.length - 9; i >= 0; i--) {
          const w = allNums.slice(i, i + 9);
          if (isValidTrackerTuple(w[0], w[1], w[2], w[3])) {
            return {
              dir: w[0], entry: w[1], sl: w[2], tp: w[3],
              volume: w[4] || 0, risk_pct: w[5] || 1.0, risk_usd: w[6] || 0, rr: w[7] || 2.0, leverage: w[8] || 20
            };
          }
        }
      }
    }
    return null;
  }

  const box = document.createElement("div");
  box.id = "ls-tracker-floating-panel";
  box.style.cssText = "position:fixed;bottom:24px;right:24px;width:300px;background:#131722;border:1px solid #2a2e39;border-top:3px solid #14b8a6;border-radius:10px;padding:10px 12px;color:#fff;font-family:sans-serif;font-size:12px;z-index:999999;box-shadow:0 10px 25px rgba(0,0,0,0.65);";
  box.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;font-weight:700;">
      <span>⚡ TRACKER BOT v2.0.6</span>
      <a href="${BOT_URL}" target="_blank" style="color:#38bdf8;font-size:11px;text-decoration:none;">MT5 UI ↗</a>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:6px;">
      <input id="u-entry" type="number" step="any" placeholder="Entry" style="background:#0b0e14;border:1px solid #f97316;color:#fdba74;padding:4px 6px;border-radius:4px;font-weight:700;" />
      <input id="u-sl" type="number" step="any" placeholder="Stop Loss" style="background:#0b0e14;border:1px solid #f43f5e;color:#fda4af;padding:4px 6px;border-radius:4px;font-weight:700;" />
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px;">
      <input id="u-tp" type="number" step="any" placeholder="Take Profit" style="background:#0b0e14;border:1px solid #14b8a6;color:#5eead4;padding:4px 6px;border-radius:4px;font-weight:700;" />
      <input id="u-vol" type="number" step="any" placeholder="Volume" style="background:#0b0e14;border:1px solid #a855f7;color:#d8b4fe;padding:4px 6px;border-radius:4px;font-weight:700;" />
    </div>
    <button id="u-btn" style="width:100%;padding:8px;border:none;border-radius:6px;background:linear-gradient(90deg,#0d9488,#4f46e5);color:#fff;font-weight:700;cursor:pointer;">
      ⚡ ĐẶT LỆNH LIMIT (Alt+B)
    </button>
    <div id="u-msg" style="margin-top:6px;font-size:11px;color:#94a3b8;text-align:center;">Ấn Alt+B để gửi lệnh sang Bot</div>
  `;
  document.body.appendChild(box);

  setInterval(() => {
    if (!autoSyncEnabled) return;
    const d = readIndicatorValuesFromLegend();
    if (d && d.entry > 0 && d.sl > 0) {
      document.getElementById("u-entry").value = d.entry;
      document.getElementById("u-sl").value = d.sl;
      document.getElementById("u-tp").value = d.tp;
      document.getElementById("u-vol").value = d.volume;
    }
  }, 400);

  function sendOrder(orderType = "LIMIT") {
    const entry = parseFloat(document.getElementById("u-entry").value) || 0;
    const sl = parseFloat(document.getElementById("u-sl").value) || 0;
    const tp = parseFloat(document.getElementById("u-tp").value) || 0;
    const volume = parseFloat(document.getElementById("u-vol").value) || 0;
    const msg = document.getElementById("u-msg");
    if (sl <= 0 || sl === entry) {
      msg.textContent = "⚠️ Chưa có Entry / SL hợp lệ!";
      return;
    }
    fetch(BOT_URL + "/api/orders/place", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: detectTradingViewSymbol(), order_type: orderType, entry, sl, tp, volume, source: "TradingView (Alt+B)" })
    })
      .then(r => r.json())
      .then(d => {
        if (d.trade) msg.textContent = "✅ Đã đặt " + d.trade.side + " " + d.trade.symbol + " @ " + d.trade.entry;
        else msg.textContent = "❌ " + (d.detail || "Lỗi");
      })
      .catch(e => { msg.textContent = "❌ " + e.message; });
  }

  document.getElementById("u-btn").addEventListener("click", () => sendOrder("LIMIT"));
  window.addEventListener("keydown", (e) => {
    if (e.altKey && (e.key === "b" || e.key === "B")) {
      e.preventDefault();
      sendOrder("LIMIT");
    }
  });
})();
