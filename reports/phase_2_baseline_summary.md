# AAGAM Phase 2: Baseline Benchmark Evaluation Summary

## Overall Test Performance (2026 Monsoon Test Block)

| variable | candidate | mae | rmse | bias | n | slice_type | slice_value |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rain_mm | GFS | 8.3864 | 15.8559 | -2.3335 | 25200 | overall | all |
| rain_mm | ECMWF IFS | 7.4875 | 14.3556 | 0.7331 | 25200 | overall | all |
| rain_mm | ICON | 8.071 | 16.7871 | -0.6665 | 21600 | overall | all |
| rain_mm | AIFS | 6.4712 | 11.6996 | 2.0377 | 25200 | overall | all |
| rain_mm | Equal-Weight Mean | 6.2757 | 11.8461 | -0.0425 | 25200 | overall | all |
| rain_mm | Best-Single Model | 7.1581 | 13.3142 | -0.3292 | 25200 | overall | all |
| rain_mm | Inverse-MAE Blend | 6.2231 | 11.7067 | 0.0752 | 25200 | overall | all |
| tmax_c | GFS | 2.284 | 3.0777 | 0.9345 | 25200 | overall | all |
| tmax_c | ECMWF IFS | 1.2781 | 1.6636 | -0.5594 | 25200 | overall | all |
| tmax_c | ICON | 1.4273 | 1.8778 | -0.3546 | 21600 | overall | all |
| tmax_c | AIFS | 1.1634 | 1.5007 | -0.6479 | 25200 | overall | all |
| tmax_c | Equal-Weight Mean | 1.1035 | 1.4617 | -0.1516 | 25200 | overall | all |
| tmax_c | Best-Single Model | 1.2387 | 1.6075 | -0.5457 | 25200 | overall | all |
| tmax_c | Inverse-MAE Blend | 1.0444 | 1.3784 | -0.2541 | 25200 | overall | all |
| wind_max_kmh | GFS | 6.2103 | 7.8935 | 5.0689 | 25200 | overall | all |
| wind_max_kmh | ECMWF IFS | 3.1491 | 4.1864 | -0.9964 | 25200 | overall | all |
| wind_max_kmh | ICON | 3.5407 | 4.5229 | -2.4868 | 21600 | overall | all |
| wind_max_kmh | AIFS | 4.0587 | 5.1049 | -2.6405 | 25200 | overall | all |
| wind_max_kmh | Equal-Weight Mean | 2.7803 | 3.5983 | -0.1624 | 25200 | overall | all |
| wind_max_kmh | Best-Single Model | 3.1491 | 4.1864 | -0.9964 | 25200 | overall | all |
| wind_max_kmh | Inverse-MAE Blend | 2.6733 | 3.4987 | -0.4122 | 25200 | overall | all |

## Performance by Lead Day

