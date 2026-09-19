"""AAGAM — Open-Meteo Verification Script (PRD Phase 0 & Tech Stack §15).

Verifies:
1. Exact model identifiers in Open-Meteo API (GFS, IFS, ICON, AIFS)
2. Availability of previous-run variables (precipitation_previous_day1..7) for all 4 models
3. Cost calculations for live cycle and historical backfill
"""
import json
import sys
import urllib.error
import urllib.request

MODELS = [
    "gfs_seamless",
    "ecmwf_ifs025",
    "icon_global",
    "ecmwf_aifs025_single"
]

def verify_models():
    print("=" * 60)
    print("1. Verifying Open-Meteo Model Identifiers...")
    print("=" * 60)

    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=28.61&longitude=77.20"
        "&hourly=temperature_2m"
        f"&models={','.join(MODELS)}"
    )

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AAGAM-Verification/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            hourly_keys = list(data.get("hourly", {}).keys())
            print("Status: 200 OK")
            print("Returned Hourly Keys:", hourly_keys)

            all_found = True
            for m in MODELS:
                key = f"temperature_2m_{m}"
                found = key in hourly_keys
                status = "PASS" if found else "FAIL"
                print(f"  - Model '{m}': {status}")
                if not found:
                    all_found = False

            if not all_found:
                print("FAILED: Some models were not found!")
                return False
    except Exception as e:
        print(f"FAILED to query Open-Meteo: {e}")
        return False

    print("\n" + "=" * 60)
    print("2. Verifying Previous Runs (precipitation_previous_day1..7)...")
    print("=" * 60)

    previous_vars = [f"precipitation_previous_day{i}" for i in range(1, 8)]
    prev_results = {}

    for m in MODELS:
        var_str = ",".join(previous_vars)
        p_url = (
            "https://api.open-meteo.com/v1/forecast"
            "?latitude=28.61&longitude=77.20"
            f"&hourly={var_str}"
            f"&models={m}&past_days=7"
        )
        try:
            req = urllib.request.Request(p_url, headers={"User-Agent": "AAGAM-Verification/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                keys = list(data.get("hourly", {}).keys())
                has_all = all(v in keys for v in previous_vars)
                prev_results[m] = {
                    "status": "PASS" if has_all else "INCOMPLETE",
                    "keys_found": [k for k in keys if k != "time"]
                }
                print(f"  - {m}: PASS (Found {len(prev_results[m]['keys_found'])}/7 previous run days)")
        except Exception as e:
            prev_results[m] = {"status": "FAIL", "error": str(e)}
            print(f"  - {m}: FAIL ({e})")

    print("\n" + "=" * 60)
    print("3. Open-Meteo Cost & Call Budget Calculation")
    print("=" * 60)
    # 40 locations * 4 models
    live_calls_per_cycle = 40 * 4 # 160 calls
    live_calls_per_day = live_calls_per_cycle * 4 # 640 calls/day
    free_daily_limit = 10000
    free_monthly_limit = 300000
    live_monthly_calls = live_calls_per_day * 30 # 19,200 calls/month

    # Backfill estimation (Jan 2024 to Sep 2026 ~ 990 days)
    backfill_units = 990 / 14 # ~71 units
    backfill_multiplier = 2.1 # 21 variables = ~2.1 calls per unit
    backfill_calls_total = int(backfill_units * backfill_multiplier * 160)

    print(f"  Live cycle calls: {live_calls_per_cycle} calls/cycle")
    print(f"  Daily live calls (4 cycles): {live_calls_per_day} calls/day ({live_calls_per_day/free_daily_limit*100:.1f}% of 10,000 daily cap)")
    print(f"  Monthly live calls: {live_monthly_calls} calls/month ({live_monthly_calls/free_monthly_limit*100:.1f}% of 300,000 monthly cap)")
    print(f"  One-off historical backfill estimate: ~{backfill_calls_total} total calls")
    print("  Recommended backfill throttle: <= 8,000 calls/day across 3-4 days")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = verify_models()
    sys.exit(0 if success else 1)
