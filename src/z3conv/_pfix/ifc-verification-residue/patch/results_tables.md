### L2 regression set (10 models, 6.0.1 wrote L2-alt-source parts)

| model | 6.0.1 L2 parts | dev3 class / levels / MB / s | dev3+vr class / levels / MB / s |
|---|---|---|---|
| e4901c30087b | 41 | 1 / L0:1057 L2:1 / 11.8 / 65.6 | 1 / L0:1058 / 12.3 / 59.3 |
| 749c9cd1eb18 | 31 | 1 / L0:237 / 3.1 / 21.3 | 1 / L0:237 / 3.1 / 16.5 |
| 3a7da4ce6b6a | 35 | 1 / L0:143 / 6.5 / 49.5 | 1 / L0:143 / 6.5 / 47.9 |
| 0e11be1f337e | 48 | 1 / L0:823 / 3.6 / 24.2 | 1 / L0:823 / 3.6 / 19.5 |
| 75d22c70b24f | 38 | 1 / L0:566 / 6.2 / 40.5 | 1 / L0:566 / 6.3 / 33.2 |
| a901254aae2a | 16 | 1 / L0:124 / 1.0 / 8.5 | 1 / L0:124 / 0.9 / 10.5 |
| 90263e4576c8 | 16 | 1 / L0:318 / 3.3 / 16.4 | 1 / L0:318 / 3.3 / 20.6 |
| 0e047d170568 | 30 | 1 / L0:670 / 5.3 / 44.2 | 1 / L0:670 / 5.3 / 40.9 |
| 042c7d952655 | 24 | 1 / L0:394 / 6.1 / 37.8 | 1 / L0:394 / 6.1 / 41.0 |
| 37aebdc71e2a | 21 | 1 / L0:311 / 5.7 / 34.1 | 1 / L0:311 / 5.7 / 36.3 |

### Converter per-part read-back as the join source (dev3+vr, RB_MAX_MB=1 forces the over-cap path)

| model | step_check join == read-back join | class (classifier unchanged) |
|---|---|---|
| e4901c30087b | yes (coverage, matched, volume checked/within/outside/median/p5/p95, surface parts) | 2 ['not_read_back_large_file'] |
| 749c9cd1eb18 | yes (coverage, matched, volume checked/within/outside/median/p5/p95, surface parts) | 2 ['not_read_back_large_file'] |
| 3a7da4ce6b6a | yes (coverage, matched, volume checked/within/outside/median/p5/p95, surface parts) | 2 ['not_read_back_large_file'] |
| 0e11be1f337e | yes (coverage, matched, volume checked/within/outside/median/p5/p95, surface parts) | 2 ['not_read_back_large_file'] |
| 75d22c70b24f | yes (coverage, matched, volume checked/within/outside/median/p5/p95, surface parts) | 2 ['not_read_back_large_file'] |
| a901254aae2a | yes (coverage, matched, volume checked/within/outside/median/p5/p95, surface parts) | 1 [] |
| 90263e4576c8 | yes (coverage, matched, volume checked/within/outside/median/p5/p95, surface parts) | 2 ['not_read_back_large_file'] |
| 0e047d170568 | yes (coverage, matched, volume checked/within/outside/median/p5/p95, surface parts) | 2 ['not_read_back_large_file'] |
| 042c7d952655 | yes (coverage, matched, volume checked/within/outside/median/p5/p95, surface parts) | 2 ['not_read_back_large_file'] |
| 37aebdc71e2a | yes (coverage, matched, volume checked/within/outside/median/p5/p95, surface parts) | 2 ['not_read_back_large_file'] |

### ifc members not converted (16 class-3 models)

| model | index row (00:06Z) | dev3 | dev3+vr (stock grader) | dev3+vr, V6_FAR_VERIFY=1 + step_check_far |
|---|---|---|---|---|
| c951cd2d377d | 3 member_coverage_0.22 | 1   cov 1.0 | 1   cov 1.0 | 1   cov 1.0 |
| b79c4f3a9377 | 3 member_coverage_0.20 | 1   cov 1.0 | not run | not run |
| c13135ba64e2 | 3 member_coverage_0.00 | 2 parts_without_solid:6 L4-surface:6 cov 1.0 | 2 parts_without_solid:6 L4-surface:6 cov 1.0 | 1   cov 1.0 |
| d9962a0cdfd3 | 3 member_coverage_0.17 | 1   cov 1.0 | 1   cov 1.0 | 1   cov 1.0 |
| 708137998946 | 3 member_coverage_0.27 | 1   cov 1.0 | not run | not run |
| 4f6b8e2e9693 | 3 member_coverage_0.01 | 2 parts_without_solid:4 L4-surface:4 cov 1.0 | 2 parts_without_solid:4 L4-surface:4 cov 1.0 | 1   cov 1.0 |
| e43ef5137745 | 3 member_coverage_0.34 | 1   cov 1.0 | not run | not run |
| 925e43c7b39a | 3 member_coverage_0.35 | 2  open-surface:4 cov 1.0 | not run | not run |
| 700b4c5c15d6 | 3 member_coverage_0.39 | 2 parts_without_solid:1 L4-surface:1 cov 1.0 | 2 parts_without_solid:1 L4-surface:1 cov 1.0 | 1   cov 1.0 |
| 944bc6d8f919 | 3 member_coverage_0.33 | 1   cov 1.0 | 1   cov 1.0 | 1   cov 1.0 |
| 6f3ceef9bdcb | 3 member_coverage_0.38 | 2 parts_without_solid:2 L4-surface:2 cov 1.0 | 2 parts_without_solid:2 L4-surface:2 cov 1.0 | 1   cov 1.0 |
| 7b35850cd279 | 3 member_coverage_0.37 | 2 parts_without_solid:1 open-surface:14 L4-surface:1 cov 1.0 | 2 parts_without_solid:1 open-surface:14 L4-surface:1 cov 1.0 | 2  open-surface:14 cov 1.0 |
| cd3313dc0284 | 3 member_coverage_0.47 | 2  open-surface:17 cov 1.0 | not run | not run |
| 7ff7ad6bbfd8 | 3 member_coverage_0.38 | 1   cov 1.0 | not run | not run |
| 4bbcc615d753 | 3 member_coverage_0.00 | 2 parts_outside_volume_tolerance:162/7735,parts_without_solid:37 open-surface:47 cov 1.0 | not run | not run |
| d713eae4bf9d | 3 member_coverage_0.44 | 2 invalid_solids:383,parts_without_solid:119 open-surface:69 L4-surface:119 cov 1.0 | not run | not run |
