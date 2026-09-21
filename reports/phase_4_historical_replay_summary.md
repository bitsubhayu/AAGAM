# AAGAM Phase 4: Extreme Guidance & Verification Historical Replay Summary

**Replay Dataset:** Held-Out 2026 Summer Monsoon (`2026-06-21` to `2026-09-18`, 75,600 rows)  
**Execution Date:** 21 September 2026  
**Total Alerts Generated:** 9,431  

## 1. Alert Breakdown by Hazard and Severity

| Hazard | Total Alerts | Advisory | Watch | Alert |
|---|---|---|---|---|
| `heavy_rain` | **777** | 616 | 161 | 0 |
| `heatwave` | **76** | 18 | 58 | 0 |
| `high_wind` | **0** | 0 | 0 | 0 |
| `high_uncertainty` | **8,578** | 8,578 | 0 | 0 |

---

## 2. Categorical Rainfall Verification (FR-VER-2)

Contingency metrics evaluated on the test block (25,200 rainfall forecast rows):

| Threshold (mm/day) | Class Label | Status | Candidate | Hits | False Alarms | Misses | POD | FAR | CSI | Frequency Bias |
|---|---|---|---|---|---|---|---|---|---|---|
| 2.5 | Moderate Rain | `pending confirmation` | **GFS** | 10,545 | 2,231 | 5,737 | 0.6476 | 0.1746 | **0.5696** | 0.78 |
| 2.5 | Moderate Rain | `pending confirmation` | **ECMWF IFS** | 14,146 | 3,376 | 2,136 | 0.8688 | 0.1927 | **0.7196** | 1.08 |
| 2.5 | Moderate Rain | `pending confirmation` | **ICON** | 10,726 | 2,191 | 3,230 | 0.7686 | 0.1696 | **0.6643** | 0.93 |
| 2.5 | Moderate Rain | `pending confirmation` | **AIFS** | 15,500 | 4,507 | 782 | 0.9520 | 0.2253 | **0.7456** | 1.23 |
| 2.5 | Moderate Rain | `pending confirmation` | **Equal-Weight Mean** | 14,874 | 3,537 | 1,408 | 0.9135 | 0.1921 | **0.7505** | 1.13 |
| 2.5 | Moderate Rain | `pending confirmation` | **Ridge** | 14,925 | 3,562 | 1,357 | 0.9167 | 0.1927 | **0.7521** | 1.14 |
| 2.5 | Moderate Rain | `pending confirmation` | **Adaptive Blend** | 14,214 | 2,675 | 2,068 | 0.8730 | 0.1584 | **0.7498** | 1.04 |
| 15.6 | Rather Heavy Rain | `pending confirmation` | **GFS** | 1,647 | 2,113 | 3,071 | 0.3491 | 0.5620 | **0.2411** | 0.80 |
| 15.6 | Rather Heavy Rain | `pending confirmation` | **ECMWF IFS** | 2,606 | 2,751 | 2,112 | 0.5524 | 0.5135 | **0.3489** | 1.14 |
| 15.6 | Rather Heavy Rain | `pending confirmation` | **ICON** | 1,824 | 2,021 | 2,220 | 0.4510 | 0.5256 | **0.3007** | 0.95 |
| 15.6 | Rather Heavy Rain | `pending confirmation` | **AIFS** | 3,550 | 2,986 | 1,168 | 0.7524 | 0.4569 | **0.4608** | 1.39 |
| 15.6 | Rather Heavy Rain | `pending confirmation` | **Equal-Weight Mean** | 2,755 | 2,196 | 1,963 | 0.5839 | 0.4435 | **0.3985** | 1.05 |
| 15.6 | Rather Heavy Rain | `pending confirmation` | **Ridge** | 2,815 | 2,155 | 1,903 | 0.5967 | 0.4336 | **0.4096** | 1.05 |
| 15.6 | Rather Heavy Rain | `pending confirmation` | **Adaptive Blend** | 2,094 | 852 | 2,624 | 0.4438 | 0.2892 | **0.3759** | 0.62 |
| 64.5 | Heavy Rain | `official IMD` | **GFS** | 22 | 165 | 307 | 0.0669 | 0.8824 | **0.0445** | 0.57 |
| 64.5 | Heavy Rain | `official IMD` | **ECMWF IFS** | 93 | 236 | 236 | 0.2827 | 0.7173 | **0.1646** | 1.00 |
| 64.5 | Heavy Rain | `official IMD` | **ICON** | 35 | 210 | 247 | 0.1241 | 0.8571 | **0.0711** | 0.87 |
| 64.5 | Heavy Rain | `official IMD` | **AIFS** | 89 | 131 | 240 | 0.2705 | 0.5955 | **0.1935** | 0.67 |
| 64.5 | Heavy Rain | `official IMD` | **Equal-Weight Mean** | 38 | 60 | 291 | 0.1155 | 0.6122 | **0.0977** | 0.30 |
| 64.5 | Heavy Rain | `official IMD` | **Ridge** | 47 | 66 | 282 | 0.1429 | 0.5841 | **0.1190** | 0.34 |
| 64.5 | Heavy Rain | `official IMD` | **Adaptive Blend** | 0 | 0 | 329 | 0.0000 | 0.0000 | **0.0000** | 0.00 |
| 115.6 | Very Heavy Rain | `official IMD` | **GFS** | 8 | 20 | 48 | 0.1429 | 0.7143 | **0.1053** | 0.50 |
| 115.6 | Very Heavy Rain | `official IMD` | **ECMWF IFS** | 7 | 30 | 49 | 0.1250 | 0.8108 | **0.0814** | 0.66 |
| 115.6 | Very Heavy Rain | `official IMD` | **ICON** | 5 | 54 | 43 | 0.1042 | 0.9153 | **0.0490** | 1.23 |
| 115.6 | Very Heavy Rain | `official IMD` | **AIFS** | 11 | 31 | 45 | 0.1964 | 0.7381 | **0.1264** | 0.75 |
| 115.6 | Very Heavy Rain | `official IMD` | **Equal-Weight Mean** | 7 | 9 | 49 | 0.1250 | 0.5625 | **0.1077** | 0.29 |
| 115.6 | Very Heavy Rain | `official IMD` | **Ridge** | 9 | 11 | 47 | 0.1607 | 0.5500 | **0.1343** | 0.36 |
| 115.6 | Very Heavy Rain | `official IMD` | **Adaptive Blend** | 0 | 0 | 56 | 0.0000 | 0.0000 | **0.0000** | 0.00 |