| variable | lead_days | candidate | mae | rmse | bias | n | slice_type | slice_value |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rain_mm | 1 | GFS | 7.6707 | 15.3351 | -1.1574 | 3600 | lead_days | 1 |
| rain_mm | 1 | ECMWF IFS | 6.0349 | 11.4261 | 0.8694 | 3600 | lead_days | 1 |
| rain_mm | 1 | ICON | 7.3829 | 14.9166 | -0.0828 | 3600 | lead_days | 1 |
| rain_mm | 1 | AIFS | 5.2904 | 9.4612 | 1.5147 | 3600 | lead_days | 1 |
| rain_mm | 1 | Equal-Weight Mean | 5.3976 | 10.2339 | 0.286 | 3600 | lead_days | 1 |
| rain_mm | 1 | Best-Single Model | 5.2904 | 9.4612 | 1.5147 | 3600 | lead_days | 1 |
| rain_mm | 1 | Inverse-MAE Blend | 5.2969 | 9.977 | 0.4008 | 3600 | lead_days | 1 |
| rain_mm | 2 | GFS | 7.7485 | 14.2635 | -1.6346 | 3600 | lead_days | 2 |
| rain_mm | 2 | ECMWF IFS | 6.8352 | 12.8794 | 1.2103 | 3600 | lead_days | 2 |
| rain_mm | 2 | ICON | 7.7019 | 15.8682 | -0.5365 | 3600 | lead_days | 2 |
| rain_mm | 2 | AIFS | 5.7539 | 10.0017 | 1.9376 | 3600 | lead_days | 2 |
| rain_mm | 2 | Equal-Weight Mean | 5.774 | 10.5906 | 0.2442 | 3600 | lead_days | 2 |
| rain_mm | 2 | Best-Single Model | 5.7539 | 10.0017 | 1.9376 | 3600 | lead_days | 2 |
| rain_mm | 2 | Inverse-MAE Blend | 5.7001 | 10.4056 | 0.383 | 3600 | lead_days | 2 |
| rain_mm | 3 | GFS | 8.2936 | 15.6782 | -1.7244 | 3600 | lead_days | 3 |
| rain_mm | 3 | ECMWF IFS | 7.4964 | 14.3243 | 0.9565 | 3600 | lead_days | 3 |
| rain_mm | 3 | ICON | 8.0244 | 16.162 | -0.6397 | 3600 | lead_days | 3 |
| rain_mm | 3 | AIFS | 6.2172 | 10.7092 | 2.1999 | 3600 | lead_days | 3 |
| rain_mm | 3 | Equal-Weight Mean | 6.1637 | 11.4689 | 0.1981 | 3600 | lead_days | 3 |
| rain_mm | 3 | Best-Single Model | 6.2172 | 10.7092 | 2.1999 | 3600 | lead_days | 3 |
| rain_mm | 3 | Inverse-MAE Blend | 6.1052 | 11.2979 | 0.3515 | 3600 | lead_days | 3 |
| rain_mm | 4 | GFS | 8.7348 | 16.9111 | -1.6571 | 3600 | lead_days | 4 |
| rain_mm | 4 | ECMWF IFS | 7.7329 | 14.6485 | 0.5939 | 3600 | lead_days | 4 |
| rain_mm | 4 | ICON | 8.1995 | 18.3263 | -0.8593 | 3600 | lead_days | 4 |
| rain_mm | 4 | AIFS | 6.5877 | 12.1312 | 2.2046 | 3600 | lead_days | 4 |
| rain_mm | 4 | Equal-Weight Mean | 6.4661 | 12.4642 | 0.0705 | 3600 | lead_days | 4 |
| rain_mm | 4 | Best-Single Model | 6.5877 | 12.1312 | 2.2046 | 3600 | lead_days | 4 |
| rain_mm | 4 | Inverse-MAE Blend | 6.4106 | 12.3316 | 0.1976 | 3600 | lead_days | 4 |
| rain_mm | 5 | GFS | 8.4363 | 15.6855 | -3.2667 | 3600 | lead_days | 5 |
| rain_mm | 5 | ECMWF IFS | 7.95 | 15.2907 | 0.5309 | 3600 | lead_days | 5 |
| rain_mm | 5 | ICON | 8.3368 | 17.6179 | -1.1189 | 3600 | lead_days | 5 |
| rain_mm | 5 | AIFS | 6.8522 | 12.3322 | 2.1122 | 3600 | lead_days | 5 |
| rain_mm | 5 | Equal-Weight Mean | 6.4753 | 12.4802 | -0.4356 | 3600 | lead_days | 5 |
| rain_mm | 5 | Best-Single Model | 8.4363 | 15.6855 | -3.2667 | 3600 | lead_days | 5 |
| rain_mm | 5 | Inverse-MAE Blend | 6.4339 | 12.3425 | -0.3384 | 3600 | lead_days | 5 |
| rain_mm | 6 | GFS | 8.8017 | 16.3275 | -3.4511 | 3600 | lead_days | 6 |
| rain_mm | 6 | ECMWF IFS | 8.0678 | 15.6233 | 0.3672 | 3600 | lead_days | 6 |
| rain_mm | 6 | ICON | 8.7802 | 17.5808 | -0.762 | 3600 | lead_days | 6 |
| rain_mm | 6 | AIFS | 7.2186 | 13.5211 | 2.2141 | 3600 | lead_days | 6 |
| rain_mm | 6 | Equal-Weight Mean | 6.7421 | 12.7421 | -0.408 | 3600 | lead_days | 6 |
| rain_mm | 6 | Best-Single Model | 8.8017 | 16.3275 | -3.4511 | 3600 | lead_days | 6 |
| rain_mm | 6 | Inverse-MAE Blend | 6.7142 | 12.6504 | -0.3067 | 3600 | lead_days | 6 |
| rain_mm | 7 | GFS | 9.0192 | 16.6385 | -3.4432 | 3600 | lead_days | 7 |
| rain_mm | 7 | ECMWF IFS | 8.2954 | 15.7632 | 0.6033 | 3600 | lead_days | 7 |
| rain_mm | 7 | ICON | nan | nan | nan | 0 | lead_days | 7 |
| rain_mm | 7 | AIFS | 7.378 | 13.1097 | 2.081 | 3600 | lead_days | 7 |
| rain_mm | 7 | Equal-Weight Mean | 6.911 | 12.665 | -0.253 | 3600 | lead_days | 7 |
| rain_mm | 7 | Best-Single Model | 9.0192 | 16.6385 | -3.4432 | 3600 | lead_days | 7 |
| rain_mm | 7 | Inverse-MAE Blend | 6.901 | 12.6263 | -0.1612 | 3600 | lead_days | 7 |
| tmax_c | 1 | GFS | 2.1636 | 2.9096 | 1.1218 | 3600 | lead_days | 1 |
| tmax_c | 1 | ECMWF IFS | 0.9762 | 1.257 | -0.4763 | 3600 | lead_days | 1 |
| tmax_c | 1 | ICON | 1.1896 | 1.5599 | -0.3343 | 3600 | lead_days | 1 |
| tmax_c | 1 | AIFS | 0.9674 | 1.2438 | -0.4064 | 3600 | lead_days | 1 |
| tmax_c | 1 | Equal-Weight Mean | 0.9247 | 1.2166 | -0.0238 | 3600 | lead_days | 1 |
| tmax_c | 1 | Best-Single Model | 0.9762 | 1.257 | -0.4763 | 3600 | lead_days | 1 |
| tmax_c | 1 | Inverse-MAE Blend | 0.8307 | 1.0861 | -0.1652 | 3600 | lead_days | 1 |
| tmax_c | 2 | GFS | 2.2329 | 3.026 | 0.9404 | 3600 | lead_days | 2 |
| tmax_c | 2 | ECMWF IFS | 1.096 | 1.409 | -0.5226 | 3600 | lead_days | 2 |
| tmax_c | 2 | ICON | 1.3196 | 1.7264 | -0.4396 | 3600 | lead_days | 2 |
| tmax_c | 2 | AIFS | 1.0565 | 1.3537 | -0.5718 | 3600 | lead_days | 2 |
| tmax_c | 2 | Equal-Weight Mean | 1.003 | 1.3313 | -0.1484 | 3600 | lead_days | 2 |
| tmax_c | 2 | Best-Single Model | 1.096 | 1.409 | -0.5226 | 3600 | lead_days | 2 |
| tmax_c | 2 | Inverse-MAE Blend | 0.9297 | 1.227 | -0.2662 | 3600 | lead_days | 2 |
| tmax_c | 3 | GFS | 2.25 | 3.0384 | 0.8791 | 3600 | lead_days | 3 |
| tmax_c | 3 | ECMWF IFS | 1.1984 | 1.5383 | -0.4885 | 3600 | lead_days | 3 |
| tmax_c | 3 | ICON | 1.3928 | 1.8367 | -0.3636 | 3600 | lead_days | 3 |
| tmax_c | 3 | AIFS | 1.1282 | 1.4483 | -0.6789 | 3600 | lead_days | 3 |
| tmax_c | 3 | Equal-Weight Mean | 1.0635 | 1.4061 | -0.163 | 3600 | lead_days | 3 |
| tmax_c | 3 | Best-Single Model | 1.1984 | 1.5383 | -0.4885 | 3600 | lead_days | 3 |
| tmax_c | 3 | Inverse-MAE Blend | 1.0069 | 1.3235 | -0.2617 | 3600 | lead_days | 3 |
| tmax_c | 4 | GFS | 2.2874 | 3.1066 | 0.9715 | 3600 | lead_days | 4 |
| tmax_c | 4 | ECMWF IFS | 1.2534 | 1.6249 | -0.4096 | 3600 | lead_days | 4 |
| tmax_c | 4 | ICON | 1.4968 | 1.942 | -0.3574 | 3600 | lead_days | 4 |
| tmax_c | 4 | AIFS | 1.1873 | 1.523 | -0.7287 | 3600 | lead_days | 4 |
| tmax_c | 4 | Equal-Weight Mean | 1.1082 | 1.4617 | -0.131 | 3600 | lead_days | 4 |
| tmax_c | 4 | Best-Single Model | 1.2534 | 1.6249 | -0.4096 | 3600 | lead_days | 4 |
| tmax_c | 4 | Inverse-MAE Blend | 1.0587 | 1.3867 | -0.2289 | 3600 | lead_days | 4 |
| tmax_c | 5 | GFS | 2.305 | 3.121 | 0.8745 | 3600 | lead_days | 5 |
| tmax_c | 5 | ECMWF IFS | 1.2773 | 1.6677 | -0.369 | 3600 | lead_days | 5 |
| tmax_c | 5 | ICON | 1.5584 | 2.0272 | -0.3323 | 3600 | lead_days | 5 |
| tmax_c | 5 | AIFS | 1.2301 | 1.5753 | -0.726 | 3600 | lead_days | 5 |
| tmax_c | 5 | Equal-Weight Mean | 1.1329 | 1.4985 | -0.1382 | 3600 | lead_days | 5 |
| tmax_c | 5 | Best-Single Model | 1.2773 | 1.6677 | -0.369 | 3600 | lead_days | 5 |
| tmax_c | 5 | Inverse-MAE Blend | 1.084 | 1.4263 | -0.2209 | 3600 | lead_days | 5 |
| tmax_c | 6 | GFS | 2.3904 | 3.1907 | 0.8851 | 3600 | lead_days | 6 |
| tmax_c | 6 | ECMWF IFS | 1.5651 | 1.9781 | -0.8539 | 3600 | lead_days | 6 |
| tmax_c | 6 | ICON | 1.6068 | 2.1187 | -0.3003 | 3600 | lead_days | 6 |
| tmax_c | 6 | AIFS | 1.2698 | 1.6321 | -0.7235 | 3600 | lead_days | 6 |
| tmax_c | 6 | Equal-Weight Mean | 1.1976 | 1.5785 | -0.2481 | 3600 | lead_days | 6 |
| tmax_c | 6 | Best-Single Model | 1.5651 | 1.9781 | -0.8539 | 3600 | lead_days | 6 |
| tmax_c | 6 | Inverse-MAE Blend | 1.1602 | 1.5206 | -0.3279 | 3600 | lead_days | 6 |
| tmax_c | 7 | GFS | 2.3583 | 3.1434 | 0.8694 | 3600 | lead_days | 7 |
| tmax_c | 7 | ECMWF IFS | 1.5804 | 2.0266 | -0.796 | 3600 | lead_days | 7 |
| tmax_c | 7 | ICON | nan | nan | nan | 0 | lead_days | 7 |
| tmax_c | 7 | AIFS | 1.3042 | 1.6799 | -0.7003 | 3600 | lead_days | 7 |
| tmax_c | 7 | Equal-Weight Mean | 1.2948 | 1.6892 | -0.209 | 3600 | lead_days | 7 |
| tmax_c | 7 | Best-Single Model | 1.3042 | 1.6799 | -0.7003 | 3600 | lead_days | 7 |
| tmax_c | 7 | Inverse-MAE Blend | 1.2403 | 1.6102 | -0.308 | 3600 | lead_days | 7 |
| wind_max_kmh | 1 | GFS | 6.0629 | 7.7159 | 5.2418 | 3600 | lead_days | 1 |
| wind_max_kmh | 1 | ECMWF IFS | 2.5064 | 3.3602 | -0.9669 | 3600 | lead_days | 1 |
| wind_max_kmh | 1 | ICON | 3.2898 | 4.1505 | -2.502 | 3600 | lead_days | 1 |
| wind_max_kmh | 1 | AIFS | 3.709 | 4.6811 | -2.5236 | 3600 | lead_days | 1 |
| wind_max_kmh | 1 | Equal-Weight Mean | 2.3413 | 3.007 | -0.1877 | 3600 | lead_days | 1 |
| wind_max_kmh | 1 | Best-Single Model | 2.5064 | 3.3602 | -0.9669 | 3600 | lead_days | 1 |
| wind_max_kmh | 1 | Inverse-MAE Blend | 2.2223 | 2.9075 | -0.4493 | 3600 | lead_days | 1 |
| wind_max_kmh | 2 | GFS | 6.3318 | 8.0317 | 5.4264 | 3600 | lead_days | 2 |
| wind_max_kmh | 2 | ECMWF IFS | 2.7593 | 3.6962 | -0.8303 | 3600 | lead_days | 2 |
| wind_max_kmh | 2 | ICON | 3.327 | 4.252 | -2.4094 | 3600 | lead_days | 2 |
| wind_max_kmh | 2 | AIFS | 3.8773 | 4.8537 | -2.614 | 3600 | lead_days | 2 |
| wind_max_kmh | 2 | Equal-Weight Mean | 2.5095 | 3.2187 | -0.1068 | 3600 | lead_days | 2 |
| wind_max_kmh | 2 | Best-Single Model | 2.7593 | 3.6962 | -0.8303 | 3600 | lead_days | 2 |
| wind_max_kmh | 2 | Inverse-MAE Blend | 2.3944 | 3.1334 | -0.3816 | 3600 | lead_days | 2 |
| wind_max_kmh | 3 | GFS | 6.1995 | 7.8736 | 5.1884 | 3600 | lead_days | 3 |
| wind_max_kmh | 3 | ECMWF IFS | 3.0246 | 3.9955 | -0.7978 | 3600 | lead_days | 3 |
| wind_max_kmh | 3 | ICON | 3.4047 | 4.3501 | -2.3159 | 3600 | lead_days | 3 |
| wind_max_kmh | 3 | AIFS | 3.9652 | 4.9794 | -2.6481 | 3600 | lead_days | 3 |
| wind_max_kmh | 3 | Equal-Weight Mean | 2.6429 | 3.3656 | -0.1434 | 3600 | lead_days | 3 |
| wind_max_kmh | 3 | Best-Single Model | 3.0246 | 3.9955 | -0.7978 | 3600 | lead_days | 3 |
| wind_max_kmh | 3 | Inverse-MAE Blend | 2.5512 | 3.2968 | -0.4136 | 3600 | lead_days | 3 |
| wind_max_kmh | 4 | GFS | 6.2611 | 7.9798 | 5.1532 | 3600 | lead_days | 4 |
| wind_max_kmh | 4 | ECMWF IFS | 3.1448 | 4.1649 | -0.7998 | 3600 | lead_days | 4 |
| wind_max_kmh | 4 | ICON | 3.6517 | 4.6869 | -2.6359 | 3600 | lead_days | 4 |
| wind_max_kmh | 4 | AIFS | 4.0728 | 5.1172 | -2.7225 | 3600 | lead_days | 4 |
| wind_max_kmh | 4 | Equal-Weight Mean | 2.7322 | 3.5304 | -0.2513 | 3600 | lead_days | 4 |
| wind_max_kmh | 4 | Best-Single Model | 3.1448 | 4.1649 | -0.7998 | 3600 | lead_days | 4 |
| wind_max_kmh | 4 | Inverse-MAE Blend | 2.6598 | 3.4728 | -0.474 | 3600 | lead_days | 4 |
| wind_max_kmh | 5 | GFS | 6.0346 | 7.7043 | 4.6859 | 3600 | lead_days | 5 |
| wind_max_kmh | 5 | ECMWF IFS | 3.2634 | 4.2921 | -0.7767 | 3600 | lead_days | 5 |
| wind_max_kmh | 5 | ICON | 3.7964 | 4.8188 | -2.6146 | 3600 | lead_days | 5 |
| wind_max_kmh | 5 | AIFS | 4.1931 | 5.2615 | -2.7444 | 3600 | lead_days | 5 |
| wind_max_kmh | 5 | Equal-Weight Mean | 2.8337 | 3.6564 | -0.3624 | 3600 | lead_days | 5 |
| wind_max_kmh | 5 | Best-Single Model | 3.2634 | 4.2921 | -0.7767 | 3600 | lead_days | 5 |
| wind_max_kmh | 5 | Inverse-MAE Blend | 2.7769 | 3.6077 | -0.5023 | 3600 | lead_days | 5 |
| wind_max_kmh | 6 | GFS | 6.2018 | 7.8357 | 4.7936 | 3600 | lead_days | 6 |
| wind_max_kmh | 6 | ECMWF IFS | 3.6134 | 4.7112 | -1.4173 | 3600 | lead_days | 6 |
| wind_max_kmh | 6 | ICON | 3.7748 | 4.8293 | -2.4432 | 3600 | lead_days | 6 |
| wind_max_kmh | 6 | AIFS | 4.2594 | 5.3589 | -2.6717 | 3600 | lead_days | 6 |
| wind_max_kmh | 6 | Equal-Weight Mean | 2.9422 | 3.8201 | -0.4347 | 3600 | lead_days | 6 |
| wind_max_kmh | 6 | Best-Single Model | 3.6134 | 4.7112 | -1.4173 | 3600 | lead_days | 6 |
| wind_max_kmh | 6 | Inverse-MAE Blend | 2.8691 | 3.7636 | -0.6416 | 3600 | lead_days | 6 |
| wind_max_kmh | 7 | GFS | 6.3807 | 8.1042 | 4.993 | 3600 | lead_days | 7 |
| wind_max_kmh | 7 | ECMWF IFS | 3.7321 | 4.8787 | -1.3861 | 3600 | lead_days | 7 |
| wind_max_kmh | 7 | ICON | nan | nan | nan | 0 | lead_days | 7 |
| wind_max_kmh | 7 | AIFS | 4.3343 | 5.4373 | -2.5593 | 3600 | lead_days | 7 |
| wind_max_kmh | 7 | Equal-Weight Mean | 3.4601 | 4.4132 | 0.3492 | 3600 | lead_days | 7 |
| wind_max_kmh | 7 | Best-Single Model | 3.7321 | 4.8787 | -1.3861 | 3600 | lead_days | 7 |
| wind_max_kmh | 7 | Inverse-MAE Blend | 3.239 | 4.1596 | -0.0234 | 3600 | lead_days | 7 |

