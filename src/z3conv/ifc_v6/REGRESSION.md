# ifc2step5 vs ifc2step6 regression (81 models)

## class before -> after (all models)

| v5 class | v6 class | models |
|---|---|---|
| 1 | 1 | 11 |
| 1 | 2 | 2 |
| 1 | None | 1 |
| 2 | 1 | 14 |
| 2 | 2 | 51 |
| 2 | None | 1 |
| 3 | None | 1 |

## by test group (stratum of the live class-2 reason)

| group | models | v5 class 1/2/3 | v6 class 1/2/3 |
|---|---|---|---|
| bbox3 | 1 | 0/0/1 | 0/0/0 |
| control | 12 | 6/6/0 | 4/7/0 |
| inv+nonpos | 6 | 0/6/0 | 1/5/0 |
| inv+nonpos+vol | 3 | 0/3/0 | 1/2/0 |
| inv+vol | 1 | 0/1/0 | 1/0/0 |
| inv-big | 1 | 0/1/0 | 0/1/0 |
| invalid | 3 | 0/3/0 | 3/0/0 |
| large | 9 | 0/9/0 | 0/9/0 |
| nonpos | 6 | 0/6/0 | 3/3/0 |
| nonpos+vol | 1 | 0/1/0 | 0/1/0 |
| schema:IFC2X2_FINAL | 6 | 0/6/0 | 0/6/0 |
| schema:IFC4 | 2 | 2/0/0 | 2/0/0 |
| schema:ZIP | 21 | 3/18/0 | 7/13/0 |
| vol | 9 | 3/6/0 | 3/6/0 |

## reasons (models carrying each)

| reason | v5 | v6 |
|---|---|---|
| bbox_absurd (corrupt source coordinates) | 1 | 0 |
| invalid_solids | 26 | 0 |
| non_positive_volume_solids | 31 | 0 |
| not_read_back_large_file | 12 | 0 |
| parts_outside_volume_tolerance | 1 | 1 |
| parts_without_solid | 39 | 44 |
| per_part_verification_pending | 12 | 0 |

## per model