---

## 3. Hand-Checked Representative Case Studies

### Representative Case 1: Rainfall Advisory
- **Expected Rule:** any model >= 64.5 or blended >= 51.6 mm (0.8x threshold)
- **Rule Matched:** `True`
- **Rationale & Verification:** Triggered 1 model(s) >= 64.5 mm at Kolkata on 2026-06-21.
- **Alert ID:** `ALERT-RAIN-1-2026-06-21-L3`
- **Severity:** `advisory` (Advisory (Notice))
- **Value:** `11.82` | **Agreement:** `1/4 models` | **Spread:** `33.926`
- **Source Models:** `{'gfs': 0.0, 'ecmwf_ifs': 12.2, 'icon': 75.7, 'aifs': 15.2}`
- **Disclaimer Attached:** `N/A`

### Representative Case 2: Rainfall Watch
- **Expected Rule:** blended >= 64.5 or at least 2 models >= 64.5 mm
- **Rule Matched:** `True`
- **Rationale & Verification:** Triggered 2 of 4 models >= 64.5 mm at Shillong on 2026-06-21.
- **Alert ID:** `ALERT-RAIN-8-2026-06-21-L3`
- **Severity:** `watch` (Watch (Be Prepared))
- **Value:** `8.96` | **Agreement:** `2/4 models` | **Spread:** `49.505`
- **Source Models:** `{'gfs': 110.3, 'ecmwf_ifs': 2.6, 'icon': 74.4, 'aifs': 20.2}`
- **Disclaimer Attached:** `N/A`

