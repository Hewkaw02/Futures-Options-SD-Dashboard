import asyncio
import math
from datetime import date
from typing import Any
from tastytrade import Session, DXLinkStreamer
from tastytrade.instruments import Future, get_future_option_chain
from tastytrade.dxfeed import Greeks
from tastytrade.utils import TastytradeError

# Monkeypatch the tastytrade SDK's error validation to handle malformed error responses
import tastytrade.utils as tt_utils
_original_validate_response = tt_utils.validate_response

def _patched_validate_response(response):
    """
    Patched version that handles when API returns 'error' as a string instead of dict.
    This prevents AttributeError('str' object has no attribute 'get') from crashing the app.
    """
    if response.status_code // 100 != 2:
        try:
            json_data = response.json()
        except Exception as e:
            raise TastytradeError(f"Couldn't parse response: {response.text}") from e
        
        content = json_data.get("error")
        if not content:
            raise TastytradeError(f"Couldn't parse response: {json_data}")
        
        # Handle both dict (expected) and string (malformed) error payloads
        if isinstance(content, str):
            raise TastytradeError(f"API Error: {content}")
        
        errors = content.get("errors") or [content]
        message = ""
        for error in errors:
            if isinstance(error, dict):
                if "code" in error and "message" in error:
                    message += f"{error['code']}: {error['message']}\n"
                elif "domain" in error and "reason" in error:
                    message += f"{error['domain']}: {error['reason']}\n"
                else:
                    tt_utils.logger.debug(f"Unknown error type: {error}")
        
        raise TastytradeError(message)

tt_utils.validate_response = _patched_validate_response

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CLIENT_SECRET, REFRESH_TOKEN

SYMBOLS    = ["/GC", "/NQ", "/ES"]
TARGET_DTE = 0   # 0 DTE (today's expiry)
MIN_SD_DTE_DAYS = 1.0  # floor used only for SD math when same-day expiry is selected


