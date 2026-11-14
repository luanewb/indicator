import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from .binance_client import normalize_binance_symbol
from .tracker_engine import TrackerEngine

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
EXTENSION_DIR = BASE_DIR / "tradingview-extension"

engine = TrackerEngine()
ws_clients: List[WebSocket] = []


async def background_ticker_loop() -> None:
    while True:
        try:
            await engine.tick_update()
            if ws_clients:
                snapshot = engine.get_dashboard_snapshot()
                dead: List[WebSocket] = []
                for ws in list(ws_clients):
                    try:
                        await ws.send_json(snapshot)
                    except Exception:
                        dead.append(ws)
                for d in dead:
                    if d in ws_clients:
                        ws_clients.remove(d)
        except Exception as e:
            engine._log("ERROR", f"Lỗi vòng lặp cập nhật giá: {e}")
        await asyncio.sleep(1.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(background_ticker_loop())
    yield
    task.cancel()


app = FastAPI(
    title="Binance Futures Long/Short Tracker Bot v2.0.6",
    version="2.0.6",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_private_network_access_headers(request: Request, call_next):
    """Cho phép trang HTTPS TradingView gọi thẳng về http://localhost:8000 (Chrome PNA)."""
    if request.method == "OPTIONS":
        resp = JSONResponse(content={"ok": True})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "*"
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
        return resp

    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


class PlaceOrderRequest(BaseModel):
    symbol: str = "BTCUSDT"
    order_type: str = "LIMIT"
    entry: float = 0.0
    sl: float
    tp: Optional[float] = 0.0
    rr: Optional[float] = 2.0
    volume: Optional[float] = 0.0
    risk_pct: Optional[float] = 1.0
    risk_usd: Optional[float] = 0.0
    leverage: Optional[int] = 20
    sl_mode: Optional[str] = "STOP_LIMIT_BE"
    be_fee_pct: Optional[float] = 0.04
    be_price: Optional[float] = 0.0
    use_account_balance: Optional[bool] = False
    source: Optional[str] = "TradingView Button"


class ClosePositionRequest(BaseModel):
    percent: float = 100.0


class ModifyTradeRequest(BaseModel):
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    quantity: Optional[float] = None


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "2.0.6", "mode": engine.settings["trading_mode"]}


@app.get("/api/state")
async def get_state():
    return engine.get_dashboard_snapshot()


@app.post("/api/orders/place")
async def place_order(req: PlaceOrderRequest):
    try:
        trade = await engine.place_signal_order(req.model_dump())
        return {"ok": True, "trade": trade, "state": engine.get_dashboard_snapshot()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/webhook")
async def tradingview_webhook(request: Request):
    try:
        payload = await request.json()
        payload.setdefault("source", "TradingView Webhook")
        trade = await engine.place_signal_order(payload)
        return {"ok": True, "trade": trade}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/orders/{trade_id}/cancel")
async def cancel_order(trade_id: str):
    try:
        trade = await engine.cancel_pending_order(trade_id)
        return {"ok": True, "trade": trade, "state": engine.get_dashboard_snapshot()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/orders/{trade_id}/trigger-market")
async def trigger_market(trade_id: str):
    try:
        trade = await engine.trigger_pending_market(trade_id)
        return {"ok": True, "trade": trade, "state": engine.get_dashboard_snapshot()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/positions/{trade_id}/close")
async def close_position(trade_id: str, req: ClosePositionRequest):
    try:
        trade = await engine.close_active_position(trade_id, percent=req.percent)
        return {"ok": True, "trade": trade, "state": engine.get_dashboard_snapshot()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/positions/{trade_id}/breakeven")
async def move_breakeven(trade_id: str):
    try:
        trade = await engine.move_to_breakeven(trade_id)
        return {"ok": True, "trade": trade, "state": engine.get_dashboard_snapshot()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/positions/{trade_id}/reverse")
async def reverse_position(trade_id: str):
    try:
        trade = await engine.reverse_position(trade_id)
        return {"ok": True, "trade": trade, "state": engine.get_dashboard_snapshot()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/trades/{trade_id}/modify")
async def modify_trade(trade_id: str, req: ModifyTradeRequest):
    try:
        trade = await engine.modify_trade(
            trade_id,
            new_entry=req.entry,
            new_sl=req.sl,
            new_tp=req.tp,
            new_quantity=req.quantity,
        )
        return {"ok": True, "trade": trade, "state": engine.get_dashboard_snapshot()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/positions/close-all")
async def close_all():
    count = await engine.close_all_positions()
    return {"ok": True, "closed_count": count, "state": engine.get_dashboard_snapshot()}


@app.post("/api/orders/cancel-all")
async def cancel_all():
    count = await engine.cancel_all_pending()
    return {"ok": True, "canceled_count": count, "state": engine.get_dashboard_snapshot()}


@app.delete("/api/history/{trade_id}")
async def delete_history(trade_id: str):
    await engine.delete_history_item(trade_id)
    return {"ok": True, "state": engine.get_dashboard_snapshot()}


@app.post("/api/history/clear")
async def clear_history():
    count = await engine.clear_closed_history()
    return {"ok": True, "cleared_count": count, "state": engine.get_dashboard_snapshot()}


@app.get("/api/market/klines")
async def get_klines(symbol: str = "BTCUSDT", interval: str = "15m", limit: int = 150):
    sym = normalize_binance_symbol(symbol)
    klines = await engine.client.get_klines(sym, interval=interval, limit=limit)
    price = engine.live_prices.get(sym) or (klines[-1]["close"] if klines else 0.0)
    return {"symbol": sym, "interval": interval, "price": price, "klines": klines}


@app.get("/api/market/price")
async def get_price(symbol: str = "BTCUSDT"):
    sym = normalize_binance_symbol(symbol)
    price = engine.live_prices.get(sym) or await engine.client.get_symbol_price(sym)
    return {"symbol": sym, "price": price}


@app.get("/api/settings")
async def get_settings():
    return engine.get_public_settings()


@app.post("/api/settings")
async def save_settings(payload: Dict[str, Any]):
    updated = engine.update_settings(payload)
    return {"ok": True, "settings": updated, "state": engine.get_dashboard_snapshot()}


@app.get("/tv-script/long-short-tracker.user.js")
async def download_userscript():
    script_path = EXTENSION_DIR / "long-short-tracker.user.js"
    if not script_path.exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy file Userscript")
    return FileResponse(script_path, media_type="application/javascript", filename="long-short-tracker.user.js")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
    try:
        await ws.send_json(engine.get_dashboard_snapshot())
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in ws_clients:
            ws_clients.remove(ws)
    except Exception:
        if ws in ws_clients:
            ws_clients.remove(ws)


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Binance Futures Long/Short Tracker Bot v2.0.3</h1>")