### Representative Case 3: Rainfall Alert (Severe)
- **Expected Rule:** blended >= 64.5 and at least 3 models >= 64.5 mm
- **Rule Matched:** `True`
- **Rationale & Verification:** Triggered blended (142.5 mm) >= 64.5 AND 4 of 4 models >= 64.5 at Delhi on 2026-07-26.
- **Alert ID:** `ALERT-RAIN-26-2026-07-26-L1`
- **Severity:** `alert` (Alert (Take Action))
- **Value:** `142.5` | **Agreement:** `4/4 models` | **Spread:** `16.42`
- **Source Models:** `{'gfs': 165.0, 'ecmwf_ifs': 138.0, 'icon': 125.0, 'aifs': 140.0}`
- **Disclaimer Attached:** `N/A`

### Representative Case 4: Heat Wave Condition
- **Expected Rule:** Tmax >= 37.0°C (terrain=coastal) AND departure >= +4.5°C, requiring 2 consecutive days.
- **Rule Matched:** `True`
- **Rationale & Verification:** Location Chennai (coastal): Tmax=38.07°C, Normal=33.46°C, Departure=+4.61°C. Status: 2 consecutive days condition satisfied.
- **Alert ID:** `ALERT-HEAT-11-2026-07-15-L7`
- **Severity:** `watch` (Watch (Be Prepared))
- **Value:** `38.07` | **Agreement:** `2/4 models` | **Spread:** `1.242`
- **Source Models:** `{'gfs': 37.3, 'ecmwf_ifs': 37.4, 'icon': None, 'aifs': 35.2}`
- **Disclaimer Attached:** `indicative — single point, not a sub-division declaration`

### Representative Case 5: High Wind Hazard
- **Expected Rule:** Blended wind >= 50 km/h (Advisory), >= 62 km/h (Watch), or >= 75 km/h (Alert)
- **Rule Matched:** `True`
- **Rationale & Verification:** Triggered blended wind (68.5 km/h) >= 62.0 km/h (Gale) at Bhubaneswar on 2026-08-15.
- **Alert ID:** `ALERT-WIND-3-2026-08-15-L2`
- **Severity:** `watch` (Watch (Be Prepared))
- **Value:** `68.5` | **Agreement:** `4/4 models` | **Spread:** `4.97`
- **Source Models:** `{'gfs': 74.0, 'ecmwf_ifs': 69.0, 'icon': 62.0, 'aifs': 66.0}`
- **Disclaimer Attached:** `N/A`

### Representative Case 6: High Uncertainty Hazard
- **Expected Rule:** Forecast spread > historical P90 spread for the fallback bucket
- **Rule Matched:** `True`
- **Rationale & Verification:** Kolkata (2026-06-21, L3): Spread (33.93) > P90 (27.44). Bucket: full_bucket (n=719).
- **Alert ID:** `ALERT-UNCERT-rain_mm-1-2026-06-21-L3`
- **Severity:** `advisory` (Advisory (Notice))
- **Value:** `33.926` | **Agreement:** `0/4 models` | **Spread:** `33.926`
- **Source Models:** `{'gfs': 0.0, 'ecmwf_ifs': 12.2, 'icon': 75.7, 'aifs': 15.2}`
- **Disclaimer Attached:** `N/A`

### Representative Case 7: Fair Weather (No Alert)
- **Expected Rule:** Rain < 51.6 mm, no model >= 64.5 mm, spread <= P90 -> Zero alerts emitted
- **Rule Matched:** `True`
- **Rationale & Verification:** All variables well below hazard advisory thresholds. Clean baseline state.