# ─── Fallback: Infer mark price from option chain ──────────────
def infer_mark_price_from_chain(chain: dict, expiry_date: date, debug: bool = False) -> float:
    """
    Infer the futures mark price by finding the "middle" of the option chain.
    Uses the call-put parity principle: the strike price where calls and puts
    have similar value is close to the futures price.
    
    For simplicity, we use the median strike across all options.
    """
    if expiry_date not in chain:
        if debug:
            print(f"    [debug] Expiry {expiry_date} not in chain. Available: {list(chain.keys())[:3]}")
        return 0.0
    
    options = chain[expiry_date]
    if not options:
        if debug:
            print(f"    [debug] No options found for {expiry_date}")
        return 0.0
    
    if debug:
        print(f"    [debug] Found {len(options)} options for {expiry_date}")
    
    strikes = []
    for opt in options:
        try:
            strike = float(opt.strike_price)
            strikes.append(strike)
        except (ValueError, AttributeError, TypeError):
            if debug:
                print(f"    [debug] Failed to parse strike: {opt.strike_price}")
            pass
    
    if not strikes:
        if debug:
            print(f"    [debug] No valid strikes extracted from {len(options)} options")
        return 0.0
    
    # Use median strike as proxy for ATM (futures) price
    strikes.sort()
    median_strike = strikes[len(strikes) // 2]
    
    if debug:
        print(f"    [debug] Extracted {len(strikes)} strikes")
        print(f"    [debug] Strike range: {strikes[0]:.2f} - {strikes[-1]:.2f}")
        print(f"    [debug] Using median strike as mark price: {median_strike:.2f}")
    
    return median_strike



# ─── SD range ────────────────────────────────────────────────
def calc_sd_ranges(price: float, iv: float, dte: float) -> dict:
    """
    Calculate 1-sigma and 2-sigma price ranges.
    Using 365 Calendar Days — standard for CME futures that trade ~23hrs/day.
    """
    # 0 DTE makes SD move mathematically zero, so use a floor for range estimation.
    effective_dte = max(float(dte), MIN_SD_DTE_DAYS)
    sd1 = price * iv * math.sqrt(effective_dte / 365)

    # Use higher precision when rounding ranges to avoid 1sd/2sd collapsing to the same value
    PREC = 4
    swing_p1_percent = (sd1 / price * 100) if price > 0 else 0.0

    # Probability that a normal variable exceeds 1-sigma in absolute value: erfc(1/sqrt(2)) (~0.3173)
    try:
        swing_p1_prob = math.erfc(1.0 / math.sqrt(2.0)) * 100.0
    except Exception:
        swing_p1_prob = 31.73

    return {
        "1sd_upper": round(price + sd1, PREC),
        "1sd_lower": round(price - sd1, PREC),
        "2sd_upper": round(price + 2 * sd1, PREC),
        "2sd_lower": round(price - 2 * sd1, PREC),
        "sd1_move": round(sd1, PREC),
        "swing_p1_percent": round(swing_p1_percent, 4),
        "swing_p1_prob_percent": round(swing_p1_prob, 2),
        "sd_dte_used": round(effective_dte, 4),
    }


def build_asset_values(
    root_symbol: str,
    front_month_symbol: str,
    mark: float,
    best_expiry: date,
    dte: int,
    atm_streamer_symbol: str,
    atm_strike: float,
    iv: float,
    call_count: int,
    put_count: int,
    sd: dict,
) -> dict[str, Any]:
    """Build a full per-asset snapshot so all values are easy to inspect/export."""
    return {
        "symbol": root_symbol,
        "front_month": front_month_symbol,
        "mark": round(mark, 2),
        "expiry": best_expiry.isoformat(),
        "dte": dte,
        "atm_streamer_symbol": atm_streamer_symbol,
        "atm_strike": float(atm_strike),
        "iv": iv,
        "iv_percent": round(iv * 100, 2),
        "call_count": call_count,
        "put_count": put_count,
        **sd,
    }


# --- Main -----------------------------------------------------
async def main():
    # 1. Login via SDK
    print("Logging in...")
    session = Session(provider_secret=CLIENT_SECRET, refresh_token=REFRESH_TOKEN)
    print("[OK] Logged in\n")

    # 2. Get all futures, find front-month per root (nearest expiry)
    all_futures = await Future.get(session)
    root_codes  = [s.lstrip('/') for s in SYMBOLS]   # ["GC", "NQ", "ES"]
    front_months: dict[str, str] = {}                 # "GC" -> "/GCJ26"
    for code in root_codes:
        matches = sorted(
            [f for f in all_futures if f.product_code == code],
            key=lambda f: f.expiration_date,
        )
        if matches:
            front_months[code] = matches[0].symbol

    # 3. Skip market data fetch - we'll infer mark price from the option chain instead
    # (This avoids permission issues with market data API)
    print("[INFO]  Skipping market data API (will infer prices from option chains)\n")

    # 4. Per symbol: chain -> ATM call -> IV -> SD
    all_asset_values: list[dict[str, Any]] = []

    async with DXLinkStreamer(session) as streamer:
        for root_sym in SYMBOLS:
            print(f"{'-'*56}")
            print(f"  Symbol : {root_sym}")
            try:
                chain = await get_future_option_chain(session, root_sym)
                today = date.today()

                # Try 0 DTE first; if not available, use nearest expiry
                best_exp = None
                dte_actual = None
                
                if today in chain:
                    best_exp = today
                    dte_actual = TARGET_DTE
                else:
                    # Fallback: use nearest expiry in the future
                    future_dates = sorted([d for d in chain.keys() if d > today])
                    if future_dates:
                        best_exp = future_dates[0]
                        dte_actual = (best_exp - today).days
                        print(f"  [WARN]  No 0 DTE available, using nearest expiry: {best_exp} ({dte_actual} DTE)")
                
                if best_exp is None:
                    print(f"  [WARN]  No future expirations available in chain")
                    continue

                # Mark price: infer from option chain (no market data API dependency)
                root_code = root_sym.lstrip('/')
                print(f"  [INFO]  Inferring mark price from option chain...")
                mark = infer_mark_price_from_chain(chain, best_exp, debug=False)
                
                if mark == 0:
                    raise ValueError("No mark price could be inferred from chain")
                
                print(f"  [INFO]  Inferred mark price: {mark:.2f}")

                # ATM call at best expiry to define a range for min IV search
                options = chain[best_exp]
                calls   = [o for o in options if o.option_type.value == "C"]
                puts    = [o for o in options if o.option_type.value == "P"]
                
                # Filter options within +/- 5% to find the baseline IV (bottom of the smile)
                min_s_iv = mark * 0.95
                max_s_iv = mark * 1.05
                relevant_options = [o for o in options if min_s_iv <= float(o.strike_price) <= max_s_iv]
                streamer_symbols = [o.streamer_symbol for o in relevant_options]

                # Get Greeks IV from DXLink streamer
                await streamer.subscribe(Greeks, streamer_symbols)
                end_time = asyncio.get_event_loop().time() + 5.0
                found_vols = []
                while asyncio.get_event_loop().time() < end_time:
                    try:
                        greeks = await asyncio.wait_for(streamer.get_event(Greeks), timeout=0.5)
                        if greeks.volatility and float(greeks.volatility) > 0:
                            found_vols.append(float(greeks.volatility))
                    except asyncio.TimeoutError:
                        continue
                    except Exception:
                        continue
                
                iv = min(found_vols) if found_vols else 0.0

                if iv == 0:
                    print(f"  [WARN]  IV = 0 (streamer returned no data)")
                    continue

                sd = calc_sd_ranges(mark, iv, dte_actual)
                
                # Find ATM strike for building the asset values record
                atm = min([o for o in options if o.option_type.value == "C"], key=lambda o: abs(float(o.strike_price) - mark))
                asset_values = build_asset_values(
                    root_symbol=root_sym,
                    front_month_symbol=front_months.get(root_code, ''),
                    mark=mark,
                    best_expiry=best_exp,
                    dte=dte_actual,
                    atm_streamer_symbol=atm.streamer_symbol,
                    atm_strike=float(atm.strike_price),
                    iv=iv,
                    call_count=len(calls),
                    put_count=len(puts),
                    sd=sd,
                )
                all_asset_values.append(asset_values)

                print(f"  Expiry : {best_exp}  (DTE: {dte_actual})")
                print(f"  Price  : {mark:,.2f}")
                print(f"  ATM IV : {iv:.4f}  ({iv*100:.2f}%)")
                print(f"  1 SD   : [{sd['1sd_lower']:,.4f} - {sd['1sd_upper']:,.4f}]  (+/-{sd['sd1_move']:,.4f})")
                print(f"  2 SD   : [{sd['2sd_lower']:,.4f} - {sd['2sd_upper']:,.4f}]")
                print(f"  Swing P1 (magnitude): +/-{sd['swing_p1_percent']:.4f}% (Price vs 1 SD)")
                print(f"  Swing P1 (probability): {sd.get('swing_p1_prob_percent', 0):.2f}% chance to move outside +/-1sigma")
                print(f"  SD DTE : {sd['sd_dte_used']} days (math floor)")
                print(f"  Values : {asset_values}")

            except Exception as e:
                print(f"  [FAIL]  Error: {e}")

    print(f"{'-'*56}")
    print("All asset values:")
    for item in all_asset_values:
        print(item)


if __name__ == "__main__":
    asyncio.run(main())

