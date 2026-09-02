"""
Thin wrapper around the DhanHQ v2 REST API.

Only the endpoints this app needs are implemented:
  - Instrument master CSV (F&O universe)
  - Expiry list (per underlying)
  - Option chain (per underlying + expiry)
  - Historical daily candles (EOD spot on a given date)
  - Market quote / LTP (live spot during the trading session)

Every method raises DhanApiError on a non-2xx response or malformed payload,
rather than silently returning None/zero -- callers must not substitute
guessed data for a failed API call (spec Section 41).
"""
from __future__ import annotations

import time
from typing import Any

import requests

from app import config
from app.data.dhan_constants import INSTRUMENT_MASTER_DETAILED_URL

BASE_URL = "https://api.dhan.co/v2"


class DhanApiError(RuntimeError):
    pass


class DhanClient:
    def __init__(self, client_id: str | None = None, access_token: str | None = None):
        self.client_id = client_id or config.DHAN_CLIENT_ID
        self.access_token = access_token or config.DHAN_ACCESS_TOKEN
        if not self.client_id or not self.access_token:
            raise DhanApiError(
                "Missing DhanHQ credentials. Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env"
            )
        self._session = requests.Session()
        self._session.headers.update(
            {
                "access-token": self.access_token,
                "client-id": self.client_id,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        self._last_optionchain_call = 0.0
        self._last_marketfeed_call = 0.0

    def _post(self, path: str, payload: dict[str, Any], _retry: int = 0) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        resp = self._session.post(url, json=payload, timeout=30)
        if resp.status_code == 429 and _retry < 3:
            time.sleep(2.0 * (_retry + 1))
            return self._post(path, payload, _retry=_retry + 1)
        if resp.status_code != 200:
            hint = ""
            if "DH-907" in resp.text or "DH-905" in resp.text:
                hint = (
                    " [Known DhanHQ-side /charts/historical instability (error DH-905/DH-907) -- "
                    "not a request-formatting bug here; this exact call can fail intermittently "
                    "even with correct parameters. Retry later or check Dhan API status.]"
                )
            raise DhanApiError(
                f"POST {path} failed [{resp.status_code}]: {resp.text[:500]}{hint}"
            )
        try:
            body = resp.json()
        except ValueError as e:
            raise DhanApiError(f"POST {path} returned non-JSON body: {resp.text[:200]}") from e
        if isinstance(body, dict) and body.get("status") == "failure":
            raise DhanApiError(f"POST {path} API failure: {body}")
        return body

    # ------------------------------------------------------------------
    # Instrument master
    # ------------------------------------------------------------------
    def download_instrument_master_csv(self, dest_path: str) -> str:
        resp = requests.get(INSTRUMENT_MASTER_DETAILED_URL, timeout=120)
        if resp.status_code != 200:
            raise DhanApiError(
                f"Instrument master download failed [{resp.status_code}]"
            )
        with open(dest_path, "wb") as f:
            f.write(resp.content)
        return dest_path

    # ------------------------------------------------------------------
    # Expiry list
    # ------------------------------------------------------------------
    def get_expiry_list(self, underlying_scrip: int, underlying_seg: str) -> list[str]:
        """Returns sorted ascending list of expiry date strings (YYYY-MM-DD)."""
        self._throttle_optionchain()
        body = self._post(
            "/optionchain/expirylist",
            {"UnderlyingScrip": underlying_scrip, "UnderlyingSeg": underlying_seg},
        )
        data = body.get("data")
        if not data:
            raise DhanApiError(
                f"No expiry list returned for underlying_scrip={underlying_scrip} seg={underlying_seg}: {body}"
            )
        return sorted(data)

    # ------------------------------------------------------------------
    # Option chain
    # ------------------------------------------------------------------
    def get_option_chain(
        self, underlying_scrip: int, underlying_seg: str, expiry: str
    ) -> dict[str, Any]:
        """
        Returns dict: {"last_price": float, "oc": {strike_str: {"ce": {...}, "pe": {...}}}}
        """
        self._throttle_optionchain()
        body = self._post(
            "/optionchain",
            {
                "UnderlyingScrip": underlying_scrip,
                "UnderlyingSeg": underlying_seg,
                "Expiry": expiry,
            },
        )
        data = body.get("data")
        if not data or "oc" not in data:
            raise DhanApiError(
                f"No option chain returned for underlying_scrip={underlying_scrip} "
                f"seg={underlying_seg} expiry={expiry}: {body}"
            )
        return data

    def _throttle_optionchain(self) -> None:
        # Option chain endpoints are rate-limited to one request per 3 seconds.
        elapsed = time.time() - self._last_optionchain_call
        if elapsed < 3.1:
            time.sleep(3.1 - elapsed)
        self._last_optionchain_call = time.time()

    # ------------------------------------------------------------------
    # Historical daily candles
    # ------------------------------------------------------------------
    def get_historical_daily(
        self,
        security_id: int,
        exchange_segment: str,
        instrument: str,
        from_date: str,
        to_date: str,
        expiry_code: int = 0,
    ) -> dict[str, list[float]]:
        body = self._post(
            "/charts/historical",
            {
                "securityId": str(security_id),
                "exchangeSegment": exchange_segment,
                "instrument": instrument,
                "fromDate": from_date,
                "toDate": to_date,
                "expiryCode": expiry_code,
            },
        )
        if "close" not in body:
            raise DhanApiError(
                f"No historical data returned for security_id={security_id} "
                f"{from_date}..{to_date}: {body}"
            )
        return body

    # ------------------------------------------------------------------
    # Market quote / LTP
    # ------------------------------------------------------------------
    def get_ltp(self, segment_to_ids: dict[str, list[int]]) -> dict[str, Any]:
        self._throttle_marketfeed()
        body = self._post("/marketfeed/ltp", segment_to_ids)
        data = body.get("data")
        if data is None:
            raise DhanApiError(f"No LTP data returned for {segment_to_ids}: {body}")
        return data

    def get_ohlc(self, segment_to_ids: dict[str, list[int]]) -> dict[str, Any]:
        self._throttle_marketfeed()
        body = self._post("/marketfeed/ohlc", segment_to_ids)
        data = body.get("data")
        if data is None:
            raise DhanApiError(f"No OHLC data returned for {segment_to_ids}: {body}")
        return data

    def get_quote(self, segment_to_ids: dict[str, list[int]]) -> dict[str, Any]:
        self._throttle_marketfeed()
        body = self._post("/marketfeed/quote", segment_to_ids)
        data = body.get("data")
        if data is None:
            raise DhanApiError(f"No quote data returned for {segment_to_ids}: {body}")
        return data

    def _throttle_marketfeed(self) -> None:
        # /marketfeed/* endpoints are rate-limited to 1 request per second.
        elapsed = time.time() - self._last_marketfeed_call
        if elapsed < 1.05:
            time.sleep(1.05 - elapsed)
        self._last_marketfeed_call = time.time()
