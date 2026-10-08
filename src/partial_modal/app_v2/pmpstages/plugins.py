"""plug-in components: the source regenerators (src_db1, src_sds2) and the issue maker (issues) are separate components
(partial_modal/<component>/). Each is copied into its stage image at /pmp/<component>/ and must provide

    <component>/stage.py      def run(job: dict, ctx: dict) -> dict
    (issues may instead provide make_issues.py with the same run(job, ctx))

and MAY provide <component>/modal_image.py with  def build(modal, root) -> modal.Image  (root = the component folder on
the Mac): the image its stage runs in (src_db1: the decoder env + kits; src_sds2: the converter envs). The app copies
the component folder to /pmp/<component>/ and the app's own code to /pmp/app/ on top of whatever image it returns.
Without modal_image.py: issues runs in the pipeline image (build123d), src_db1 / src_sds2 cannot run (their stage
records 'plugin_image_missing'; nothing is skipped silently).

The app calls run() once per model inside the stage's Modal container with:

  ctx['stage']      'src_db1' | 'src_sds2' | 'issues'
  ctx['work']       empty local scratch dir on the container's ephemeral disk (deleted afterwards)
  ctx['out']        empty local staging dir, see "outputs" below
  ctx['model_dir']  /vol/<id>: outputs of earlier stages (read only): source/, pipeline/out/, pipeline/summary.json
  ctx['cls'], ctx['J'], ctx['deadline']   size class, cores to use, epoch seconds by which run() must return
  ctx['log']        callable(str): appends to /<id>/logs/<stage>.log
  ctx['fetch']      callable(url_key, dest_path, sha256=None, nbytes=None) -> {bytes, sha256, object}: downloads
                    job['urls'][url_key] (pre-signed GET) with retries; never log the URL itself
  ctx['code_dir']   /pmp/code/<variant> of the pipeline code this model uses (tools/, kit/)
  issues only:
  ctx['step_path']     local copy of the delivered STEP (size- and sha256-checked)
  ctx['ifc_path']      local copy of the source IFC (package IFC, or the regenerated / emitted one from source/)
  ctx['pipeline_out']  local copy of the pipeline's flat out folder (parts.csv ... verification.csv, *_summary.json)
  ctx['source_dir']    local copy of /<id>/source/ (provenance.json, skipped_records.json, sds2_facts.json ...)
  ctx['pipeline']      the pipeline summary (pmx_summary.json: perfect, reasons, status, steps ...)
  ctx['model_folder']  the scripts/<model_folder> name; ctx['issues_name'] = the <model> prefix of the issues files

outputs (everything run() writes into ctx['out']):
  src_*:  the IFC (name returned in 'ifc') + provenance.json (+ skipped_records.json for src_db1, sds2_facts.json for
          src_sds2, any other file the issue maker needs). Published as /<id>/source/ when ok=True.
  issues: paths relative to the model folder: schedules/issues.json, schedules/missing_parts.json,
          issues/WHERE_TO_LOOK.md (all three required). Optional: ref/<file> = a reference copy of an issues STEP
          the maker produced itself; the app then requires the shipped build_issues_model.py to reproduce it (DATA
          section byte-identical). Everything except ref/ is copied into scripts/<model_folder>/.

run() returns a JSON-serialisable dict with at least {'ok': bool, 'error': str|None}; plus
  src_*:   'ifc' (file name inside ctx['out']), 'sha256' (of that file), 'provenance' (dict: kit / converter version,
           proof of reproduction ...), 'verdict' (e.g. 'reproduced')
  issues:  'counts' ({'GREY','RED','ORANGE','YELLOW','PURPLE'} part counts as issues.json states them), anything else
An exception in run() is caught and recorded as the stage's error; it is never retried silently.
"""
import importlib.util, os, sys

from . import common as C

ENTRY = {'src_db1': ('stage.py',), 'src_sds2': ('stage.py',), 'issues': ('stage.py', 'make_issues.py')}


def entry(name, root=C.PLUGIN_ROOT):
    for f in ENTRY.get(name, ('stage.py',)):
        p = os.path.join(root, name, f)
        if os.path.exists(p):
            return p
    return None


def available(name, root=C.PLUGIN_ROOT):
    return entry(name, root) is not None


def load(name, root=C.PLUGIN_ROOT):
    d = os.path.join(root, name)
    path = entry(name, root)
    if not path:
        raise ImportError(f'plug-in {name} not in this image ({d}/{"|".join(ENTRY.get(name, ("stage.py",)))} missing)')
    if d not in sys.path:
        sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location(f'pmp_plugin_{name}', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not callable(getattr(mod, 'run', None)):
        raise ImportError(f'plug-in {name}: {os.path.basename(path)} has no run(job, ctx)')
    return mod