| group | id | schema | IFC MB | v5 class / reasons | v6 class / reasons | v5 STEP MB | v6 STEP MB | v5 s | v6 s | v6 read-back | v6 levels | v6 tags |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bbox3 | 4efa1dc5f109 | IFC2X3 | 102.6 | 3 bbox_absurd (corrupt source coordinates) | n/a | 0.0 |  | 334.8 |  |  |  |  |
| control | 1607aaaa774d | IFC2X3 | 99.6 | 2 parts_without_solid | 2 parts_without_solid | 177.9 | 124.0 | 253.7 | 1711.0 | occ_readback | {"L0": 7377, "L4": 64} | L4-surface:64, components:4673, instanced:5157, open-surface:66, open_in_source:64, sewn:12 |
| control | 132338901dd3 | IFC2X3 | 49.7 | 2 parts_without_solid | 2 parts_without_solid | 8.5 | 56.2 | 14.1 | 317.2 | occ_readback | {"L0": 1358, "L4": 1} | L4-surface:1, components:134, instanced:415, open_in_source:1 |
| control | 0933b1c14211 | IFC2X3 | 39.4 | 2 parts_without_solid | 2 parts_without_solid | 92.7 | 40.0 | 156.0 | 152.9 | occ_readback | {"L0": 14834, "L2": 20, "L4": 10} | L2-alt-source:20, L4-surface:10, components:216, instanced:12054, open-surface:216, open_in_source:36, sewn:5, tjunction:10 |
| control | 0fc26e2e3194 | IFC2X3 | 20.5 | 1  | n/a | 1.1 |  | 3.6 |  |  |  |  |
| control | 015071d4bc56 | IFC2X3 | 14.7 | 2 parts_without_solid | 2 parts_without_solid | 30.2 | 14.4 | 44.4 | 122.3 | occ_readback | {"L0": 4381, "L4": 1} | L4-surface:1, components:547, instanced:3583, open-surface:1, open_in_source:1, sewn:4 |
| control | 16d9debe4b5e | IFC2X3 | 13.1 | 2 parts_without_solid | 2 parts_without_solid | 47.5 | 15.0 | 78.4 | 157.0 | occ_readback | {"L0": 889, "L4": 7} | L4-surface:7, components:97, instanced:683, open_in_source:7 |
| control | 09d2d25a4679 | IFC2X3 | 6.4 | 2 parts_without_solid | 2 parts_without_solid | 21.3 | 6.5 | 40.8 | 96.9 | occ_readback | {"L0": 111, "L4": 2} | L4-surface:2, approx-curved:11, components:1, instanced:97, open_in_source:2, sewn:1 |
| control | 0ca4e1bdc082 | IFC2X3 | 4.5 | 1  | 1  | 23.2 | 17.9 | 41.3 | 366.4 | occ_readback | {"L0": 1336} | components:838, instanced:855 |
| control | 191bb540dec0 | IFC2X3 | 1.8 | 1  | 1  | 5.3 | 1.9 | 10.2 | 11.8 | occ_readback | {"L0": 383} | instanced:366 |
| control | 019e0c5c9dcc | IFC2X3 | 0.4 | 1  | 2  | 1.0 | 1.0 | 2.6 | 21.3 | occ_readback | {"L0": 46} | components:4, instanced:15, open-surface:4 |
| control | 075087d6664d | IFC2X3 | 0.1 | 1  | 1  | 0.7 | 0.2 | 2.1 | 2.5 | occ_readback | {"L0": 36} | approx-curved:22, instanced:26 |
| control | 04fe149b85aa | IFC2X3 | 0.0 | 1  | 1  | 0.0 | 0.0 | 1.0 | 3.3 | occ_readback | {"L0": 7} | instanced:6 |
| inv+nonpos | 078ad510afa4 | IFC2X3 | 16.7 | 2 invalid_solids,non_positive_volume_solids,parts_without_solid | 2 parts_without_solid | 113.0 | 30.7 | 180.7 | 104.4 | occ_readback | {"L0": 3215, "L3": 6, "L1": 3, "L4": 1} | L1-triangulated:3, L3-partial-surface:6, L4-surface:1, components:520, double-sided:110, instanced:2657, open-surface:116, open_in_source:1, reoriented:74, sewn |
| inv+nonpos | 112634d7353a | IFC2X3 | 8.9 | 2 invalid_solids,non_positive_volume_solids | 2  | 52.4 | 13.7 | 79.5 | 134.7 | occ_readback | {"L0": 3328} | components:112, instanced:2779, open-surface:2 |
| inv+nonpos | 14733a78c914 | IFC2X3 | 5.0 | 2 invalid_solids,non_positive_volume_solids,parts_without_solid | 2 parts_without_solid | 23.9 | 14.3 | 51.1 | 88.4 | occ_readback | {"L0": 1107, "L4": 3} | L4-surface:3, components:584, instanced:646, open_in_source:3 |
| inv+nonpos | 0e92449b5da0 | IFC2X3 | 3.2 | 2 invalid_solids,non_positive_volume_solids,parts_without_solid | 2 parts_without_solid | 13.9 | 5.8 | 23.1 | 68.7 | occ_readback | {"L0": 584, "L1": 3, "L2": 5, "L4": 1} | L1-triangulated:3, L2-alt-source:5, L4-surface:1, approx-curved:120, components:109, instanced:419, open-surface:7, open_in_source:8, sewn:7, tjunction:2 |
| inv+nonpos | 09cbd0b87516 | IFC2X3 | 1.5 | 2 invalid_solids,non_positive_volume_solids | 2  | 6.5 | 1.2 | 11.8 | 6.9 | occ_readback | {"L0": 229} | components:11, double-sided:8, instanced:188, open-surface:8, reoriented:8, sewn:8, tjunction:8 |
| inv+nonpos | ddaae9f3feba | ZIP:ISO-10303-21.txt | 0.5 | 2 invalid_solids,non_positive_volume_solids | 1  | 15.4 | 11.0 | 29.8 | 67.1 | occ_readback | {"L0": 719} | components:397, instanced:546 |
| inv+nonpos+vol | 0a84f0b13e40 | IFC2X3 | 7.9 | 2 invalid_solids,non_positive_volume_solids,parts_without_solid | 2 parts_without_solid | 66.6 | 22.8 | 110.3 | 233.4 | occ_readback | {"L0": 2429, "L4": 2} | L4-surface:2, approx-curved:784, components:710, instanced:1661, open-surface:1, open_in_source:2, sewn:2, tjunction:1 |
| inv+nonpos+vol | 1481043e986c | IFC2X3 | 0.8 | 2 invalid_solids,non_positive_volume_solids,parts_outside_volume_tolerance | 2  | 4.4 | 2.6 | 5.2 | 32.4 | occ_readback | {"L0": 334} | approx-curved:141, components:37, instanced:18, open-surface:12 |
| inv+nonpos+vol | 0bb09346e290 | IFC2X3 | 0.5 | 2 invalid_solids,non_positive_volume_solids | 1  | 4.5 | 1.4 | 9.3 | 17.2 | occ_readback | {"L0": 178} | approx-curved:95, components:27, instanced:115 |
| inv+vol | 055b208a3929 | IFC2X3 | 3.7 | 2 invalid_solids,parts_without_solid | 1  | 17.0 | 5.0 | 28.2 | 22.2 | occ_readback | {"L0": 1215} | approx-curved:259, components:86, instanced:968, sewn:12 |
| inv-big | 00ef40cace1c | IFC2X3 | 49.6 | 2 invalid_solids,parts_without_solid | 2 parts_without_solid | 192.4 | 63.5 | 326.3 | 225.8 | occ_readback | {"L0": 16609, "L4": 22, "L2": 3} | L2-alt-source:3, L4-surface:22, components:466, instanced:13167, open-surface:4, open_in_source:28, sewn:7, tjunction:3 |
| invalid | 0f73ae81d37e | IFC2X3 | 3.5 | 2 invalid_solids,parts_without_solid | 1  | 34.8 | 3.9 | 55.6 | 73.9 | occ_readback | {"L0": 540} | components:88, double-sided:49, instanced:420, reoriented:36, sewn:4, tjunction:36 |
| invalid | 16a555243e17 | IFC2X3 | 3.3 | 2 invalid_solids,parts_without_solid | 1  | 34.3 | 3.8 | 54.8 | 78.4 | occ_readback | {"L0": 502} | components:58, double-sided:49, instanced:382, reoriented:36, sewn:4, tjunction:36 |
| invalid | 122158cb8d96 | IFC2X3 | 1.2 | 2 invalid_solids | 1  | 2.8 | 1.8 | 6.0 | 9.9 | occ_readback | {"L0": 287} | components:32, instanced:222 |
| large | 18ff6c83da32 | IFC2X3 | 342.5 | 2 not_read_back_large_file,per_part_verification_pending | 2 parts_without_solid | 3397.9 | 677.3 | 542.2 | 2349.9 | occ_readback | {"L0": 13651, "L4": 9, "L2": 8} | L2-alt-source:8, L4-surface:9, approx-curved:1005, components:23, instanced:11593, open-surface:21, open_in_source:21, sewn:62, tjunction:83 |
| large | 020fcf5a0ea1 | IFC2X3 | 339.2 | 2 not_read_back_large_file,per_part_verification_pending | 2 parts_without_solid | 3474.0 | 775.7 | 555.1 | 2503.4 | occ_readback | {"L0": 13632, "L4": 9, "L2": 8} | L2-alt-source:8, L4-surface:9, approx-curved:1032, components:23, instanced:11411, open-surface:21, open_in_source:21, sewn:62, tjunction:81 |
| large | 0eba5980e5aa | IFC2X3 | 298.3 | 2 not_read_back_large_file,per_part_verification_pending | 2 parts_without_solid | 3068.7 | 449.8 | 477.7 | 2039.5 | occ_readback | {"L0": 13002, "L4": 9, "L2": 8} | L2-alt-source:8, L4-surface:9, approx-curved:1392, components:41, instanced:11298, open-surface:39, open_in_source:39, sewn:63, tjunction:123, void:1 |
| large | 03101a532d0d | IFC2X3 | 258.7 | 2 not_read_back_large_file,per_part_verification_pending | 2 parts_without_solid | 1995.8 | 227.3 | 319.6 | 637.0 | occ_readback | {"L0": 30011, "L4": 22, "L3": 39, "L2": 1, "L1": 3} | L1-triangulated:3, L2-alt-source:1, L3-partial-surface:39, L4-surface:22, components:9604, double-sided:24594, instanced:23031, open-surface:23317, open_in_sour |
| large | 0b3b8b2f2335 | IFC2X3 | 170.7 | 2 not_read_back_large_file,per_part_verification_pending | 2 parts_outside_volume_tolerance,parts_without_solid | 1192.6 | 640.6 | 192.6 | 1800.0 | occ_readback | {"L0": 13723, "L2": 1, "L4": 2} | L2-alt-source:1, L4-surface:2, approx-curved:509, components:92, instanced:4497, open-surface:11, open_in_source:24, sewn:2, tjunction:4 |
| large | 0f2685e378a4 | IFC2X3 | 124.7 | 2 not_read_back_large_file,per_part_verification_pending | 2 parts_without_solid | 1312.3 | 494.1 | 1235.7 | 2448.2 | occ_readback | {"L0": 13174, "L4": 13} | L4-surface:13, components:1152, instanced:3992, open-surface:2, open_in_source:13, sewn:6, tjunction:2 |
| large | 085ebca9cbdd | IFC2X3 | 90.1 | 2 not_read_back_large_file,per_part_verification_pending | 2 parts_without_solid | 1112.1 | 265.0 | 207.7 | 924.2 | occ_readback | {"L0": 23469, "L4": 127, "L3": 12} | L3-partial-surface:12, L4-surface:127, approx-curved:9675, components:8074, instanced:17426, open-surface:144, open_in_source:128, sewn:61, void:12 |
| large | 17866fae69fc | IFC2X3 | 73.7 | 2 not_read_back_large_file,per_part_verification_pending | 2 parts_without_solid | 1160.8 | 318.8 | 257.5 | 1216.2 | occ_readback | {"L0": 36694, "L2": 16, "L4": 16} | L2-alt-source:16, L4-surface:16, approx-curved:10627, components:11819, instanced:27335, open-surface:49, open_in_source:33, sewn:84, tjunction:17, void:2 |
| large | 1924e526e9c8 | IFC2X3 | 63.4 | 2 not_read_back_large_file,per_part_verification_pending | 2  | 1398.3 | 410.1 | 334.6 | 1524.4 | occ_readback | {"L0": 34893} | approx-curved:13641, components:15931, instanced:25637, open-surface:2, sewn:5 |
| nonpos | 081327319530 | IFC2X3 | 22.0 | 2 non_positive_volume_solids,parts_without_solid | 2 parts_without_solid | 141.8 | 25.4 | 236.7 | 364.3 | occ_readback | {"L0": 11423, "L4": 2} | L4-surface:2, approx-curved:4, components:3368, instanced:10200, open-surface:2, open_in_source:2, sewn:1 |
| nonpos | 1199dffb1a2b | IFC2X3 | 14.0 | 2 non_positive_volume_solids | 1  | 80.6 | 60.0 | 151.9 | 418.1 | occ_readback | {"L0": 3428} | components:2365, instanced:2604 |
| nonpos | 0fbdc222bdf9 | IFC2X3 | 7.9 | 2 non_positive_volume_solids,parts_without_solid | 2 parts_without_solid | 42.3 | 24.7 | 80.9 | 163.4 | occ_readback | {"L0": 2139, "L4": 1} | L4-surface:1, components:1258, instanced:1592, open_in_source:1 |
| nonpos | 0e2f64077ad1 | IFC2X3 | 2.7 | 2 non_positive_volume_solids,parts_without_solid | 2 parts_without_solid | 8.8 | 3.0 | 15.4 | 46.2 | occ_readback | {"L0": 445} | components:35, instanced:390, open-surface:21, open_in_source:2, sewn:2 |
| nonpos | 105766e3503f | IFC2X3 | 0.6 | 2 non_positive_volume_solids | 1  | 4.8 | 0.5 | 9.2 | 23.6 | occ_readback | {"L0": 497} | components:388, instanced:485 |
| nonpos | 14e58e8a4c58 | IFC2X3 | 0.1 | 2 non_positive_volume_solids | 1  | 0.2 | 0.2 | 1.4 | 3.5 | occ_readback | {"L0": 14} | components:5, instanced:5 |
| nonpos+vol | 0b21dd350696 | IFC2X3 | 10.9 | 2 non_positive_volume_solids,parts_without_solid | 2 parts_without_solid | 153.7 | 38.2 | 311.4 | 195.8 | occ_readback | {"L0": 3154, "L4": 20} | L4-surface:20, approx-curved:732, components:1966, instanced:2323, open-surface:1, open_in_source:20, sewn:12 |
| schema:IFC2X2_FINAL | 6ca8c04a5c98 | IFC2X2_FINAL | 269.3 | 2 not_read_back_large_file,per_part_verification_pending | 2 parts_without_solid | 2995.5 | 776.5 | 504.7 | 3087.2 | occ_readback | {"L0": 12205, "L2": 39} | L2-alt-source:39, approx-curved:437, components:27, instanced:6377, open-surface:6, open_in_source:15, reoriented:1, tjunction:114 |
| schema:IFC2X2_FINAL | ece055a1bf72 | IFC2X2_FINAL | 147.4 | 2 parts_without_solid | 2 parts_without_solid | 310.9 | 222.5 | 477.3 | 544.5 | occ_readback | {"L0": 2198, "L2": 1, "L3": 1} | L2-alt-source:1, L3-partial-surface:1, approx-curved:952, components:5, instanced:24 |
| schema:IFC2X2_FINAL | f8ec65870568 | IFC2X2_FINAL | 63.5 | 2 invalid_solids,non_positive_volume_solids,parts_without_solid | 2 parts_without_solid | 132.1 | 59.8 | 211.1 | 241.3 | occ_readback | {"L0": 6656, "L4": 5, "L2": 7} | L2-alt-source:7, L4-surface:5, approx-curved:58, components:25, instanced:1614, open-surface:4, open_in_source:5, sewn:8, tjunction:4 |
| schema:IFC2X2_FINAL | 3cb7e6a1d373 | IFC2X2_FINAL | 11.3 | 2 parts_without_solid | 2 parts_without_solid | 51.4 | 21.6 | 71.7 | 123.3 | occ_readback | {"L0": 1672} | approx-curved:1133, instanced:155 |
| schema:IFC2X2_FINAL | 83134afa6b20 | IFC2X2_FINAL | 7.8 | 2 invalid_solids | 2 parts_without_solid | 6.3 | 6.5 | 11.1 | 18.5 | occ_readback | {"L0": 1306, "L2": 2, "L4": 1} | L2-alt-source:2, L4-surface:1, components:5, open-surface:2, reoriented:1, tjunction:2 |
| schema:IFC2X2_FINAL | d9ae2e49946a | IFC2X2_FINAL | 7.8 | 2 invalid_solids | 2 parts_without_solid | 6.3 | 6.5 | 11.1 | 45.2 | occ_readback | {"L0": 1306, "L2": 2, "L4": 1} | L2-alt-source:2, L4-surface:1, components:5, open-surface:2, reoriented:1, tjunction:2 |
| schema:IFC4 | cdb0c35e2c6b | IFC4 | 1.2 | 1  | 1  | 6.3 | 0.2 | 9.6 | 15.4 | occ_readback | {"L0": 144} | instanced:143 |
| schema:IFC4 | d5e2fc66e9f4 | IFC4 | 0.0 | 1  | 1  | 0.0 | 0.0 | 1.1 | 1.9 | occ_readback | {"L0": 4} | instanced:4 |
| schema:ZIP | beeeacea7d2d | ZIP:ISO-10303-21.txt | 18.9 | 2 not_read_back_large_file,per_part_verification_pending | n/a | 1154.1 |  | 204.1 |  |  |  |  |
| schema:ZIP | 1c61df42e527 | ZIP:ISO-10303-21.txt | 14.0 | 2 not_read_back_large_file,per_part_verification_pending | 2 parts_without_solid | 1388.8 | 502.8 | 766.3 | 3667.4 | occ_readback | {"L0": 26683, "L4": 540} | L4-surface:540, approx-curved:21679, components:6160, instanced:9970, open-surface:527, open_in_source:540 |
| schema:ZIP | 8759e3c31104 | ZIP:ISO-10303-21.txt | 6.7 | 2 invalid_solids,non_positive_volume_solids,parts_without_solid | 2 parts_without_solid | 661.2 | 202.7 | 1212.8 | 864.6 | occ_readback | {"L4": 59, "L0": 17072, "L1": 1, "L2": 3} | L1-triangulated:1, L2-alt-source:3, L4-surface:59, approx-curved:2326, components:8421, instanced:13249, open-surface:1, open_in_source:62, sewn:26, tjunction:1 |
| schema:ZIP | e2570f7a33f0 | ZIP:ISO-10303-21.txt | 2.9 | 2 non_positive_volume_solids | 1  | 231.8 | 191.0 | 408.5 | 429.7 | occ_readback | {"L0": 5122} | components:1457, instanced:3567 |
| schema:ZIP | be399c739698 | ZIP:ISO-10303-21.txt | 2.1 | 2 non_positive_volume_solids,parts_without_solid | 2 parts_without_solid | 12.6 | 83.1 | 22.6 | 1172.2 | occ_readback | {"L0": 2167, "L4": 47} | L4-surface:47, components:129, instanced:957, open_in_source:47, sewn:3, tjunction:10 |
| schema:ZIP | 10350b347f19 | ZIP:ISO-10303-21.txt | 1.6 | 2 invalid_solids,non_positive_volume_solids,parts_without_solid | 2 parts_without_solid | 35.9 | 20.7 | 65.6 | 363.4 | occ_readback | {"L0": 2483, "L4": 1} | L4-surface:1, components:711, instanced:1700, open-surface:1, open_in_source:1, sewn:1, tjunction:1 |
| schema:ZIP | 1874367bb71a | ZIP:ISO-10303-21.txt | 1.5 | 2 parts_without_solid | 2 parts_without_solid | 28.7 | 13.9 | 50.9 | 211.3 | occ_readback | {"L0": 1465, "L4": 2} | L4-surface:2, components:393, instanced:1073, open-surface:75, open_in_source:2 |
| schema:ZIP | 48cbb9528580 | ZIP:ISO-10303-21.txt | 1.4 | 2 parts_without_solid | 2 parts_without_solid | 28.4 | 15.6 | 50.3 | 153.2 | occ_readback | {"L0": 1384, "L4": 2, "L2": 1} | L2-alt-source:1, L4-surface:2, components:393, instanced:974, open-surface:75, open_in_source:2 |
| schema:ZIP | 7e197e4d1de8 | ZIP:ISO-10303-21.txt | 1.1 | 2 invalid_solids,non_positive_volume_solids,parts_without_solid | 2 parts_without_solid | 29.4 | 22.5 | 54.7 | 113.4 | occ_readback | {"L0": 1441, "L4": 2} | L4-surface:2, components:754, instanced:1030, open-surface:1, open_in_source:2, sewn:1 |
| schema:ZIP | ff3e47295fe8 | ZIP:ISO-10303-21.txt | 0.9 | 2 invalid_solids,non_positive_volume_solids,parts_without_solid | 2 parts_without_solid | 51.0 | 8.1 | 83.6 | 156.9 | occ_readback | {"L0": 2112, "L2": 2, "L1": 1, "L4": 1} | L1-triangulated:1, L2-alt-source:2, L4-surface:1, components:184, double-sided:36, instanced:1866, open-surface:38, open_in_source:1, reoriented:36, sewn:36, tj |
| schema:ZIP | 91883af31876 | ZIP:ISO-10303-21.txt | 0.8 | 2 invalid_solids,non_positive_volume_solids,parts_without_solid | 2 parts_without_solid | 34.6 | 18.4 | 62.4 | 333.3 | occ_readback | {"L4": 1, "L0": 1499} | L4-surface:1, components:1100, instanced:1290, open_in_source:1 |
| schema:ZIP | 0c5f518af190 | ZIP:ISO-10303-21.txt | 0.7 | 1  | 1  | 9.0 | 5.8 | 16.2 | 21.1 | occ_readback | {"L0": 457} | components:76, instanced:271 |
| schema:ZIP | 4ea78faae2b2 | ZIP:ISO-10303-21.txt | 0.5 | 2 invalid_solids,non_positive_volume_solids | 1  | 18.4 | 7.8 | 34.5 | 59.8 | occ_readback | {"L0": 853} | components:536, instanced:689 |
| schema:ZIP | e4901c30087b | ZIP:ISO-10303-21.txt | 0.5 | 2 non_positive_volume_solids,parts_without_solid | 1  | 40.9 | 12.9 | 70.8 | 136.6 | occ_readback | {"L0": 1058} | approx-curved:291, components:454, instanced:769 |
| schema:ZIP | f2e8cf74a202 | ZIP:ISO-10303-21.txt | 0.5 | 2 invalid_solids,non_positive_volume_solids,parts_without_solid | 2  | 14.3 | 3.5 | 23.4 | 12.3 | occ_readback | {"L0": 297} | approx-curved:50, components:30, double-sided:14, instanced:199, open-surface:15, reoriented:4, sewn:15, tjunction:14 |
| schema:ZIP | f50a5baaf9de | ZIP:ISO-10303-21.txt | 0.2 | 2 invalid_solids,non_positive_volume_solids,parts_without_solid | 2  | 19.0 | 6.6 | 31.7 | 61.4 | occ_readback | {"L0": 172, "L1": 1, "L3": 1} | L1-triangulated:1, L3-partial-surface:1, approx-curved:34, components:58, double-sided:26, instanced:107, open-surface:26, reoriented:8, sewn:26, tjunction:26 |
| schema:ZIP | 2247ee6192c7 | ZIP:ISO-10303-21.txt | 0.2 | 1  | 1  | 7.5 | 2.5 | 14.3 | 21.1 | occ_readback | {"L0": 337} | components:260, instanced:280 |
| schema:ZIP | 5d45eacd762e | ZIP:ISO-10303-21.txt | 0.1 | 2 invalid_solids,non_positive_volume_solids,parts_without_solid | 2  | 5.4 | 1.8 | 9.3 | 32.4 | occ_readback | {"L0": 146} | components:15, double-sided:6, instanced:91, open-surface:7, reoriented:6, sewn:6, tjunction:6 |
| schema:ZIP | bda4d8948095 | ZIP:ISO-10303-21.txt | 0.1 | 2 non_positive_volume_solids | 2  | 2.0 | 1.2 | 4.6 | 21.1 | occ_readback | {"L0": 92} | components:63, instanced:70, open-surface:1 |
| schema:ZIP | e5a81c9a8f2a | ZIP:ISO-10303-21.txt | 0.1 | 2 non_positive_volume_solids | 1  | 3.9 | 1.6 | 8.2 | 16.5 | occ_readback | {"L0": 102} | approx-curved:33, components:22, instanced:51 |
| schema:ZIP | 7b0bb2c84146 | ZIP:ISO-10303-21.txt | 0.0 | 1  | 1  | 0.4 | 0.2 | 1.6 | 3.1 | occ_readback | {"L0": 28} | components:8, instanced:20 |
| vol | 0645b1a6f7d9 | IFC2X3 | 14.5 | 2 parts_without_solid | 2 parts_without_solid | 163.6 | 53.7 | 347.8 | 317.9 | occ_readback | {"L0": 3744} | components:2856, instanced:2917, open-surface:1, sewn:2 |
| vol | 043fe447e557 | IFC2X3 | 12.4 | 1  | 2 parts_without_solid | 204.3 | 54.5 | 426.3 | 347.8 | occ_readback | {"L0": 3706, "L4": 1} | L4-surface:1, components:2597, instanced:2649, open_in_source:1, sewn:24 |
| vol | 052153fe1036 | IFC2X3 | 3.4 | 2 parts_without_solid | 2 parts_without_solid | 145.5 | 8.3 | 196.5 | 65.7 | occ_readback | {"L0": 3010, "L4": 3} | L4-surface:3, approx-curved:2378, components:114, instanced:2877, open_in_source:3, sewn:4 |
| vol | 09f2c71cfe34 | IFC2X3 | 3.3 | 2 parts_without_solid | 2 parts_without_solid | 143.6 | 6.2 | 192.8 | 57.4 | occ_readback | {"L0": 2961, "L4": 4} | L4-surface:4, approx-curved:2402, components:84, instanced:2712, open_in_source:4, sewn:4 |
| vol | 19f6ca4aee01 | IFC2X3 | 2.3 | 2 parts_without_solid | 2 parts_without_solid | 21.1 | 4.0 | 32.8 | 20.7 | occ_readback | {"L0": 890, "L4": 1} | L4-surface:1, approx-curved:267, instanced:785, open_in_source:1, sewn:15, tjunction:12 |
| vol | 0e047d170568 | IFC2X3 | 1.4 | 1  | 1  | 22.6 | 5.6 | 47.8 | 35.9 | occ_readback | {"L0": 670} | components:134, instanced:547, sewn:1 |
| vol | 1595a90990fc | IFC2X3 | 0.9 | 2 parts_without_solid | 2 parts_without_solid | 11.7 | 3.3 | 17.8 | 15.7 | occ_readback | {"L0": 319, "L4": 3} | L4-surface:3, approx-curved:224, components:36, instanced:254, open_in_source:8, sewn:2 |
| vol | 054e6f2eff2b | IFC2X3 | 0.8 | 1  | 1  | 5.9 | 1.8 | 10.9 | 8.1 | occ_readback | {"L0": 251} | approx-curved:100, components:60, instanced:188 |
| vol | 07bbae17b550 | IFC2X3 | 0.3 | 2 parts_without_solid | 1  | 2.0 | 0.5 | 4.6 | 4.4 | occ_readback | {"L0": 123} | approx-curved:32, components:32, instanced:108, sewn:2, tjunction:2 |

