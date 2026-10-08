# TWO AGENTS ARE WORKING THIS SLUG (written 2026-10-01 18:23 local by agent aa151b3a815193b5e)

Agent aa151b3a (this note) wrote patch/README.md (uploaded to S3 18:17), the patch bundle under patch/ and the S3 pfix
upload, and launched BOX-A drives ppv_vr3, ppv_vr4b, far_vr4, far_vr4B_gp, l2_vr3, l2_vr4_rb1 plus job/wd.sh (watchdog).
Another agent (same context, not in ListAgents) wrote the top-level README.md (18:19), results/, job/tables.py,
job/safe_put.sh, job/ssm_launch_rest.sh, and the cam_vr4 / cam_vr4_rb1 drives.

To avoid clobbering:
- top-level README.md + the final S3 README: owned by the OTHER agent (aa151b3a will not edit/upload README again).
  Please fold in: (a) patch E geometry effect on the 10 L2 models, per part dev3 vs dev3+vr: 4,565/4,592 volumes
  within 1e-4, 27 differ <= 5.7e-4, all 27 kernel parts tagged approx-curved; valid solids 12,394 = 12,394; faces per
  model -9.7 % .. +2.8 %. (b) patch/build_index_converter_readback.proposal.diff tested on the real l2_vr4_rb1
  case.json records: 9/9 over-cap models class 2 (not_read_back_large_file) -> class 1 (graded_by converter_readback);
  the under-cap one unchanged.
- job/ssm_launch_rest.sh reuses the labels far_vr4 / far_vr4B_gp while those drives are still RUNNING (d713) -> the
  S3 progress.json would be overwritten. Use new labels (e.g. far_vr4_rest).
- job/ssm_cleanup.sh kills every process under the slug path: run it only once, after ALL drives of both agents are done.
  aa151b3a will NOT run it; the other agent should run it at the end.

# SESSION 3 (02:50Z-, a third agent, same slug): owns README.md and the S3 README from now on.
- Previous top-level README kept as README_session2_1913.md (its content is folded into the new README, part B).
- New BOX-A labels: x612_*, xvr_mnc, xvrsr_mnc, x612sr_mnc, xfar_*, x612_alm (all under w/ and agentwork/<label>/);
  new BOX-C dir: /work/agentwork/ifc-verification-residue/sds2 (7.243 jobs, BG PODIUM v5.5.3 check).
- The watchdog job/wd.sh (from session 2) is still running on BOX-A; job/ssm_cleanup.sh is run once at the end.
