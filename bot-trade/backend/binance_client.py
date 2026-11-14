import hashlib
import hmac
import math
import time
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
import httpx


def normalize_binance_symbol(raw_symbol: str) -> str:
    """
    Chuẩn hóa mã cặp tiền từ TradingView sang chuẩn Binance Futures USD-M.
    Ví dụ:
      - 'BINANCE:BTCUSDT.P' -> 'BTCUSDT'
      - 'BTCUSDT.P'         -> 'BTCUSDT'
      - 'BTCUSD'            -> 'BTCUSDT'
      - 'BTC'               -> 'BTCUSDT'
    """
    if not raw_symbol:
        return "BTCUSDT"
    s = raw_symbol.strip().upper()
    if ":" in s:
        s = s.split(":")[-1]
    for suffix in [".P", "-PERP", "PERP", ".PERP"]:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    s = s.replace("/", "").replace("-", "").replace("_", "")
    if s.endswith("USD") and not s.endswith("USDT") and not s.endswith("BUSD") and not s.endswith("USDC"):
        s = s[:-3] + "USDT"
    elif not any(s.endswith(q) for q in ["USDT", "USDC", "BUSD"]):
        s = s + "USDT"
    return s


class BinanceFuturesClient:
    MAINNET_URL = "https://fapi.binance.com"
    TESTNET_URL = "https://testnet.binancefuture.com"

    def __init__(
        self,
        mode: str = "PAPER",
        api_key: str = "",
        api_secret: str = "",
        testnet_api_key: str = "",
        testnet_api_secret: str = "",
    ):
        self.mode = mode.upper()  # PAPER, TESTNET, MAINNET
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.testnet_api_key = testnet_api_key.strip()
        self.testnet_api_secret = testnet_api_secret.strip()

        self._symbol_filters: Dict[str, Dict[str, Any]] = {}
        self._last_exchange_info_ts: float = 0.0
        self._time_offset_ms: int = 0
        self._hedge_mode_cache: Optional[bool] = None

    @property
    def base_url(self) -> str:
        if self.mode == "TESTNET":
            return self.TESTNET_URL
        return self.MAINNET_URL

    @property
    def active_api_key(self) -> str:
        if self.mode == "TESTNET":
            return self.testnet_api_key
        return self.api_key

    @property
    def active_api_secret(self) -> str:
        if self.mode == "TESTNET":
            return self.testnet_api_secret
        return self.api_secret

    def has_valid_credentials(self) -> bool:
        if self.mode == "PAPER":
            return True
        return bool(self.active_api_key and self.active_api_secret)

    def _sign_params(self, params: Dict[str, Any]) -> str:
        clean_params = {k: v for k, v in params.items() if v is not None}
        clean_params["timestamp"] = int(time.time() * 1000) + self._time_offset_ms
        clean_params.setdefault("recvWindow", 10000)
        query_string = urlencode(clean_params)
        signature = hmac.new(
            self.active_api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{query_string}&signature={signature}"

    async def sync_server_time(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(f"{self.base_url}/fapi/v1/time")
                if resp.status_code == 200:
                    server_time = resp.json().get("serverTime", int(time.time() * 1000))
                    self._time_offset_ms = int(server_time - int(time.time() * 1000))
        except Exception:
            pass

    async def ensure_exchange_info(self) -> None:
        now = time.time()
        if self._symbol_filters and (now - self._last_exchange_info_ts) < 3600:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.MAINNET_URL}/fapi/v1/exchangeInfo")
                if resp.status_code == 200:
                    data = resp.json()
                    for sym_info in data.get("symbols", []):
                        sym = sym_info.get("symbol")
                        tick_size = "0.01"
                        step_size = "0.001"
                        min_qty = 0.001
                        min_notional = 5.0
                        for f in sym_info.get("filters", []):
                            ft = f.get("filterType")
                            if ft == "PRICE_FILTER":
                                tick_size = f.get("tickSize", "0.01")
                            elif ft == "LOT_SIZE":
                                step_size = f.get("stepSize", "0.001")
                                min_qty = float(f.get("minQty", 0.001))
                            elif ft == "MIN_NOTIONAL":
                                min_notional = float(f.get("notional", 5.0))
                        self._symbol_filters[sym] = {
                            "tickSize": tick_size,
                            "stepSize": step_size,
                            "minQty": min_qty,
                            "minNotional": min_notional,
                            "pricePrecision": sym_info.get("pricePrecision", 2),
                            "quantityPrecision": sym_info.get("quantityPrecision", 3),
                        }
                    self._last_exchange_info_ts = now
        except Exception:
            pass

    def round_price(self, symbol: str, price: float) -> float:
        if price <= 0:
            return 0.0
        info = self._symbol_filters.get(symbol)
        if not info:
            return round(price, 4)
        tick = Decimal(str(info["tickSize"])).normalize()
        d_price = Decimal(str(price))
        rounded = (d_price / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick
        return float(rounded)

    def round_quantity(self, symbol: str, qty: float, mark_price: float = 0.0) -> float:
        if qty <= 0:
            return 0.0
        info = self._symbol_filters.get(symbol)
        if not info:
            return round(qty, 3)
        step = Decimal(str(info["stepSize"])).normalize()
        min_qty = Decimal(str(info["minQty"]))
        d_qty = Decimal(str(qty))
        rounded = (d_qty / step).quantize(Decimal("1"), rounding=ROUND_DOWN) * step
        if rounded < min_qty:
            rounded = min_qty
        # Đảm bảo đạt minNotional (thường >= 5 USDT trên Binance Futures)
        if mark_price > 0:
            min_notional = float(info.get("minNotional", 5.0))
            if float(rounded) * mark_price < min_notional:
                needed = Decimal(str((min_notional * 1.02) / mark_price))
                rounded = ((needed / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * step
        return float(rounded)

    async def get_all_prices(self) -> Dict[str, float]:
        """Lấy giá hiện tại của toàn bộ cặp tiền trên Binance Futures."""
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(f"{self.MAINNET_URL}/fapi/v1/ticker/price")
                if resp.status_code == 200:
                    return {item["symbol"]: float(item["price"]) for item in resp.json()}
        except Exception:
            pass
        return {}

    async def get_symbol_price(self, symbol: str) -> float:
        sym = normalize_binance_symbol(symbol)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self.MAINNET_URL}/fapi/v1/ticker/price",
                    params={"symbol": sym},
                )
                if resp.status_code == 200:
                    return float(resp.json()["price"])
        except Exception:
            pass
        return 0.0

    async def get_klines(self, symbol: str, interval: str = "15m", limit: int = 150) -> List[Dict[str, Any]]:
        sym = normalize_binance_symbol(symbol)
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    f"{self.MAINNET_URL}/fapi/v1/klines",
                    params={"symbol": sym, "interval": interval, "limit": limit},
                )
                if resp.status_code == 200:
                    raw = resp.json()
                    return [
                        {
                            "time": int(k[0] // 1000),
                            "open": float(k[1]),
                            "high": float(k[2]),
                            "low": float(k[3]),
                            "close": float(k[4]),
                            "volume": float(k[5]),
                        }
                        for k in raw
                    ]
        except Exception:
            pass
        return []

    async def _signed_request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if not self.has_valid_credentials():
            raise RuntimeError(f"Chưa cấu hình API Key & Secret cho chế độ {self.mode}")
        if self._time_offset_ms == 0:
            await self.sync_server_time()

        signed_qs = self._sign_params(params or {})
        url = f"{self.base_url}{path}?{signed_qs}"
        headers = {"X-MBX-APIKEY": self.active_api_key}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, url, headers=headers)
            if resp.status_code >= 400:
                try:
                    err_json = resp.json()
                    msg = err_json.get("msg", resp.text)
                    code = err_json.get("code", resp.status_code)
                    raise RuntimeError(f"Binance API Error [{code}]: {msg}")
                except ValueError:
                    raise RuntimeError(f"Binance HTTP {resp.status_code}: {resp.text}")
            return resp.json()

    async def is_hedge_mode(self) -> bool:
        if self._hedge_mode_cache is not None:
            return self._hedge_mode_cache
        try:
            res = await self._signed_request("GET", "/fapi/v1/positionSide/dual")
            self._hedge_mode_cache = bool(res.get("dualSidePosition", False))
            return self._hedge_mode_cache
        except Exception:
            return False

    async def get_account_summary(self) -> Dict[str, Any]:
        data = await self._signed_request("GET", "/fapi/v2/account")
        return {
            "totalWalletBalance": float(data.get("totalWalletBalance", 0.0)),
            "totalUnrealizedProfit": float(data.get("totalUnrealizedProfit", 0.0)),
            "totalMarginBalance": float(data.get("totalMarginBalance", 0.0)),
            "availableBalance": float(data.get("availableBalance", 0.0)),
            "totalInitialMargin": float(data.get("totalInitialMargin", 0.0)),
            "totalMaintMargin": float(data.get("totalMaintMargin", 0.0)),
            "positions": data.get("positions", []),
        }

    async def set_leverage_and_margin(self, symbol: str, leverage: int = 20, margin_type: str = "ISOLATED") -> None:
        sym = normalize_binance_symbol(symbol)
        try:
            await self._signed_request(
                "POST",
                "/fapi/v1/marginType",
                {"symbol": sym, "marginType": margin_type.upper()},
            )
        except Exception:
            # Có thể đã ở sẵn chế độ marginType đó
            pass
        try:
            await self._signed_request(
                "POST",
                "/fapi/v1/leverage",
                {"symbol": sym, "leverage": int(leverage)},
            )
        except Exception:
            pass

    async def place_limit_order(
        self,
        symbol: str,
        side: str,  # "LONG" hoặc "SHORT"
        quantity: float,
        price: float,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        sym = normalize_binance_symbol(symbol)
        hedge = await self.is_hedge_mode()
        order_side = "BUY" if side.upper() == "LONG" else "SELL"
        pos_side = ("LONG" if side.upper() == "LONG" else "SHORT") if hedge else "BOTH"

        params: Dict[str, Any] = {
            "symbol": sym,
            "side": order_side,
            "positionSide": pos_side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": quantity,
            "price": price,
        }
        if client_order_id:
            params["newClientOrderId"] = client_order_id

        return await self._signed_request("POST", "/fapi/v1/order", params)

    async def place_market_order(
        self,
        symbol: str,
        side: str,  # "LONG" hoặc "SHORT" (vào lệnh)
        quantity: float,
        reduce_only: bool = False,
    ) -> Dict[str, Any]:
        sym = normalize_binance_symbol(symbol)
        hedge = await self.is_hedge_mode()
        if not reduce_only:
            order_side = "BUY" if side.upper() == "LONG" else "SELL"
            pos_side = ("LONG" if side.upper() == "LONG" else "SHORT") if hedge else "BOTH"
        else:
            # Đóng vị thế của chiều side
            order_side = "SELL" if side.upper() == "LONG" else "BUY"
            pos_side = ("LONG" if side.upper() == "LONG" else "SHORT") if hedge else "BOTH"

        params: Dict[str, Any] = {
            "symbol": sym,
            "side": order_side,
            "positionSide": pos_side,
            "type": "MARKET",
            "quantity": quantity,
        }
        if reduce_only and not hedge:
            params["reduceOnly"] = "true"

        return await self._signed_request("POST", "/fapi/v1/order", params)

    async def place_reduce_limit_order(
        self,
        symbol: str,
        side: str,  # Chiều của vị thế gốc: "LONG" hoặc "SHORT"
        quantity: float,
        price: float,
    ) -> Dict[str, Any]:
        """Đặt lệnh LIMIT đóng vị thế (chốt hòa / chốt lời reduceOnly) trên Binance Futures."""
        sym = normalize_binance_symbol(symbol)
        hedge = await self.is_hedge_mode()
        close_side = "SELL" if side.upper() == "LONG" else "BUY"
        pos_side = ("LONG" if side.upper() == "LONG" else "SHORT") if hedge else "BOTH"

        params: Dict[str, Any] = {
            "symbol": sym,
            "side": close_side,
            "positionSide": pos_side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": quantity,
            "price": price,
        }
        if not hedge:
            params["reduceOnly"] = "true"
        return await self._signed_request("POST", "/fapi/v1/order", params)

    async def place_sl_tp_orders(
        self,
        symbol: str,
        side: str,  # Chiều của vị thế gốc: "LONG" hoặc "SHORT"
        quantity: float,
        sl_price: float,
        tp_price: float,
        sl_mode: str = "STOP_LIMIT_BE",
        be_price: float = 0.0,
    ) -> Dict[str, Any]:
        sym = normalize_binance_symbol(symbol)
        hedge = await self.is_hedge_mode()
        close_side = "SELL" if side.upper() == "LONG" else "BUY"
        pos_side = ("LONG" if side.upper() == "LONG" else "SHORT") if hedge else "BOTH"

        results: Dict[str, Any] = {"sl_order": None, "tp_order": None}

        if sl_price > 0:
            if sl_mode.upper() == "STOP_LIMIT_BE" and be_price > 0:
                # Đặt lệnh STOP-LIMIT trực tiếp trên Binance:
                # Khi giá chạm stopPrice (SL), sàn tự kích hoạt lệnh LIMIT đóng tại be_price (Chốt Hòa)
                sl_params: Dict[str, Any] = {
                    "symbol": sym,
                    "side": close_side,
                    "positionSide": pos_side,
                    "type": "STOP",
                    "timeInForce": "GTC",
                    "stopPrice": sl_price,
                    "price": be_price,
                    "quantity": quantity,
                    "workingType": "MARK_PRICE",
                }
            else:
                sl_params = {
                    "symbol": sym,
                    "side": close_side,
                    "positionSide": pos_side,
                    "type": "STOP_MARKET",
                    "stopPrice": sl_price,
                    "quantity": quantity,
                    "workingType": "MARK_PRICE",
                }
            if not hedge:
                sl_params["reduceOnly"] = "true"
            try:
                results["sl_order"] = await self._signed_request("POST", "/fapi/v1/order", sl_params)
            except Exception as e:
                results["sl_error"] = str(e)

        if tp_price > 0:
            tp_params: Dict[str, Any] = {
                "symbol": sym,
                "side": close_side,
                "positionSide": pos_side,
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": tp_price,
                "quantity": quantity,
                "workingType": "MARK_PRICE",
            }
            if not hedge:
                tp_params["reduceOnly"] = "true"
            try:
                results["tp_order"] = await self._signed_request("POST", "/fapi/v1/order", tp_params)
            except Exception as e:
                results["tp_error"] = str(e)

        return results

    async def cancel_order(self, symbol: str, order_id: int) -> Any:
        sym = normalize_binance_symbol(symbol)
        return await self._signed_request(
            "DELETE",
            "/fapi/v1/order",
            {"symbol": sym, "orderId": order_id},
        )

    async def cancel_all_orders(self, symbol: str) -> Any:
        sym = normalize_binance_symbol(symbol)
        return await self._signed_request(
            "DELETE",
            "/fapi/v1/allOpenOrders",
            {"symbol": sym},
        )

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if symbol:
            params["symbol"] = normalize_binance_symbol(symbol)
        return await self._signed_request("GET", "/fapi/v1/openOrders", params)