## regressions (v6 class worse than v5): 2

- control 019e0c5c9dcccc7c: v5 1  -> v6 2 
- vol 043fe447e5579f31: v5 1  -> v6 2 parts_without_solid

## 6.1.5-adjusted classes (tag change only: parts tagged open-surface that hold a solid count as stray-faces)

| v5 class | v6.1.5 class | models |
|---|---|---|
| 1 | 1 | 12 |
| 1 | 2 | 1 |
| 2 | 1 | 21 |
| 2 | 2 | 44 |

Totals over 78 models graded in both runs: v5 class 1/2/3 = 13/65/0; v6.1.5 = 33/45/0.

| group | v5 1/2/3 | v6.1.5 1/2/3 |
|---|---|---|
| control | 5/6/0 | 5/6/0 |
| inv+nonpos | 0/6/0 | 3/3/0 |
| inv+nonpos+vol | 0/3/0 | 2/1/0 |
| inv+vol | 0/1/0 | 1/0/0 |
| inv-big | 0/1/0 | 0/1/0 |
| invalid | 0/3/0 | 3/0/0 |
| large | 0/9/0 | 1/8/0 |
| nonpos | 0/6/0 | 3/3/0 |
| nonpos+vol | 0/1/0 | 0/1/0 |
| schema:IFC2X2_FINAL | 0/6/0 | 0/6/0 |
| schema:IFC4 | 2/0/0 | 2/0/0 |
| schema:ZIP | 3/17/0 | 10/10/0 |
| vol | 3/6/0 | 3/6/0 |