## Performance by Region

| variable | region | candidate | mae | rmse | bias | n | slice_type | slice_value |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rain_mm | CENTRAL | GFS | 8.5905 | 15.5923 | -3.9275 | 4410 | region | CENTRAL |
| rain_mm | CENTRAL | ECMWF IFS | 8.3937 | 16.1354 | 1.1362 | 4410 | region | CENTRAL |
| rain_mm | CENTRAL | ICON | 9.5939 | 17.8521 | -0.5399 | 3780 | region | CENTRAL |
| rain_mm | CENTRAL | AIFS | 6.7219 | 11.1146 | 2.7663 | 4410 | region | CENTRAL |
| rain_mm | CENTRAL | Equal-Weight Mean | 6.5248 | 11.0646 | -0.1625 | 4410 | region | CENTRAL |
| rain_mm | CENTRAL | Best-Single Model | 7.5395 | 12.9188 | -0.82 | 4410 | region | CENTRAL |
| rain_mm | CENTRAL | Inverse-MAE Blend | 6.4196 | 10.8168 | 0.0416 | 4410 | region | CENTRAL |
| rain_mm | EAST_NE | GFS | 12.0323 | 20.3491 | -1.8254 | 6300 | region | EAST_NE |
| rain_mm | EAST_NE | ECMWF IFS | 10.2094 | 17.4345 | 0.7494 | 6300 | region | EAST_NE |
| rain_mm | EAST_NE | ICON | 10.7783 | 18.9647 | -0.8283 | 5400 | region | EAST_NE |
| rain_mm | EAST_NE | AIFS | 9.1298 | 14.7115 | 2.5461 | 6300 | region | EAST_NE |
| rain_mm | EAST_NE | Equal-Weight Mean | 8.9159 | 15.4438 | 0.1938 | 6300 | region | EAST_NE |
| rain_mm | EAST_NE | Best-Single Model | 10.181 | 17.172 | -0.0243 | 6300 | region | EAST_NE |
| rain_mm | EAST_NE | Inverse-MAE Blend | 8.8562 | 15.3022 | 0.3204 | 6300 | region | EAST_NE |
| rain_mm | HIMALAYAN | GFS | 9.1976 | 16.0966 | -0.2651 | 3780 | region | HIMALAYAN |
| rain_mm | HIMALAYAN | ECMWF IFS | 7.4888 | 13.6823 | 1.596 | 3780 | region | HIMALAYAN |
| rain_mm | HIMALAYAN | ICON | 7.668 | 13.8685 | -0.3695 | 3240 | region | HIMALAYAN |
| rain_mm | HIMALAYAN | AIFS | 6.4566 | 10.6251 | 1.894 | 3780 | region | HIMALAYAN |
| rain_mm | HIMALAYAN | Equal-Weight Mean | 6.3489 | 10.654 | 0.7672 | 3780 | region | HIMALAYAN |
| rain_mm | HIMALAYAN | Best-Single Model | 7.4435 | 13.041 | 0.6722 | 3780 | region | HIMALAYAN |
| rain_mm | HIMALAYAN | Inverse-MAE Blend | 6.3632 | 10.716 | 0.7302 | 3780 | region | HIMALAYAN |
| rain_mm | NW | GFS | 6.2387 | 13.8086 | -1.8397 | 5670 | region | NW |
| rain_mm | NW | ECMWF IFS | 6.1054 | 13.1526 | 0.7944 | 5670 | region | NW |
| rain_mm | NW | ICON | 7.1878 | 19.904 | 1.6935 | 4860 | region | NW |
| rain_mm | NW | AIFS | 5.5989 | 12.3931 | 2.6162 | 5670 | region | NW |
| rain_mm | NW | Equal-Weight Mean | 5.1847 | 11.4549 | 0.7585 | 5670 | region | NW |
| rain_mm | NW | Best-Single Model | 5.5672 | 12.0158 | 0.1463 | 5670 | region | NW |
| rain_mm | NW | Inverse-MAE Blend | 5.1463 | 11.2935 | 0.7834 | 5670 | region | NW |
| rain_mm | SOUTH | GFS | 5.4583 | 10.8573 | -3.6808 | 5040 | region | SOUTH |
| rain_mm | SOUTH | ECMWF IFS | 4.8461 | 9.3612 | -0.3563 | 5040 | region | SOUTH |
| rain_mm | SOUTH | ICON | 4.65 | 9.5217 | -3.4528 | 4320 | region | SOUTH |
| rain_mm | SOUTH | AIFS | 3.9207 | 6.9512 | 0.2217 | 5040 | region | SOUTH |
| rain_mm | SOUTH | Equal-Weight Mean | 3.93 | 7.9773 | -1.7415 | 5040 | region | SOUTH |
| rain_mm | SOUTH | Best-Single Model | 4.6213 | 9.0403 | -1.5669 | 5040 | region | SOUTH |
| rain_mm | SOUTH | Inverse-MAE Blend | 3.8661 | 7.781 | -1.4896 | 5040 | region | SOUTH |
| tmax_c | CENTRAL | GFS | 1.7446 | 2.3526 | 0.0907 | 4410 | region | CENTRAL |
| tmax_c | CENTRAL | ECMWF IFS | 1.211 | 1.6084 | -0.5853 | 4410 | region | CENTRAL |
| tmax_c | CENTRAL | ICON | 1.5255 | 2.0344 | -0.6777 | 3780 | region | CENTRAL |
| tmax_c | CENTRAL | AIFS | 1.1068 | 1.4311 | -0.6454 | 4410 | region | CENTRAL |
| tmax_c | CENTRAL | Equal-Weight Mean | 1.0663 | 1.4182 | -0.4434 | 4410 | region | CENTRAL |
| tmax_c | CENTRAL | Best-Single Model | 1.1666 | 1.5426 | -0.5524 | 4410 | region | CENTRAL |
| tmax_c | CENTRAL | Inverse-MAE Blend | 1.0435 | 1.3846 | -0.4826 | 4410 | region | CENTRAL |
| tmax_c | EAST_NE | GFS | 2.1545 | 2.7664 | 0.2216 | 6300 | region | EAST_NE |
| tmax_c | EAST_NE | ECMWF IFS | 1.2653 | 1.6137 | -0.6277 | 6300 | region | EAST_NE |
| tmax_c | EAST_NE | ICON | 1.5365 | 1.9965 | -0.7956 | 5400 | region | EAST_NE |
| tmax_c | EAST_NE | AIFS | 0.968 | 1.2538 | -0.4523 | 6300 | region | EAST_NE |
| tmax_c | EAST_NE | Equal-Weight Mean | 1.1309 | 1.457 | -0.3982 | 6300 | region | EAST_NE |
| tmax_c | EAST_NE | Best-Single Model | 1.2056 | 1.5383 | -0.5757 | 6300 | region | EAST_NE |
| tmax_c | EAST_NE | Inverse-MAE Blend | 1.0613 | 1.3687 | -0.4318 | 6300 | region | EAST_NE |
| tmax_c | HIMALAYAN | GFS | 2.7985 | 3.7756 | 1.3963 | 3780 | region | HIMALAYAN |
| tmax_c | HIMALAYAN | ECMWF IFS | 1.3014 | 1.7021 | -0.125 | 3780 | region | HIMALAYAN |
| tmax_c | HIMALAYAN | ICON | 1.5395 | 1.9095 | -0.4131 | 3240 | region | HIMALAYAN |
| tmax_c | HIMALAYAN | AIFS | 1.4971 | 1.8312 | -0.7799 | 3780 | region | HIMALAYAN |
| tmax_c | HIMALAYAN | Equal-Weight Mean | 1.2938 | 1.6913 | 0.0369 | 3780 | region | HIMALAYAN |
| tmax_c | HIMALAYAN | Best-Single Model | 1.3097 | 1.702 | -0.2251 | 3780 | region | HIMALAYAN |
| tmax_c | HIMALAYAN | Inverse-MAE Blend | 1.2206 | 1.5961 | -0.0481 | 3780 | region | HIMALAYAN |
| tmax_c | NW | GFS | 3.0183 | 3.9602 | 2.4 | 5670 | region | NW |
| tmax_c | NW | ECMWF IFS | 1.2856 | 1.6746 | -0.7241 | 5670 | region | NW |
| tmax_c | NW | ICON | 1.4051 | 1.8808 | -0.2055 | 4860 | region | NW |
| tmax_c | NW | AIFS | 1.1176 | 1.4949 | -0.5587 | 5670 | region | NW |
| tmax_c | NW | Equal-Weight Mean | 1.0989 | 1.4884 | 0.2411 | 5670 | region | NW |
| tmax_c | NW | Best-Single Model | 1.2415 | 1.623 | -0.6916 | 5670 | region | NW |
| tmax_c | NW | Inverse-MAE Blend | 0.9843 | 1.3282 | -0.0042 | 5670 | region | NW |
| tmax_c | SOUTH | GFS | 1.7056 | 2.1491 | 0.5691 | 5040 | region | SOUTH |
| tmax_c | SOUTH | ECMWF IFS | 1.327 | 1.7296 | -0.5918 | 5040 | region | SOUTH |
| tmax_c | SOUTH | ICON | 1.1457 | 1.5207 | 0.3555 | 4320 | region | SOUTH |
| tmax_c | SOUTH | AIFS | 1.2583 | 1.573 | -0.8961 | 5040 | region | SOUTH |
| tmax_c | SOUTH | Equal-Weight Mean | 0.9645 | 1.2777 | -0.1714 | 5040 | region | SOUTH |
| tmax_c | SOUTH | Best-Single Model | 1.2866 | 1.6564 | -0.5789 | 5040 | region | SOUTH |
| tmax_c | SOUTH | Inverse-MAE Blend | 0.9594 | 1.2589 | -0.2677 | 5040 | region | SOUTH |
| wind_max_kmh | CENTRAL | GFS | 6.7358 | 7.9495 | 6.3581 | 4410 | region | CENTRAL |
| wind_max_kmh | CENTRAL | ECMWF IFS | 3.2988 | 4.5156 | -0.1393 | 4410 | region | CENTRAL |
| wind_max_kmh | CENTRAL | ICON | 3.6793 | 4.6774 | -2.6902 | 3780 | region | CENTRAL |
| wind_max_kmh | CENTRAL | AIFS | 3.3446 | 4.5093 | -2.2156 | 4410 | region | CENTRAL |
| wind_max_kmh | CENTRAL | Equal-Weight Mean | 2.718 | 3.5233 | 0.4825 | 4410 | region | CENTRAL |
| wind_max_kmh | CENTRAL | Best-Single Model | 3.2988 | 4.5156 | -0.1393 | 4410 | region | CENTRAL |
| wind_max_kmh | CENTRAL | Inverse-MAE Blend | 2.6456 | 3.4986 | 0.17 | 4410 | region | CENTRAL |
| wind_max_kmh | EAST_NE | GFS | 4.5683 | 5.9954 | 2.1129 | 6300 | region | EAST_NE |
| wind_max_kmh | EAST_NE | ECMWF IFS | 3.3531 | 4.4134 | -2.1167 | 6300 | region | EAST_NE |
| wind_max_kmh | EAST_NE | ICON | 4.3035 | 5.3057 | -3.7115 | 5400 | region | EAST_NE |
| wind_max_kmh | EAST_NE | AIFS | 4.5563 | 5.4879 | -4.0727 | 6300 | region | EAST_NE |
| wind_max_kmh | EAST_NE | Equal-Weight Mean | 2.8751 | 3.7427 | -1.8837 | 6300 | region | EAST_NE |
| wind_max_kmh | EAST_NE | Best-Single Model | 3.3531 | 4.4134 | -2.1167 | 6300 | region | EAST_NE |
| wind_max_kmh | EAST_NE | Inverse-MAE Blend | 2.8419 | 3.7134 | -1.7782 | 6300 | region | EAST_NE |
| wind_max_kmh | HIMALAYAN | GFS | 3.8239 | 5.5604 | 2.5187 | 3780 | region | HIMALAYAN |
| wind_max_kmh | HIMALAYAN | ECMWF IFS | 2.7408 | 3.4405 | -2.1828 | 3780 | region | HIMALAYAN |
| wind_max_kmh | HIMALAYAN | ICON | 2.7989 | 3.5367 | -0.6039 | 3240 | region | HIMALAYAN |
| wind_max_kmh | HIMALAYAN | AIFS | 4.1395 | 4.7547 | -4.111 | 3780 | region | HIMALAYAN |
| wind_max_kmh | HIMALAYAN | Equal-Weight Mean | 2.0784 | 2.8025 | -1.129 | 3780 | region | HIMALAYAN |
| wind_max_kmh | HIMALAYAN | Best-Single Model | 2.7408 | 3.4405 | -2.1828 | 3780 | region | HIMALAYAN |
| wind_max_kmh | HIMALAYAN | Inverse-MAE Blend | 2.0528 | 2.7667 | -0.9493 | 3780 | region | HIMALAYAN |
| wind_max_kmh | NW | GFS | 9.5771 | 11.0421 | 9.3157 | 5670 | region | NW |
| wind_max_kmh | NW | ECMWF IFS | 2.9347 | 3.9705 | 0.0567 | 5670 | region | NW |
| wind_max_kmh | NW | ICON | 3.1904 | 4.1673 | -2.0756 | 4860 | region | NW |
| wind_max_kmh | NW | AIFS | 4.0325 | 5.0904 | -0.8216 | 5670 | region | NW |
| wind_max_kmh | NW | Equal-Weight Mean | 3.115 | 3.947 | 1.7982 | 5670 | region | NW |
| wind_max_kmh | NW | Best-Single Model | 2.9347 | 3.9705 | 0.0567 | 5670 | region | NW |
| wind_max_kmh | NW | Inverse-MAE Blend | 2.7594 | 3.6022 | 0.8205 | 5670 | region | NW |
| wind_max_kmh | SOUTH | GFS | 5.8054 | 7.1377 | 4.771 | 5040 | region | SOUTH |
| wind_max_kmh | SOUTH | ECMWF IFS | 3.3107 | 4.3389 | -0.6411 | 5040 | region | SOUTH |
| wind_max_kmh | SOUTH | ICON | 3.4167 | 4.3627 | -2.6528 | 4320 | region | SOUTH |
| wind_max_kmh | SOUTH | AIFS | 4.0305 | 5.3621 | -2.1656 | 5040 | region | SOUTH |
| wind_max_kmh | SOUTH | Equal-Weight Mean | 2.8659 | 3.5984 | -0.0559 | 5040 | region | SOUTH |
| wind_max_kmh | SOUTH | Best-Single Model | 3.3107 | 4.3389 | -0.6411 | 5040 | region | SOUTH |
| wind_max_kmh | SOUTH | Inverse-MAE Blend | 2.855 | 3.5942 | -0.1983 | 5040 | region | SOUTH |