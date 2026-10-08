"""VLM check: a vision model looks at the renders (and the Tekla-export render when there is one) and answers a fixed
rubric as JSON. It catches what numbers miss: members pointing the wrong way, exploded or scattered models, a
structure that does not look like the reference. It never overrides a numeric FAIL; it can only add findings.

Modes: api (Claude API, needs credentials), queue (write the request for a human / agent judge, ingest later)."""
import base64, json, os
from . import config as C

ISSUES = ["scattered_or_floating_parts", "misoriented_members", "exploded_or_duplicated", "missing_regions_vs_reference",
          "extra_regions_vs_reference", "wrong_scale_or_flattened", "empty_or_near_empty", "not_a_structure",
          "plates_misplaced", "render_unreadable"]

SCHEMA = {
    "type": "object",
    "properties": {
        "overall": {"type": "string", "enum": ["pass", "warn", "fail"]},
        "coherent_structure": {"type": "boolean"},
        "structure_type": {"type": "string"},
        "issues": {"type": "array", "items": {"type": "string", "enum": ISSUES}},
        "reference_agreement": {"type": "string", "enum": ["same", "mostly_same", "partial", "different", "no_reference"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "notes": {"type": "string"},
    },
    "required": ["overall", "coherent_structure", "structure_type", "issues", "reference_agreement", "confidence", "notes"],
    "additionalProperties": False,
}

PROMPT = """You are checking an automated conversion of a Tekla Structures steel model (.db1) into STEP.
Image 1 shows the converted STEP: four orthographic views (iso, plan from above, front elevation, and an iso of
the FULL extent including any stray parts). Blue = members (beams, columns, braces), orange = plates. Dark lines are
depth edges.
{ref}
Numbers from the geometric check, for context: {facts}

Judge only what the images show:
- Does it look like one coherent, buildable steel structure (frame, rack, platform, stair, building, connection
  detail...)? Columns should stand vertical, beams horizontal, plates attached to members.
- Are there parts floating far away, members sticking out at random angles, a model exploded into pieces,
  obviously duplicated copies, or a flattened/scaled-wrong model?
- If a reference render is given: is it the same structure (same layout, same main members)? The export may be
  partial (only some phases), so a STEP that contains the reference plus more is "partial", not "different".
overall = fail only for a clearly broken conversion; warn when something looks off but may be genuine; pass when it
looks like a correct steel model. Keep notes to 2-3 sentences, concrete (which view, what region)."""

REF_TEXT = """Image 2 shows Tekla's own IFC export of the same model (the ground truth), drawn in the SAME frame after
alignment: top row STEP, bottom row Tekla export. Green = STEP parts matched to an export element, red = export
elements with no STEP part."""


def request(images, facts, has_ref):
    content = []
    for p in images:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                    "data": base64.standard_b64encode(open(p, "rb").read()).decode()}})
    content.append({"type": "text", "text": PROMPT.format(ref=REF_TEXT if has_ref else "No reference export exists for this model.",
                                                          facts=json.dumps(facts, sort_keys=True))})
    return content


def judge_api(images, facts, has_ref, model=C.VLM_MODEL):
    import anthropic
    client = anthropic.Anthropic()
    resp = client.beta.messages.create(
        model=model, max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        output_config={"effort": C.VLM_EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": request(images, facts, has_ref)}],
    )
    if resp.stop_reason == "refusal":
        return dict(error="refusal", category=getattr(resp.stop_details, "category", None))
    text = next(b.text for b in resp.content if b.type == "text")
    out = json.loads(text); out["judge"] = resp.model
    return out


def write_queue(out_dir, stem, images, facts, has_ref):
    """a self-contained request a human or an agent session can answer; answer goes to <stem>_vlm.json"""
    q = dict(stem=stem, images=[os.path.abspath(p) for p in images], has_reference=has_ref, facts=facts,
             prompt=PROMPT.format(ref=REF_TEXT if has_ref else "No reference export exists for this model.", facts=json.dumps(facts, sort_keys=True)),
             answer_schema=SCHEMA, answer_path=os.path.abspath(os.path.join(out_dir, stem + "_vlm.json")))
    p = os.path.join(out_dir, stem + "_vlm_request.json"); json.dump(q, open(p, "w"), indent=1)
    return p


def validate(ans):
    """check an answer against SCHEMA (queue answers are written by hand/agent, not constrained decoding)"""
    for k in SCHEMA["required"]:
        if k not in ans: raise ValueError(f"missing {k}")
    assert ans["overall"] in ("pass", "warn", "fail")
    assert ans["reference_agreement"] in SCHEMA["properties"]["reference_agreement"]["enum"]
    assert ans["confidence"] in ("high", "medium", "low")
    assert all(i in ISSUES for i in ans["issues"])
    return ans
