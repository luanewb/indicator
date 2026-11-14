// Long/Short Tracker Bridge v2.0.6 - Nút Đặt Lệnh & Stop-Limit Chốt Hòa (Alt+B) ngay trên TradingView
(function () {
  const oldPanel = document.getElementById("ls-tracker-floating-panel");
  if (oldPanel) oldPanel.remove();
  window.__LS_TRACKER_BRIDGE_LOADED__ = true;

  const BOT_URL = "http://localhost:8000";
  let autoSyncEnabled = true;
  let isMinimized = false;

  function parseTvNumber(str) {
    if (str === null || str === undefined) return NaN;
    const cleaned = String(str)
      .replace(/−/g, "-")
      .replace(/,/g, "")
      .replace(/[^0-9.\-]/g, "");
    if (!cleaned || cleaned === "-" || cleaned === ".") return NaN;
    return parseFloat(cleaned);
  }

  function detectTradingViewSymbol() {
    const selectors = [
      '#header-toolbar-symbol-search',
      '[data-name="legend-series-item"] [class*="title"]',
      'button[class*="symbolName"]'
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && el.textContent && el.textContent.trim()) {
        return el.textContent.trim().toUpperCase();
      }
    }
    const titleMatch = document.title.match(/^([A-Z0-9._\-]+)/i);
    return titleMatch ? titleMatch[1].toUpperCase() : "BTCUSDT";
  }

  function isValidTrackerTuple(dir, entry, sl, tp) {
    if ((dir !== 1 && dir !== -1) || !(entry > 0) || !(sl > 0) || entry === sl) {
      return false;
    }
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

      if (!lower.includes("long/short") && !lower.includes("tracker") && !lower.includes("bot-trade")) {
        continue;
      }

      const leafNums = [];
      const allChildren = item.querySelectorAll("*");
      allChildren.forEach((el) => {
        if (el.children.length === 0) {
          const txt = (el.textContent || "").trim();
          if (/^[−\-]?\d+(?:,\d{3})*(?:\.\d+)?$/.test(txt)) {
            const n = parseTvNumber(txt);
            if (!isNaN(n)) leafNums.push(n);
          }
        }
      });

      if (leafNums.length >= 9) {
        const tail9 = leafNums.slice(-9);
        if (isValidTrackerTuple(tail9[0], tail9[1], tail9[2], tail9[3])) {
          return {
            dir: tail9[0],
            entry: tail9[1],
            sl: tail9[2],
            tp: tail9[3],
            volume: tail9[4] || 0,
            risk_pct: tail9[5] || 1.0,
            risk_usd: tail9[6] || 0,
            rr: tail9[7] || 2.0,
            leverage: tail9[8] || 20,
          };
        }
      }

      const matches = rawText.match(/-?\d+(?:,\d{3})*(?:\.\d+)?/g);
      if (matches && matches.length >= 9) {
        const allNums = matches.map((m) => parseTvNumber(m)).filter((n) => !isNaN(n));
        for (let i = allNums.length - 9; i >= 0; i--) {
          const w = allNums.slice(i, i + 9);
          if (isValidTrackerTuple(w[0], w[1], w[2], w[3])) {
            return {
              dir: w[0],
              entry: w[1],
              sl: w[2],
              tp: w[3],
              volume: w[4] || 0,
              risk_pct: w[5] || 1.0,
              risk_usd: w[6] || 0,
              rr: w[7] || 2.0,
              leverage: w[8] || 20,
            };
          }
        }
      }
    }
    return null;
  }

  const widget = document.createElement("div");
  widget.id = "ls-tracker-floating-panel";
  widget.style.cssText = `
    position: fixed;
    bottom: 24px;
    right: 24px;
    width: 320px;
    background: #131722;
    border: 1px solid #2a2e39;
    border-top: 3px solid #fcd535;
    border-radius: 10px;
    box-shadow: 0 12px 32px rgba(0,0,0,0.65);
    color: #e2e8f0;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 12px;
    z-index: 999999;
    user-select: none;
  `;

  widget.innerHTML = `
    <div id="lst-header" style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:#1e222d;border-radius:8px 8px 0 0;cursor:move;">
      <div style="display:flex;align-items:center;gap:6px;font-weight:700;font-size:12px;color:#fcd535;">
        <span id="lst-dot" style="width:8px;height:8px;border-radius:50%;background:#10b981;display:inline-block;"></span>
        <span>⚡ LONG/SHORT TRACKER v2.0.6</span>
      </div>
      <div style="display:flex;align-items:center;gap:6px;">
        <button id="lst-sync-now" title="Đọc lại giá từ biểu đồ ngay lập tức" style="background:#334155;border:none;color:#e2e8f0;border-radius:4px;cursor:pointer;font-size:10px;padding:2px 6px;font-weight:600;">🔄 Sync</button>
        <a href="${BOT_URL}" target="_blank" title="Mở bảng quản lý lệnh MT5 Dashboard" style="color:#38bdf8;text-decoration:none;font-size:11px;font-weight:600;">MT5 UI ↗</a>
        <button id="lst-min-btn" style="background:none;border:none;color:#94a3b8;cursor:pointer;font-size:14px;padding:0 4px;">−</button>
      </div>
    </div>

    <div id="lst-body" style="padding:10px 12px;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
        <div style="display:flex;align-items:center;gap:6px;">
          <input id="lst-symbol" type="text" value="BTCUSDT" style="width:88px;background:#0b0e14;border:1px solid #334155;border-radius:4px;color:#fff;font-weight:700;font-size:12px;padding:3px 6px;text-transform:uppercase;" />
          <span id="lst-side-badge" style="padding:2px 8px;border-radius:4px;font-weight:700;font-size:11px;background:#1e293b;color:#94a3b8;">CHỜ SL</span>
        </div>
        <label style="display:flex;align-items:center;gap:4px;font-size:11px;color:#94a3b8;cursor:pointer;" title="Tự động lấy số liệu từ chỉ báo Long/Short Tracker trên biểu đồ">
          <input id="lst-autosync" type="checkbox" checked style="accent-color:#fcd535;" />
          <span>Auto Sync</span>
        </label>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:6px;">
        <div>
          <label style="display:block;font-size:10px;color:#fb923c;margin-bottom:2px;font-weight:600;">Giá Entry</label>
          <input id="lst-entry" type="number" step="any" placeholder="Entry" style="width:100%;box-sizing:border-box;background:#0b0e14;border:1px solid #f9731666;border-radius:4px;color:#fdba74;font-weight:700;font-size:12px;padding:4px 6px;" />
        </div>
        <div>
          <label style="display:block;font-size:10px;color:#f43f5e;margin-bottom:2px;font-weight:600;">Stop Loss (SL Trigger)</label>
          <input id="lst-sl" type="number" step="any" placeholder="Stop Loss" style="width:100%;box-sizing:border-box;background:#0b0e14;border:1px solid #f43f5e66;border-radius:4px;color:#fda4af;font-weight:700;font-size:12px;padding:4px 6px;" />
        </div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:6px;">
        <div>
          <label style="display:block;font-size:10px;color:#14b8a6;margin-bottom:2px;font-weight:600;">Take Profit (TP)</label>
          <input id="lst-tp" type="number" step="any" placeholder="Take Profit" style="width:100%;box-sizing:border-box;background:#0b0e14;border:1px solid #14b8a666;border-radius:4px;color:#5eead4;font-weight:700;font-size:12px;padding:4px 6px;" />
        </div>
        <div>
          <label style="display:block;font-size:10px;color:#c084fc;margin-bottom:2px;font-weight:600;">Volume (Hoặc theo %Risk)</label>
          <input id="lst-vol" type="number" step="any" placeholder="Auto" style="width:100%;box-sizing:border-box;background:#0b0e14;border:1px solid #a855f766;border-radius:4px;color:#d8b4fe;font-weight:700;font-size:12px;padding:4px 6px;" />
        </div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px;">
        <div>
          <label style="display:block;font-size:10px;color:#94a3b8;margin-bottom:2px;">% Rủi ro (Risk %)</label>
          <input id="lst-risk-pct" type="number" step="0.1" value="1.0" style="width:100%;box-sizing:border-box;background:#0b0e14;border:1px solid #334155;border-radius:4px;color:#fff;font-size:11px;padding:3px 6px;" />
        </div>
        <div>
          <label style="display:block;font-size:10px;color:#94a3b8;margin-bottom:2px;">Hệ số R:R</label>
          <input id="lst-rr" type="number" step="0.1" value="2.0" style="width:100%;box-sizing:border-box;background:#0b0e14;border:1px solid #334155;border-radius:4px;color:#fff;font-size:11px;padding:3px 6px;" />
        </div>
      </div>

      <!-- Chế độ Stop-Limit Chốt Hòa (0.04% phí) -->
      <div style="background:#0b0e14;border:1px solid #fcd53555;border-radius:6px;padding:6px 8px;margin-bottom:9px;">
        <div style="display:flex;align-items:center;justify-content:space-between;">
          <label style="display:flex;align-items:center;gap:5px;font-size:11px;font-weight:700;color:#fcd535;cursor:pointer;" title="Khi giá chạm SL -> Tự động hủy TP và đặt lệnh Limit Chốt Hòa (cộng 0.04% phí 2 chiều)">
            <input id="lst-stoplimit-be" type="checkbox" checked style="accent-color:#fcd535;" />
            <span>🛡️ Chạm SL → Đặt Limit Chốt Hòa</span>
          </label>
          <span style="font-size:10px;color:#94a3b8;">Phí 0.04%</span>
        </div>
        <div id="lst-be-preview" style="font-size:10.5px;color:#cbd5e1;margin-top:3px;padding-left:18px;">
          Giá Chốt Hòa (BE): <b style="color:#fcd535;">--</b>
        </div>
      </div>

      <div style="display:flex;gap:6px;">
        <button id="lst-btn-limit" style="flex:2;padding:8px 6px;border:none;border-radius:6px;background:linear-gradient(90deg,#0d9488,#4f46e5);color:#fff;font-weight:700;font-size:11.5px;cursor:pointer;box-shadow:0 4px 12px rgba(20,184,166,0.3);">
          ⚡ ĐẶT LỆNH LIMIT (Alt+B)
        </button>
        <button id="lst-btn-market" title="Vào lệnh Market ngay lập tức kèm SL & TP (Alt+M)" style="flex:1;padding:8px 4px;border:1px solid #f59e0b66;border-radius:6px;background:#f59e0b22;color:#fcd34d;font-weight:700;font-size:11px;cursor:pointer;">
          🔥 MARKET
        </button>
      </div>

      <div id="lst-status-msg" style="margin-top:7px;font-size:11px;color:#94a3b8;text-align:center;min-height:15px;">
        Kéo Entry & SL trên Chart rồi bấm <b>Alt + B</b>
      </div>
    </div>
  `;

  document.body.appendChild(widget);

  const header = document.getElementById("lst-header");
  let isDragging = false, startX = 0, startY = 0, origRight = 24, origBottom = 24;
  header.addEventListener("mousedown", (e) => {
    if (e.target.tagName === "BUTTON" || e.target.tagName === "A") return;
    isDragging = true;
    startX = e.clientX;
    startY = e.clientY;
    const rect = widget.getBoundingClientRect();
    origRight = window.innerWidth - rect.right;
    origBottom = window.innerHeight - rect.bottom;
  });
  window.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    widget.style.right = Math.max(8, origRight - dx) + "px";
    widget.style.bottom = Math.max(8, origBottom - dy) + "px";
  });
  window.addEventListener("mouseup", () => { isDragging = false; });

  document.getElementById("lst-min-btn").addEventListener("click", () => {
    isMinimized = !isMinimized;
    document.getElementById("lst-body").style.display = isMinimized ? "none" : "block";
    document.getElementById("lst-min-btn").textContent = isMinimized ? "+" : "−";
  });

  document.getElementById("lst-autosync").addEventListener("change", (e) => {
    autoSyncEnabled = e.target.checked;
    if (autoSyncEnabled) syncNow(true);
  });

  document.getElementById("lst-sync-now").addEventListener("click", () => {
    autoSyncEnabled = true;
    document.getElementById("lst-autosync").checked = true;
    syncNow(true);
  });

  function updateSideBadge() {
    const entry = parseFloat(document.getElementById("lst-entry").value) || 0;
    const sl = parseFloat(document.getElementById("lst-sl").value) || 0;
    const rr = parseFloat(document.getElementById("lst-rr").value) || 2.0;
    const badge = document.getElementById("lst-side-badge");
    const bePreview = document.getElementById("lst-be-preview");

    if (entry > 0 && sl > 0 && entry !== sl) {
      const isLong = sl < entry;
      badge.textContent = isLong ? "🟢 LONG" : "🔴 SHORT";
      badge.style.background = isLong ? "rgba(20,184,166,0.2)" : "rgba(244,63,94,0.2)";
      badge.style.color = isLong ? "#5eead4" : "#fda4af";

      const bePrice = isLong ? entry * 1.0004 : entry * 0.9996;
      bePreview.innerHTML = `Giá Chốt Hòa (BE): <b style="color:#fcd535;">${Number(bePrice.toPrecision(7))}</b> <span style="color:#64748b;">(Hủy TP khi chạm ${sl})</span>`;

      if (!autoSyncEnabled) {
        const dist = Math.abs(entry - sl);
        const tp = isLong ? entry + dist * rr : entry - dist * rr;
        document.getElementById("lst-tp").value = Number(tp.toPrecision(7));
      }
    } else {
      badge.textContent = "CHỜ SL";
      badge.style.background = "#1e293b";
      badge.style.color = "#94a3b8";
      bePreview.innerHTML = `Giá Chốt Hòa (BE): <b style="color:#fcd535;">--</b>`;
    }
  }

  ["lst-entry", "lst-sl", "lst-rr"].forEach((id) => {
    document.getElementById(id).addEventListener("input", () => {
      autoSyncEnabled = false;
      document.getElementById("lst-autosync").checked = false;
      updateSideBadge();
    });
  });

  function syncNow(showFeedback = false) {
    const sym = detectTradingViewSymbol();
    if (sym) document.getElementById("lst-symbol").value = sym;

    const data = readIndicatorValuesFromLegend();
    const statusEl = document.getElementById("lst-status-msg");
    if (data && data.entry > 0 && data.sl > 0) {
      document.getElementById("lst-entry").value = data.entry;
      document.getElementById("lst-sl").value = data.sl;
      if (data.tp > 0) document.getElementById("lst-tp").value = data.tp;
      if (data.volume > 0) document.getElementById("lst-vol").value = data.volume;
      if (data.risk_pct > 0) document.getElementById("lst-risk-pct").value = data.risk_pct;
      if (data.rr > 0) document.getElementById("lst-rr").value = data.rr;
      updateSideBadge();
      if (showFeedback) {
        statusEl.innerHTML = `<span style="color:#10b981;">✅ Đã đồng bộ: Entry ${data.entry} | SL ${data.sl} | TP ${data.tp}</span>`;
      }
    } else if (showFeedback) {
      statusEl.innerHTML = `<span style="color:#f59e0b;">⚠️ Hãy bật hiển thị 'Values in status line' trên TradingView</span>`;
    }
  }

  setInterval(() => {
    if (!autoSyncEnabled) return;
    syncNow(false);
  }, 400);

  function sendOrderToBot(orderType = "LIMIT") {
    if (autoSyncEnabled) syncNow(false);

    const symbol = document.getElementById("lst-symbol").value.trim().toUpperCase() || detectTradingViewSymbol();
    const entry = parseFloat(document.getElementById("lst-entry").value) || 0;
    const sl = parseFloat(document.getElementById("lst-sl").value) || 0;
    const tp = parseFloat(document.getElementById("lst-tp").value) || 0;
    const volume = parseFloat(document.getElementById("lst-vol").value) || 0;
    const risk_pct = parseFloat(document.getElementById("lst-risk-pct").value) || 1.0;
    const rr = parseFloat(document.getElementById("lst-rr").value) || 2.0;
    const useStopLimitBE = document.getElementById("lst-stoplimit-be").checked;
    const statusEl = document.getElementById("lst-status-msg");

    if (sl <= 0 || sl === entry) {
      statusEl.innerHTML = `<span style="color:#f43f5e;font-weight:700;">⚠️ Chưa có giá Entry & SL hợp lệ!</span>`;
      return;
    }

    statusEl.innerHTML = `<span style="color:#38bdf8;">⏳ Đang gửi lệnh ${orderType} sang Bot...</span>`;
    const payload = {
      symbol,
      order_type: orderType,
      entry,
      sl,
      tp,
      volume,
      risk_pct,
      rr,
      sl_mode: useStopLimitBE ? "STOP_LIMIT_BE" : "STOP_MARKET",
      be_fee_pct: 0.04,
      source: "TradingView (Alt+B)"
    };

    if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {
      chrome.runtime.sendMessage({ type: "PLACE_ORDER", botUrl: BOT_URL, payload }, (res) => {
        if (res && res.ok && res.data && res.data.trade) {
          const t = res.data.trade;
          statusEl.innerHTML = `<span style="color:#10b981;font-weight:700;">✅ Đã đặt ${t.side} @ ${t.entry} (BE: ${t.be_price})</span>`;
        } else {
          statusEl.innerHTML = `<span style="color:#f43f5e;">❌ ${res ? res.error : "Lỗi kết nối Bot"}</span>`;
        }
      });
    } else {
      fetch(`${BOT_URL}/api/orders/place`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      })
        .then(async (r) => {
          const d = await r.json();
          if (!r.ok) throw new Error(d.detail || "Lỗi đặt lệnh");
          const t = d.trade;
          statusEl.innerHTML = `<span style="color:#10b981;font-weight:700;">✅ Đã đặt ${t.side} @ ${t.entry} (BE: ${t.be_price})</span>`;
        })
        .catch((err) => {
          statusEl.innerHTML = `<span style="color:#f43f5e;">❌ ${err.message}</span>`;
        });
    }
  }

  document.getElementById("lst-btn-limit").addEventListener("click", () => sendOrderToBot("LIMIT"));
  document.getElementById("lst-btn-market").addEventListener("click", () => sendOrderToBot("MARKET"));

  window.addEventListener("keydown", (e) => {
    if (e.altKey && (e.key === "b" || e.key === "B")) {
      e.preventDefault();
      sendOrderToBot("LIMIT");
    } else if (e.altKey && (e.key === "m" || e.key === "M")) {
      e.preventDefault();
      sendOrderToBot("MARKET");
    }
  });

  syncNow(false);
})();
