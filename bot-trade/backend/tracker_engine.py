import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .binance_client import BinanceFuturesClient, normalize_binance_symbol

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TRADES_FILE = DATA_DIR / "trades_state.json"
SETTINGS_FILE = DATA_DIR / "bot_settings.json"


class TrackerEngine:
    """
    Bộ máy quản lý lệnh chuẩn Long/Short Tracker v2.0.3 kết hợp chuẩn thao tác MT5
    trên Binance Futures (hỗ trợ PAPER, TESTNET, MAINNET).
    """

    def __init__(self) -> None:
        self.settings: Dict[str, Any] = {
            "trading_mode": os.getenv("TRADING_MODE", "PAPER").upper(),
            "binance_api_key": os.getenv("BINANCE_API_KEY", ""),
            "binance_api_secret": os.getenv("BINANCE_API_SECRET", ""),
            "binance_testnet_api_key": os.getenv("BINANCE_TESTNET_API_KEY", ""),
            "binance_testnet_api_secret": os.getenv("BINANCE_TESTNET_API_SECRET", ""),
            "default_leverage": int(os.getenv("DEFAULT_LEVERAGE", "20")),
            "default_margin_type": os.getenv("DEFAULT_MARGIN_TYPE", "ISOLATED").upper(),
            "paper_balance": float(os.getenv("PAPER_INITIAL_BALANCE", "10000.0")),
            "use_account_balance_for_risk": os.getenv("USE_ACCOUNT_BALANCE_FOR_RISK", "false").lower() == "true",
            "default_risk_pct": 1.0,
            "default_rr": 2.0,
            "auto_sl_tp_on_exchange": True,
            "default_sl_mode": "STOP_LIMIT_BE",  # STOP_LIMIT_BE (Chạm SL -> Hủy TP & Đặt Limit Chốt Hòa) hoặc STOP_MARKET
            "be_fee_offset_pct": 0.04,  # 0.04% bù phí giao dịch 2 chiều khi đặt lệnh Chốt Hòa
        }
        self._load_settings()

        self.client = BinanceFuturesClient(
            mode=self.settings["trading_mode"],
            api_key=self.settings["binance_api_key"],
            api_secret=self.settings["binance_api_secret"],
            testnet_api_key=self.settings["binance_testnet_api_key"],
            testnet_api_secret=self.settings["binance_testnet_api_secret"],
        )

        self.trades: Dict[str, Dict[str, Any]] = {}
        self.live_prices: Dict[str, float] = {}
        self.account_cache: Dict[str, Any] = {
            "balance": self.settings["paper_balance"],
            "equity": self.settings["paper_balance"],
            "unrealized_pnl": 0.0,
            "used_margin": 0.0,
            "free_margin": self.settings["paper_balance"],
            "margin_level": 0.0,
            "total_floating_r": 0.0,
        }
        self.event_logs: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._load_trades()
        self._log("INFO", f"Khởi động Long/Short Tracker Bot v2.0.6 (Chế độ: {self.settings['trading_mode']})")

    def calc_be_price(self, symbol: str, side: str, entry_px: float, fee_pct: Optional[float] = None) -> float:
        """Tính mức giá Chốt Hòa (Breakeven) cộng phí 2 chiều (mặc định 0.04%)."""
        pct = float(fee_pct if fee_pct is not None else self.settings.get("be_fee_offset_pct", 0.04)) / 100.0
        if side.upper() == "LONG":
            raw_be = entry_px * (1.0 + pct)
        else:
            raw_be = entry_px * (1.0 - pct)
        return self.client.round_price(symbol, raw_be)

    def _log(self, level: str, message: str) -> None:
        entry = {
            "id": str(uuid.uuid4())[:8],
            "time": time.strftime("%H:%M:%S", time.localtime()),
            "timestamp": int(time.time() * 1000),
            "level": level,
            "message": message,
        }
        self.event_logs.insert(0, entry)
        if len(self.event_logs) > 150:
            self.event_logs = self.event_logs[:150]

    def _load_settings(self) -> None:
        if SETTINGS_FILE.exists():
            try:
                saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                self.settings.update(saved)
            except Exception:
                pass

    def _save_settings(self) -> None:
        try:
            SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _load_trades(self) -> None:
        if TRADES_FILE.exists():
            try:
                data = json.loads(TRADES_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.trades = data
            except Exception:
                pass

    def _save_trades(self) -> None:
        try:
            TRADES_FILE.write_text(json.dumps(self.trades, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def update_settings(self, new_cfg: Dict[str, Any]) -> Dict[str, Any]:
        for k, v in new_cfg.items():
            if k in self.settings and v is not None:
                self.settings[k] = v
        self.settings["trading_mode"] = str(self.settings["trading_mode"]).upper()
        self.client.mode = self.settings["trading_mode"]
        self.client.api_key = str(self.settings.get("binance_api_key", "")).strip()
        self.client.api_secret = str(self.settings.get("binance_api_secret", "")).strip()
        self.client.testnet_api_key = str(self.settings.get("binance_testnet_api_key", "")).strip()
        self.client.testnet_api_secret = str(self.settings.get("binance_testnet_api_secret", "")).strip()
        self.client._hedge_mode_cache = None
        self._save_settings()
        self._log("INFO", f"Đã cập nhật cấu hình hệ thống (Chế độ: {self.settings['trading_mode']})")
        return self.get_public_settings()

    def get_public_settings(self) -> Dict[str, Any]:
        cfg = dict(self.settings)
        # Ẩn một phần secret key khi trả về UI
        for secret_field in ["binance_api_secret", "binance_testnet_api_secret"]:
            val = cfg.get(secret_field, "")
            if val and len(val) > 8:
                cfg[secret_field + "_masked"] = val[:4] + "****" + val[-4:]
            else:
                cfg[secret_field + "_masked"] = ""
        cfg["has_credentials"] = self.client.has_valid_credentials()
        return cfg

    async def place_signal_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Nhận tín hiệu từ Nút đặt lệnh trên TradingView (Alt+B), Webhook hoặc MT5 Dashboard:
        - Tự động xác định LONG / SHORT từ Entry & SL (y hệt long-short-tracker.txt)
        - Tự động tính TP theo R:R nếu chưa truyền TP
        - Tự động tính Volume theo % Risk & làm tròn chuẩn Binance Futures
        - Đặt lệnh LIMIT (hoặc MARKET) kèm SL & TP
        """
        async with self._lock:
            await self.client.ensure_exchange_info()

            raw_symbol = str(payload.get("symbol", "BTCUSDT"))
            symbol = normalize_binance_symbol(raw_symbol)

            # Lấy giá thị trường hiện tại của cặp tiền
            mark_price = self.live_prices.get(symbol) or await self.client.get_symbol_price(symbol)
            if mark_price > 0:
                self.live_prices[symbol] = mark_price

            order_type = str(payload.get("order_type", "LIMIT")).upper()  # LIMIT hoặc MARKET
            entry_px = float(payload.get("entry") or 0.0)
            if entry_px <= 0.0 or order_type == "MARKET":
                entry_px = mark_price

            sl_px = float(payload.get("sl") or 0.0)
            if sl_px <= 0.0 or sl_px == entry_px:
                raise ValueError("Mức giá Stop Loss (SL) phải khác 0 và khác mức giá Entry!")

            # Chuẩn logic Long/Short Tracker: SL < Entry => LONG, SL > Entry => SHORT
            is_long = sl_px < entry_px
            side = "LONG" if is_long else "SHORT"
            risk_dist = abs(entry_px - sl_px)

            rr_ratio = float(payload.get("rr") or self.settings.get("default_rr", 2.0))
            tp_px = float(payload.get("tp") or 0.0)
            if tp_px <= 0.0:
                tp_px = (entry_px + risk_dist * rr_ratio) if is_long else (entry_px - risk_dist * rr_ratio)
            else:
                rr_ratio = abs(tp_px - entry_px) / risk_dist if risk_dist > 0 else rr_ratio

            # Làm tròn giá chuẩn tickSize sàn Binance Futures
            entry_px = self.client.round_price(symbol, entry_px)
            sl_px = self.client.round_price(symbol, sl_px)
            tp_px = self.client.round_price(symbol, tp_px)
            risk_dist = abs(entry_px - sl_px)
            if risk_dist <= 0:
                raise ValueError("Khoảng cách giữa Entry và SL quá nhỏ sau khi làm tròn tickSize!")

            # Tính toán Risk USD & Khối lượng (Volume)
            risk_pct = float(payload.get("risk_pct") or self.settings.get("default_risk_pct", 1.0))
            input_volume = float(payload.get("volume") or 0.0)
            input_risk_usd = float(payload.get("risk_usd") or 0.0)

            use_acct_bal = bool(payload.get("use_account_balance", self.settings.get("use_account_balance_for_risk", False)))
            base_balance = float(self.account_cache.get("balance") or self.settings.get("paper_balance", 10000.0))

            if use_acct_bal or input_volume <= 0.0:
                risk_usd = base_balance * (risk_pct / 100.0)
                raw_qty = risk_usd / risk_dist
            else:
                raw_qty = input_volume
                risk_usd = input_risk_usd if input_risk_usd > 0 else (raw_qty * risk_dist)

            quantity = self.client.round_quantity(symbol, raw_qty, mark_price=entry_px)
            actual_risk_usd = round(quantity * risk_dist, 2)
            leverage = int(payload.get("leverage") or self.settings.get("default_leverage", 20))
            source = str(payload.get("source", "TradingView"))

            sl_mode = str(payload.get("sl_mode") or self.settings.get("default_sl_mode", "STOP_LIMIT_BE")).upper()
            be_fee_pct = float(
                payload.get("be_fee_pct")
                if payload.get("be_fee_pct") is not None
                else self.settings.get("be_fee_offset_pct", 0.04)
            )
            be_price = float(payload.get("be_price") or 0.0)
            if be_price <= 0.0:
                be_price = self.calc_be_price(symbol, side, entry_px, be_fee_pct)
            else:
                be_price = self.client.round_price(symbol, be_price)

            trade_id = f"TRK-{int(time.time() * 1000) % 100000000}"
            now_ts = int(time.time() * 1000)

            trade_record: Dict[str, Any] = {
                "id": trade_id,
                "symbol": symbol,
                "raw_symbol": raw_symbol,
                "side": side,
                "order_type": order_type,
                "status": "WAITING" if order_type == "LIMIT" else "ACTIVE",
                "entry": entry_px,
                "sl": sl_px,
                "initial_sl": sl_px,
                "tp": tp_px,
                "initial_tp": tp_px,
                "sl_mode": sl_mode,
                "be_fee_pct": be_fee_pct,
                "be_price": be_price,
                "sl_triggered": False,
                "rr": round(rr_ratio, 2),
                "quantity": quantity,
                "initial_quantity": quantity,
                "risk_pct": round(risk_pct, 2),
                "risk_usd": actual_risk_usd,
                "risk_dist": risk_dist,
                "leverage": leverage,
                "mark_price": mark_price or entry_px,
                "floating_r": 0.0,
                "floating_usd": 0.0,
                "realized_usd": 0.0,
                "realized_r": 0.0,
                "mfe_r": 0.0,
                "mae_r": 0.0,
                "is_be": False,
                "source": source,
                "mode": self.settings["trading_mode"],
                "created_at": now_ts,
                "created_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "triggered_at": now_ts if order_type == "MARKET" else None,
                "closed_at": None,
                "close_reason": None,
                "exchange_entry_order_id": None,
                "exchange_sl_order_id": None,
                "exchange_tp_order_id": None,
            }

            # Nếu ở chế độ TESTNET hoặc MAINNET -> Đặt lệnh thật lên Binance Futures
            if self.settings["trading_mode"] in ("TESTNET", "MAINNET"):
                if not self.client.has_valid_credentials():
                    raise RuntimeError(
                        f"Chưa nhập API Key cho chế độ {self.settings['trading_mode']}. "
                        "Vui lòng nhập API Key trong mục Cấu hình hoặc chuyển sang chế độ PAPER."
                    )
                await self.client.set_leverage_and_margin(
                    symbol,
                    leverage=leverage,
                    margin_type=self.settings.get("default_margin_type", "ISOLATED"),
                )
                if order_type == "LIMIT":
                    ex_order = await self.client.place_limit_order(
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        price=entry_px,
                        client_order_id=trade_id,
                    )
                    trade_record["exchange_entry_order_id"] = ex_order.get("orderId")
                    ex_status = ex_order.get("status", "NEW")
                    if ex_status == "FILLED":
                        trade_record["status"] = "ACTIVE"
                        trade_record["triggered_at"] = int(time.time() * 1000)
                        await self._attach_exchange_sl_tp(trade_record)
                else:
                    ex_order = await self.client.place_market_order(
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        reduce_only=False,
                    )
                    trade_record["exchange_entry_order_id"] = ex_order.get("orderId")
                    trade_record["status"] = "ACTIVE"
                    trade_record["triggered_at"] = int(time.time() * 1000)
                    await self._attach_exchange_sl_tp(trade_record)
            else:
                # Chế độ PAPER: Kiểm tra nếu giá hiện tại đã chạm luôn mức Limit Entry
                if order_type == "MARKET":
                    trade_record["status"] = "ACTIVE"
                    trade_record["triggered_at"] = now_ts

            self.trades[trade_id] = trade_record
            self._save_trades()

            self._log(
                "SUCCESS",
                f"[{source}] Đặt lệnh {order_type} {side} {symbol} | Entry: {entry_px} | SL: {sl_px} ({sl_mode} -> BE: {be_price}) | TP: {tp_px} | Vol: {quantity}",
            )
            return trade_record

    async def _attach_exchange_sl_tp(self, trade: Dict[str, Any]) -> None:
        """Đặt lệnh SL (STOP_LIMIT_BE hoặc STOP_MARKET) và TAKE_PROFIT_MARKET (TP) lên sàn Binance Futures."""
        if self.settings["trading_mode"] not in ("TESTNET", "MAINNET"):
            return
        if not self.settings.get("auto_sl_tp_on_exchange", True):
            return

        symbol = trade["symbol"]
        # Hủy SL/TP cũ nếu có
        for oid_key in ("exchange_sl_order_id", "exchange_tp_order_id"):
            old_oid = trade.get(oid_key)
            if old_oid:
                try:
                    await self.client.cancel_order(symbol, int(old_oid))
                except Exception:
                    pass
                trade[oid_key] = None

        # Nếu đã kích hoạt trạng thái chờ hồi về Chốt Hòa (sl_triggered == True) -> Chỉ đặt lệnh Limit đóng tại be_price
        if trade.get("sl_triggered"):
            be_px = trade.get("be_price") or self.calc_be_price(symbol, trade["side"], trade["entry"], trade.get("be_fee_pct"))
            try:
                be_order = await self.client.place_reduce_limit_order(
                    symbol=symbol,
                    side=trade["side"],
                    quantity=trade["quantity"],
                    price=be_px,
                )
                trade["exchange_sl_order_id"] = be_order.get("orderId")
            except Exception as e:
                self._log("ERROR", f"Lỗi đặt lệnh Limit Chốt Hòa trên sàn cho {symbol}: {e}")
            return

        res = await self.client.place_sl_tp_orders(
            symbol=symbol,
            side=trade["side"],
            quantity=trade["quantity"],
            sl_price=trade["sl"],
            tp_price=trade["tp"],
            sl_mode=trade.get("sl_mode", "STOP_LIMIT_BE"),
            be_price=trade.get("be_price", 0.0),
        )
        if res.get("sl_order"):
            trade["exchange_sl_order_id"] = res["sl_order"].get("orderId")
        if res.get("tp_order"):
            trade["exchange_tp_order_id"] = res["tp_order"].get("orderId")

    async def _cleanup_exchange_orders(self, trade: Dict[str, Any]) -> None:
        """Tự động dọn các lệnh chờ Entry / SL / TP còn sót trên Binance Futures."""
        if self.settings["trading_mode"] not in ("TESTNET", "MAINNET"):
            return
        symbol = trade["symbol"]
        for oid_key in ("exchange_entry_order_id", "exchange_sl_order_id", "exchange_tp_order_id"):
            oid = trade.get(oid_key)
            if oid:
                try:
                    await self.client.cancel_order(symbol, int(oid))
                except Exception:
                    pass
                trade[oid_key] = None

    async def cancel_pending_order(self, trade_id: str) -> Dict[str, Any]:
        """Hủy lệnh chờ Limit (WAITING) giống nút [X] Cancel trên MT5."""
        async with self._lock:
            trade = self.trades.get(trade_id)
            if not trade:
                raise ValueError(f"Không tìm thấy lệnh {trade_id}")
            if trade["status"] != "WAITING":
                raise ValueError(f"Lệnh {trade_id} không ở trạng thái chờ (WAITING)")

            await self._cleanup_exchange_orders(trade)
            trade["status"] = "CANCELED"
            trade["closed_at"] = int(time.time() * 1000)
            trade["close_reason"] = "CANCELED"
            self._save_trades()
            self._log("WARN", f"Đã hủy lệnh chờ {trade['side']} {trade['symbol']} @ {trade['entry']} ({trade_id})")
            return trade

    async def trigger_pending_market(self, trade_id: str) -> Dict[str, Any]:
        """Khớp ngay lệnh đang WAITING theo giá Market hiện tại."""
        async with self._lock:
            trade = self.trades.get(trade_id)
            if not trade:
                raise ValueError(f"Không tìm thấy lệnh {trade_id}")
            if trade["status"] != "WAITING":
                raise ValueError("Chỉ có thể khớp nhanh cho lệnh đang ở trạng thái WAITING")

            symbol = trade["symbol"]
            mark_px = self.live_prices.get(symbol) or await self.client.get_symbol_price(symbol) or trade["entry"]
            mark_px = self.client.round_price(symbol, mark_px)

            if self.settings["trading_mode"] in ("TESTNET", "MAINNET"):
                # Hủy lệnh Limit cũ và vào lệnh Market
                if trade.get("exchange_entry_order_id"):
                    try:
                        await self.client.cancel_order(symbol, int(trade["exchange_entry_order_id"]))
                    except Exception:
                        pass
                ex_order = await self.client.place_market_order(
                    symbol=symbol,
                    side=trade["side"],
                    quantity=trade["quantity"],
                    reduce_only=False,
                )
                trade["exchange_entry_order_id"] = ex_order.get("orderId")

            trade["entry"] = mark_px
            trade["risk_dist"] = abs(mark_px - trade["sl"])
            trade["status"] = "ACTIVE"
            trade["triggered_at"] = int(time.time() * 1000)

            if self.settings["trading_mode"] in ("TESTNET", "MAINNET"):
                await self._attach_exchange_sl_tp(trade)

            self._save_trades()
            self._log("SUCCESS", f"Đã khớp lệnh Market ngay cho {trade['side']} {symbol} @ {mark_px}")
            return trade

    async def close_active_position(self, trade_id: str, percent: float = 100.0) -> Dict[str, Any]:
        """
        Đóng vị thế đang ACTIVE (Đóng 100% hoặc Partial Close 25%, 50%, 75%) giống MT5.
        """
        async with self._lock:
            trade = self.trades.get(trade_id)
            if not trade:
                raise ValueError(f"Không tìm thấy vị thế {trade_id}")
            if trade["status"] != "ACTIVE":
                raise ValueError(f"Vị thế {trade_id} không ở trạng thái ACTIVE")

            symbol = trade["symbol"]
            mark_px = self.live_prices.get(symbol) or await self.client.get_symbol_price(symbol) or trade["mark_price"]
            is_long = trade["side"] == "LONG"
            pnl_dist = (mark_px - trade["entry"]) if is_long else (trade["entry"] - mark_px)
            r_dist = trade["risk_dist"] if trade["risk_dist"] > 0 else 1.0

            if percent >= 99.9:
                close_qty = trade["quantity"]
                if self.settings["trading_mode"] in ("TESTNET", "MAINNET"):
                    await self.client.place_market_order(
                        symbol=symbol,
                        side=trade["side"],
                        quantity=close_qty,
                        reduce_only=True,
                    )
                    await self._cleanup_exchange_orders(trade)

                closed_pnl = round(pnl_dist * close_qty, 2)
                trade["realized_usd"] = round(trade.get("realized_usd", 0.0) + closed_pnl, 2)
                trade["realized_r"] = round(pnl_dist / r_dist, 2)
                trade["floating_usd"] = 0.0
                trade["floating_r"] = 0.0
                trade["status"] = "MANUAL_CLOSE"
                trade["closed_at"] = int(time.time() * 1000)
                trade["close_reason"] = "MANUAL_CLOSE"

                if self.settings["trading_mode"] == "PAPER":
                    self.settings["paper_balance"] = round(self.settings["paper_balance"] + closed_pnl, 2)
                    self._save_settings()

                self._save_trades()
                self._log(
                    "INFO",
                    f"Đã đóng toàn bộ vị thế {trade['side']} {symbol} @ {mark_px} | PnL: ${trade['realized_usd']} ({trade['realized_r']}R)",
                )
                return trade
            else:
                # Partial close (ví dụ 25%, 50%, 75%)
                raw_close_qty = trade["quantity"] * (percent / 100.0)
                close_qty = self.client.round_quantity(symbol, raw_close_qty)
                if close_qty >= trade["quantity"]:
                    close_qty = trade["quantity"]

                if self.settings["trading_mode"] in ("TESTNET", "MAINNET"):
                    await self.client.place_market_order(
                        symbol=symbol,
                        side=trade["side"],
                        quantity=close_qty,
                        reduce_only=True,
                    )

                partial_pnl = round(pnl_dist * close_qty, 2)
                trade["realized_usd"] = round(trade.get("realized_usd", 0.0) + partial_pnl, 2)
                trade["quantity"] = self.client.round_quantity(symbol, trade["quantity"] - close_qty)
                trade["risk_usd"] = round(trade["quantity"] * trade["risk_dist"], 2)

                if self.settings["trading_mode"] == "PAPER":
                    self.settings["paper_balance"] = round(self.settings["paper_balance"] + partial_pnl, 2)
                    self._save_settings()
                else:
                    await self._attach_exchange_sl_tp(trade)

                self._save_trades()
                self._log(
                    "INFO",
                    f"Đã chốt {percent:.0f}% ({close_qty}) vị thế {trade['side']} {symbol} @ {mark_px} | Đã bỏ túi: ${partial_pnl}",
                )
                return trade

    async def move_to_breakeven(self, trade_id: str) -> Dict[str, Any]:
        """Dời Stop Loss về Hòa vốn (Entry + phí sàn) chỉ bằng 1 click."""
        async with self._lock:
            trade = self.trades.get(trade_id)
            if not trade or trade["status"] != "ACTIVE":
                raise ValueError("Chỉ có thể dời SL về Hòa vốn (BE) cho vị thế đang ACTIVE")

            symbol = trade["symbol"]
            entry_px = trade["entry"]
            new_sl = self.calc_be_price(symbol, trade["side"], entry_px, trade.get("be_fee_pct"))

            trade["sl"] = new_sl
            trade["is_be"] = True

            if self.settings["trading_mode"] in ("TESTNET", "MAINNET"):
                await self._attach_exchange_sl_tp(trade)

            self._save_trades()
            self._log("SUCCESS", f"Đã dời SL về Hòa vốn (BE: {new_sl}) cho lệnh {trade['side']} {symbol}")
            return trade

    async def modify_trade(
        self,
        trade_id: str,
        new_entry: Optional[float] = None,
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None,
        new_quantity: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Chỉnh sửa Entry / SL / TP / Volume trực tiếp như Modify Order trên MT5."""
        async with self._lock:
            trade = self.trades.get(trade_id)
            if not trade:
                raise ValueError(f"Không tìm thấy lệnh {trade_id}")
            symbol = trade["symbol"]

            if trade["status"] == "WAITING" and new_entry and new_entry > 0:
                trade["entry"] = self.client.round_price(symbol, float(new_entry))

            if new_sl and new_sl > 0:
                trade["sl"] = self.client.round_price(symbol, float(new_sl))

            if new_tp and new_tp > 0:
                trade["tp"] = self.client.round_price(symbol, float(new_tp))

            if trade["status"] == "WAITING" and new_quantity and new_quantity > 0:
                trade["quantity"] = self.client.round_quantity(symbol, float(new_quantity), mark_price=trade["entry"])

            # Tính lại chiều & khoảng cách R nếu đang WAITING
            if trade["status"] == "WAITING":
                trade["side"] = "LONG" if trade["sl"] < trade["entry"] else "SHORT"
                trade["risk_dist"] = abs(trade["entry"] - trade["sl"])
                trade["risk_usd"] = round(trade["quantity"] * trade["risk_dist"], 2)
                trade["be_price"] = self.calc_be_price(symbol, trade["side"], trade["entry"], trade.get("be_fee_pct"))
                if trade["risk_dist"] > 0:
                    trade["rr"] = round(abs(trade["tp"] - trade["entry"]) / trade["risk_dist"], 2)

                if self.settings["trading_mode"] in ("TESTNET", "MAINNET"):
                    if trade.get("exchange_entry_order_id"):
                        try:
                            await self.client.cancel_order(symbol, int(trade["exchange_entry_order_id"]))
                        except Exception:
                            pass
                    ex_order = await self.client.place_limit_order(
                        symbol=symbol,
                        side=trade["side"],
                        quantity=trade["quantity"],
                        price=trade["entry"],
                        client_order_id=f"{trade['id']}-M",
                    )
                    trade["exchange_entry_order_id"] = ex_order.get("orderId")

            elif trade["status"] == "ACTIVE":
                if self.settings["trading_mode"] in ("TESTNET", "MAINNET"):
                    await self._attach_exchange_sl_tp(trade)

            self._save_trades()
            self._log(
                "INFO",
                f"Đã cập nhật lệnh {trade['symbol']} ({trade_id}) -> Entry: {trade['entry']} | SL: {trade['sl']} | TP: {trade['tp']}",
            )
            return trade

    async def reverse_position(self, trade_id: str) -> Dict[str, Any]:
        """Đảo chiều vị thế đang ACTIVE (LONG <-> SHORT) 1-click giống MT5."""
        old_trade = self.trades.get(trade_id)
        if not old_trade or old_trade["status"] != "ACTIVE":
            raise ValueError("Chỉ hỗ trợ đảo chiều vị thế đang ACTIVE")

        symbol = old_trade["symbol"]
        old_side = old_trade["side"]
        new_side = "SHORT" if old_side == "LONG" else "LONG"
        r_dist = old_trade["risk_dist"]
        rr = old_trade["rr"]
        qty = old_trade["quantity"]

        await self.close_active_position(trade_id, percent=100.0)
        mark_px = self.live_prices.get(symbol) or await self.client.get_symbol_price(symbol) or old_trade["mark_price"]
        new_sl = (mark_px - r_dist) if new_side == "LONG" else (mark_px + r_dist)
        new_tp = (mark_px + r_dist * rr) if new_side == "LONG" else (mark_px - r_dist * rr)

        return await self.place_signal_order(
            {
                "symbol": symbol,
                "order_type": "MARKET",
                "entry": mark_px,
                "sl": new_sl,
                "tp": new_tp,
                "volume": qty,
                "rr": rr,
                "leverage": old_trade.get("leverage", 20),
                "source": "MT5 Reverse",
            }
        )

    async def close_all_positions(self) -> int:
        active_ids = [tid for tid, t in self.trades.items() if t["status"] == "ACTIVE"]
        for tid in active_ids:
            try:
                await self.close_active_position(tid, percent=100.0)
            except Exception as e:
                self._log("ERROR", f"Lỗi đóng lệnh {tid}: {e}")
        return len(active_ids)

    async def cancel_all_pending(self) -> int:
        waiting_ids = [tid for tid, t in self.trades.items() if t["status"] == "WAITING"]
        for tid in waiting_ids:
            try:
                await self.cancel_pending_order(tid)
            except Exception as e:
                self._log("ERROR", f"Lỗi hủy lệnh {tid}: {e}")
        return len(waiting_ids)

    async def delete_history_item(self, trade_id: str) -> None:
        async with self._lock:
            t = self.trades.get(trade_id)
            if t and t["status"] not in ("WAITING", "ACTIVE"):
                del self.trades[trade_id]
                self._save_trades()

    async def clear_closed_history(self) -> int:
        async with self._lock:
            closed_ids = [tid for tid, t in self.trades.items() if t["status"] not in ("WAITING", "ACTIVE")]
            for tid in closed_ids:
                del self.trades[tid]
            self._save_trades()
            return len(closed_ids)

    async def tick_update(self) -> None:
        """
        Vòng lặp cập nhật giá realtime từ Binance Futures mỗi giây:
        - Kiểm tra khớp lệnh WAITING -> ACTIVE
        - Cập nhật Floating R, Floating USD, MFE (+R), MAE (-R) chuẩn Long/Short Tracker v2.0.3
        - Kiểm tra chạm HIT_TP / HIT_SL và tự động dọn lệnh thừa
        """
        await self.client.ensure_exchange_info()
        prices = await self.client.get_all_prices()
        if prices:
            self.live_prices.update(prices)

        # Nếu đang ở TESTNET / MAINNET và có API Key -> Đồng bộ số dư & trạng thái lệnh từ sàn
        exchange_open_order_ids = set()
        if self.settings["trading_mode"] in ("TESTNET", "MAINNET") and self.client.has_valid_credentials():
            try:
                acct = await self.client.get_account_summary()
                self.account_cache["balance"] = round(acct["totalWalletBalance"], 2)
                self.account_cache["equity"] = round(acct["totalMarginBalance"], 2)
                self.account_cache["unrealized_pnl"] = round(acct["totalUnrealizedProfit"], 2)
                self.account_cache["used_margin"] = round(acct["totalInitialMargin"], 2)
                self.account_cache["free_margin"] = round(acct["availableBalance"], 2)
                open_orders = await self.client.get_open_orders()
                exchange_open_order_ids = {int(o["orderId"]) for o in open_orders if "orderId" in o}
            except Exception:
                pass

        changed = False
        total_unrealized_usd = 0.0
        total_floating_r = 0.0
        total_used_margin = 0.0

        async with self._lock:
            for tid, trade in list(self.trades.items()):
                status = trade["status"]
                if status not in ("WAITING", "ACTIVE"):
                    continue

                sym = trade["symbol"]
                mark_px = self.live_prices.get(sym)
                if not mark_px or mark_px <= 0:
                    continue

                prev_px = trade.get("mark_price", mark_px)
                trade["mark_price"] = mark_px
                seg_min = min(prev_px, mark_px)
                seg_max = max(prev_px, mark_px)

                entry = trade["entry"]
                sl = trade["sl"]
                tp = trade["tp"]
                r_dist = trade["risk_dist"] if trade["risk_dist"] > 0 else abs(entry - sl)
                is_long = trade["side"] == "LONG"

                # 1. Trạng thái WAITING -> Kiểm tra khớp Entry (giống f_processSegment trong long-short-tracker.txt)
                if status == "WAITING":
                    # Kiểm tra xem đường giá cắt qua mức Entry hoặc lệnh trên sàn đã khớp
                    crossed_entry = (entry >= seg_min and entry <= seg_max) or (
                        is_long and mark_px <= entry and prev_px >= entry
                    ) or (not is_long and mark_px >= entry and prev_px <= entry)

                    ex_oid = trade.get("exchange_entry_order_id")
                    if self.settings["trading_mode"] in ("TESTNET", "MAINNET") and ex_oid and exchange_open_order_ids:
                        if int(ex_oid) not in exchange_open_order_ids and crossed_entry:
                            crossed_entry = True

                    if crossed_entry:
                        trade["status"] = "ACTIVE"
                        trade["triggered_at"] = int(time.time() * 1000)
                        trade["mfe_r"] = 0.0
                        trade["mae_r"] = 0.0
                        status = "ACTIVE"
                        changed = True
                        self._log("SUCCESS", f"⚡ Lệnh chờ {trade['side']} {sym} đã KHỚP tại Entry {entry} -> ACTIVE!")
                        if self.settings["trading_mode"] in ("TESTNET", "MAINNET"):
                            await self._attach_exchange_sl_tp(trade)

                # 2. Trạng thái ACTIVE -> Tính Floating R, MFE, MAE & Kiểm tra HIT_TP / HIT_SL / STOP_LIMIT_BE
                if status == "ACTIVE" and r_dist > 0:
                    pnl_dist = (mark_px - entry) if is_long else (entry - mark_px)
                    current_r = pnl_dist / r_dist
                    current_usd = pnl_dist * trade["quantity"]

                    trade["floating_r"] = round(current_r, 2)
                    trade["floating_usd"] = round(current_usd, 2)

                    if current_r > 0:
                        trade["mfe_r"] = round(max(trade.get("mfe_r", 0.0), current_r), 2)
                    elif current_r < 0:
                        trade["mae_r"] = round(max(trade.get("mae_r", 0.0), abs(current_r)), 2)

                    sl_mode = trade.get("sl_mode", "STOP_LIMIT_BE").upper()
                    sl_triggered = bool(trade.get("sl_triggered", False))
                    be_px = trade.get("be_price") or self.calc_be_price(sym, trade["side"], entry, trade.get("be_fee_pct"))
                    trade["be_price"] = be_px

                    # TRƯỜNG HỢP A: Đã chạm SL trước đó và đang chờ hồi về giá Chốt Hòa (be_px)
                    if sl_triggered:
                        hit_be = (mark_px >= be_px) if is_long else (mark_px <= be_px)
                        if hit_be:
                            trade["status"] = "HIT_BE"
                            trade["closed_at"] = int(time.time() * 1000)
                            trade["close_reason"] = "HIT_BE"
                            trade["realized_usd"] = 0.0
                            trade["realized_r"] = 0.0
                            trade["floating_r"] = 0.0
                            trade["floating_usd"] = 0.0
                            changed = True

                            if self.settings["trading_mode"] in ("TESTNET", "MAINNET"):
                                await self._cleanup_exchange_orders(trade)

                            self._log(
                                "SUCCESS",
                                f"⚖️ HIT BE ({be_px}): Giá đã hồi về điểm Chốt Hòa (trừ phí {trade.get('be_fee_pct', 0.04)}%), đóng lệnh {trade['side']} {sym} hòa vốn!",
                            )
                        else:
                            total_unrealized_usd += trade["floating_usd"]
                            total_floating_r += trade["floating_r"]
                            lev = max(1, int(trade.get("leverage", 20)))
                            total_used_margin += (trade["quantity"] * mark_px) / lev
                        continue

                    # TRƯỜNG HỢP B: Chưa chạm SL -> Kiểm tra chạm SL hoặc chạm TP
                    hit_sl = (mark_px <= sl) if is_long else (mark_px >= sl)
                    hit_tp = (mark_px >= tp) if is_long else (mark_px <= tp)

                    if hit_sl:
                        if sl_mode == "STOP_LIMIT_BE":
                            # KÍCH HOẠT STOP-LIMIT CHỐT HÒA:
                            # 1. Hủy lệnh TP cũ
                            # 2. Kích hoạt lệnh Limit Chốt Hòa ở mức be_px (Entry + 0.04% phí)
                            old_tp = trade["tp"]
                            trade["sl_triggered"] = True
                            trade["tp"] = be_px
                            trade["is_be"] = True
                            trade["mae_r"] = round(max(trade.get("mae_r", 0.0), 1.0), 2)
                            changed = True

                            if self.settings["trading_mode"] in ("TESTNET", "MAINNET"):
                                # Hủy lệnh TP trên sàn Binance
                                tp_oid = trade.get("exchange_tp_order_id")
                                if tp_oid:
                                    try:
                                        await self.client.cancel_order(sym, int(tp_oid))
                                    except Exception:
                                        pass
                                    trade["exchange_tp_order_id"] = None
                                # Nếu chưa có lệnh STOP-LIMIT trên sàn thì đặt trực tiếp lệnh Limit reduceOnly tại be_px
                                if not trade.get("exchange_sl_order_id"):
                                    await self._attach_exchange_sl_tp(trade)

                            self._log(
                                "WARN",
                                f"🛡️ Chạm SL ({sl}) lệnh {trade['side']} {sym} -> Đã HỦY TP ({old_tp}) & Kích hoạt Stop-Limit Chốt Hòa tại {be_px}!",
                            )
                            total_unrealized_usd += trade["floating_usd"]
                            total_floating_r += trade["floating_r"]
                            lev = max(1, int(trade.get("leverage", 20)))
                            total_used_margin += (trade["quantity"] * mark_px) / lev
                        else:
                            # Chế độ STOP_MARKET truyền thống: cắt lỗ ngay tại SL
                            trade["status"] = "HIT_SL"
                            trade["closed_at"] = int(time.time() * 1000)
                            trade["close_reason"] = "HIT_SL"
                            sl_pnl_dist = (sl - entry) if is_long else (entry - sl)
                            sl_usd = round(sl_pnl_dist * trade["quantity"], 2)
                            trade["realized_usd"] = round(trade.get("realized_usd", 0.0) + sl_usd, 2)
                            trade["realized_r"] = round(sl_pnl_dist / r_dist, 2)
                            trade["mae_r"] = max(trade.get("mae_r", 0.0), 1.0)
                            trade["floating_r"] = 0.0
                            trade["floating_usd"] = 0.0
                            changed = True

                            if self.settings["trading_mode"] == "PAPER":
                                self.settings["paper_balance"] = round(self.settings["paper_balance"] + sl_usd, 2)
                                self._save_settings()
                            else:
                                await self._cleanup_exchange_orders(trade)

                            self._log(
                                "WARN",
                                f"🛑 Chạm SL ({sl}) lệnh {trade['side']} {sym} | Kết quả: {trade['realized_r']}R (${trade['realized_usd']}) | MFE từng đạt: +{trade['mfe_r']}R",
                            )

                    elif hit_tp:
                        trade["status"] = "HIT_TP"
                        trade["closed_at"] = int(time.time() * 1000)
                        trade["close_reason"] = "HIT_TP"
                        tp_pnl_dist = (tp - entry) if is_long else (entry - tp)
                        tp_usd = round(tp_pnl_dist * trade["quantity"], 2)
                        trade["realized_usd"] = round(trade.get("realized_usd", 0.0) + tp_usd, 2)
                        trade["realized_r"] = round(tp_pnl_dist / r_dist, 2)
                        trade["mfe_r"] = round(max(trade.get("mfe_r", 0.0), trade["realized_r"]), 2)
                        trade["floating_r"] = 0.0
                        trade["floating_usd"] = 0.0
                        changed = True

                        if self.settings["trading_mode"] == "PAPER":
                            self.settings["paper_balance"] = round(self.settings["paper_balance"] + tp_usd, 2)
                            self._save_settings()
                        else:
                            await self._cleanup_exchange_orders(trade)

                        self._log(
                            "SUCCESS",
                            f"🎯 HIT TP ({tp}) lệnh {trade['side']} {sym} | Lợi nhuận: +{trade['realized_r']}R (+${trade['realized_usd']}) | Max DD: -{trade['mae_r']}R",
                        )
                    else:
                        total_unrealized_usd += trade["floating_usd"]
                        total_floating_r += trade["floating_r"]
                        lev = max(1, int(trade.get("leverage", 20)))
                        total_used_margin += (trade["quantity"] * mark_px) / lev

            if changed:
                self._save_trades()

        if self.settings["trading_mode"] == "PAPER":
            bal = float(self.settings.get("paper_balance", 10000.0))
            eq = bal + total_unrealized_usd
            free_m = max(0.0, eq - total_used_margin)
            m_level = (eq / total_used_margin * 100.0) if total_used_margin > 0 else 0.0
            self.account_cache = {
                "balance": round(bal, 2),
                "equity": round(eq, 2),
                "unrealized_pnl": round(total_unrealized_usd, 2),
                "used_margin": round(total_used_margin, 2),
                "free_margin": round(free_m, 2),
                "margin_level": round(m_level, 1),
                "total_floating_r": round(total_floating_r, 2),
            }
        else:
            self.account_cache["total_floating_r"] = round(total_floating_r, 2)

    def get_dashboard_snapshot(self) -> Dict[str, Any]:
        all_trades = sorted(self.trades.values(), key=lambda x: x.get("created_at", 0), reverse=True)
        active_positions = [t for t in all_trades if t["status"] == "ACTIVE"]
        pending_orders = [t for t in all_trades if t["status"] == "WAITING"]
        history_trades = [t for t in all_trades if t["status"] not in ("ACTIVE", "WAITING")]

        closed_with_result = [t for t in history_trades if t["status"] in ("HIT_TP", "HIT_SL", "HIT_BE", "MANUAL_CLOSE")]
        wins = [t for t in closed_with_result if t.get("realized_usd", 0.0) > 0]
        win_rate = round((len(wins) / len(closed_with_result)) * 100.0, 1) if closed_with_result else 0.0
        total_realized_usd = round(sum(t.get("realized_usd", 0.0) for t in closed_with_result), 2)
        total_realized_r = round(sum(t.get("realized_r", 0.0) for t in closed_with_result), 2)

        return {
            "version": "2.0.6",
            "mode": self.settings["trading_mode"],
            "account": self.account_cache,
            "positions": active_positions,
            "pending": pending_orders,
            "history": history_trades,
            "stats": {
                "active_count": len(active_positions),
                "pending_count": len(pending_orders),
                "history_count": len(history_trades),
                "win_rate": win_rate,
                "total_realized_usd": total_realized_usd,
                "total_realized_r": total_realized_r,
            },
            "logs": self.event_logs[:40],
        }

