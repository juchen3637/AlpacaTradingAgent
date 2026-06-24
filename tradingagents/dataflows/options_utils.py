"""
options_utils.py - Alpaca options chain data for the Ghetto Standard Deviation tool.

Two responsibilities:
- Enumerate available expirations for an underlying (cached — they change slowly).
- Fetch live bid/ask quotes for a single expiration's chain (NEVER cached — stale
  option quotes would corrupt the SD calculation and verdicts).

Everything returned is plain JSON-serializable data so the Dash callbacks can map
it onto the engine's ContractQuote / AnalysisInput without importing Alpaca types.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionChainRequest
from alpaca.data.enums import OptionsFeed
from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.trading.enums import AssetStatus

from .config import get_api_key
from .cache_utils import with_cache
from .alpaca_utils import get_alpaca_trading_client


def get_alpaca_option_data_client() -> OptionHistoricalDataClient:
    api_key = get_api_key("alpaca_api_key", "ALPACA_API_KEY")
    api_secret = get_api_key("alpaca_secret_key", "ALPACA_SECRET_KEY")
    if not api_key or not api_secret:
        raise ValueError("Alpaca API key or secret not found. Please set ALPACA_API_KEY and ALPACA_SECRET_KEY.")
    return OptionHistoricalDataClient(api_key, api_secret)


def _options_feed() -> OptionsFeed:
    """OPRA requires a paid options-data subscription; default to the free indicative feed."""
    raw = (get_api_key("alpaca_options_feed", "ALPACA_OPTIONS_FEED") or "").strip().lower()
    return OptionsFeed.OPRA if raw == "opra" else OptionsFeed.INDICATIVE


def parse_occ_symbol(occ: str) -> tuple[float, str, date] | None:
    """Parse an OCC option symbol → (strike, side, expiry), or None if malformed.

    Format: <root><YYMMDD><C|P><strike * 1000, zero-padded to 8 digits>.
    The strike field is the last 8 chars, the side the char before it, and the
    six chars before that the date — the root is whatever remains (1-6 chars).
    """
    if len(occ) < 15:
        return None
    try:
        strike = int(occ[-8:]) / 1000.0
        side = "call" if occ[-9].upper() == "C" else "put"
        expiry = datetime.strptime(occ[-15:-9], "%y%m%d").date()
        return strike, side, expiry
    except (ValueError, IndexError):
        return None


# Alpaca's option-contracts endpoint returns ONLY the nearest expiration unless an
# expiration_date_gte filter is supplied. Bound the upper end too so the response
# stays well under the page limit (covers weeklies + the near monthlies this tool needs).
_EXPIRATION_WINDOW_DAYS = 90


@with_cache(cache_category="options_expirations", max_age_hours=24)
def get_option_expirations(symbol: str) -> list[str]:
    """Sorted, de-duplicated list of available expiration dates (ISO strings).

    Spans today through _EXPIRATION_WINDOW_DAYS out; without the date window Alpaca
    returns only the soonest expiration.
    """
    client = get_alpaca_trading_client()
    today = datetime.now().date()
    expirations: set[str] = set()
    page_token = None
    while True:
        req = GetOptionContractsRequest(
            underlying_symbols=[symbol],
            status=AssetStatus.ACTIVE,
            expiration_date_gte=today,
            expiration_date_lte=today + timedelta(days=_EXPIRATION_WINDOW_DAYS),
            limit=10000,
            page_token=page_token,
        )
        resp = client.get_option_contracts(req)
        for c in resp.option_contracts or []:
            exp = c.expiration_date
            expirations.add(exp.isoformat() if isinstance(exp, date) else str(exp))
        page_token = getattr(resp, "next_page_token", None)
        if not page_token:
            break
    return sorted(expirations)


def get_option_chain_quotes(symbol: str, expiration: str) -> list[dict]:
    """Live quotes for one expiration's chain. Contracts without a quote are dropped."""
    client = get_alpaca_option_data_client()
    req = OptionChainRequest(
        underlying_symbol=symbol,
        feed=_options_feed(),
        expiration_date=date.fromisoformat(expiration),
    )
    snapshots = client.get_option_chain(req)

    rows: list[dict] = []
    for occ, snap in (snapshots or {}).items():
        quote = getattr(snap, "latest_quote", None)
        if quote is None or not quote.bid_price or not quote.ask_price or quote.ask_price <= 0:
            continue
        parsed = parse_occ_symbol(occ)
        if parsed is None:
            continue
        strike, side, _ = parsed
        rows.append({
            "symbol": occ,
            "strike": strike,
            "side": side,
            "bid": float(quote.bid_price),
            "ask": float(quote.ask_price),
            "iv": getattr(snap, "implied_volatility", None),
        })
    rows.sort(key=lambda r: (r["side"], r["strike"]))
    return rows


def get_atm_quotes(symbol: str, current_price: float, expiration: str) -> dict:
    """ATM strike (nearest at/above price) plus its call & put asks."""
    chain = get_option_chain_quotes(symbol, expiration)
    calls = {r["strike"]: r for r in chain if r["side"] == "call"}
    puts = {r["strike"]: r for r in chain if r["side"] == "put"}

    strikes = sorted(set(calls) | set(puts))
    above = [s for s in strikes if s >= current_price]
    atm_strike = min(above) if above else (max(strikes) if strikes else None)

    call = calls.get(atm_strike)
    put = puts.get(atm_strike)
    return {
        "atm_strike": atm_strike,
        "call_ask": call["ask"] if call else None,
        "put_ask": put["ask"] if put else None,
    }