STEP size total: v5 26.39 GB -> v6 7.22 GB; wall time (conversion + grader read-back, 2 boxes, shared load) total: v5 202 min -> v6 560 min.
Read back by OCC (whole file, grader): v5 67/78, v6 78/78.

Regressions after the 6.1.5 tag change: 1
- vol 043fe447e5579f31: v5 1 -> v6 2 ['parts_without_solid:1']. IfcBeam B_110 is an IfcFacetedBrep with 4 openings: v5 wrote it without the openings (valid but uncut - the audit's "class 1 with uncut openings"); v6 applies them, the kernel boolean returns an open mesh -> tagged L4 surface.

Not graded in both runs: 4efa1dc5 (grader read-back of the 970 MB STEP still running; converter: 124,556 parts, 0 missing, 2 corrupt bolts excluded - was class 3 bbox_absurd), 0fc26e2e (control, read-back running), beeeacea / Seaport (grader read-back of the 585 MB STEP > 90 min; converter: 49,162/49,162 parts, verify final_failed 0).

Grader kit: the live kit at run time (step_check, ifc_census, grade_join, worker) with my copy of build_index classify_ifc; v5 = ifc2step5.py graded with the same kit (v5n run), v6 = ifc2step6 6.1.3 (6.1.4 output identical except memory handling; 6.1.5 tag change applied as above).

## 6.1.8 / 6.1.9 fleet canaries (2026-10-02)

Same fleet worker and grader for both versions (best-of off for the comparison); per model class from the builder's
classify_ifc on each run's result.json (/tmp/v6/canary/compare.py, compare2.py).

| canary | models compared | class 2 -> 1 | regressions | controls | tag totals |
|---|---|---|---|---|---|
| 6.1.7 vs 6.1.8-rc (122: 30 L1-only, 62 OIS-only, 18 pipeline, 12 controls) | 116 | 19 | 0 | 5 x class 1, 6 x class 2 (unchanged) | L1 50 -> 31, open_in_source 64 -> 40, L4 2,019 -> 1,896 |
| 6.1.8 vs 6.1.9-rc (30: 18 pipeline, 12 controls) | 24 | 3 | 0 | 9 landed, unchanged | L4 79 -> 70 |

- Lifted by 6.1.8:
  - L1-only: ef806600;
  - OIS-only: 0dc425d4, 33137cdc, 3825e887, 4bc5188e, 62b42a40, 711b994d, e82ff8f3, f934c5ee;
  - overlap: 309afe6f, 324c0e0e, 475f982e, 6260e106, c2f9f032, fa27c3e7;
  - pipeline: a512a566, c1de5e51, d00047d0, a0ae9004.
- Lifted by 6.1.9: 786aab37, 8bce5139, ecae31e1.
- OIS build-only probe (856 former open_in_source parts in the 62 OIS-only models):
  - parts closed: 210 by 6.1.7 code, 255 by 6.1.8;
  - remaining gaps are mm-scale missing or overlapping faces (571 parts > 10 mm, none <= 1 mm);
  - 38 of the 62 models have every former open_in_source part closed.
- Seam sewing without chaining (6.1.8 final), on the 145 class-1 sewn models (1,177 transcoded parts):
  - no change in closedness;
  - sew_max_mm <= 0.1 (was up to 0.33);
  - largest volume change 7e-5.
- ca769beb (1.2 GB Tekla 2022, 6.1.7-rc on BOX-A): 194,604 parts in 4 h 04 min, peak 10.9 GB, STEP 4.99 GB, rc 0. The
  verify budget was not hit (verify ~93 min).
