// Background Service Worker (v2.0.6) - Cầu nối gửi lệnh từ TradingView sang Bot Localhost không lo chặn CORS/HTTPS
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "PLACE_ORDER") {
    const botUrl = message.botUrl || "http://localhost:8000";
    fetch(`${botUrl}/api/orders/place`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(message.payload)
    })
      .then(async (res) => {
        const data = await res.json();
        if (!res.ok) {
          sendResponse({ ok: false, error: data.detail || "Lỗi đặt lệnh từ Bot" });
        } else {
          sendResponse({ ok: true, data });
        }
      })
      .catch((err) => {
        sendResponse({ ok: false, error: "Không kết nối được Bot tại " + botUrl + " (" + err.message + ")" });
      });
    return true; // Giữ kênh message mở cho async response
  }

  if (message.type === "CHECK_HEALTH") {
    const botUrl = message.botUrl || "http://localhost:8000";
    fetch(`${botUrl}/api/health`)
      .then((res) => res.json())
      .then((data) => sendResponse({ ok: true, data }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }
});

