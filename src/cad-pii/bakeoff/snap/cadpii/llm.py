"""OpenRouter client: logs tokens / cost / latency per call. Never prints the key."""
import base64
import json
import os
import re
import time

import requests

URL = "https://openrouter.ai/api/v1/chat/completions"
_KEY = None
LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "llm_calls.jsonl")

# models with a ZDR endpoint on OpenRouter (GET /api/v1/endpoints/zdr, 2026-09-30)
NO_ZDR = {"qwen/qwen3.8-max-prime", "qwen/qwen3.8-max-0902", "anthropic/claude-fable-5.1"}


def key():
    global _KEY
    if _KEY is None:
        _KEY = open(os.path.expanduser("~/.config/cad-pii/openrouter.key")).read().strip()
    return _KEY


def b64png(png):
    return "data:image/png;base64," + base64.b64encode(png).decode()


def chat(model, system, text, images=(), max_tokens=12000, tag="", json_mode=True, timeout=600, retries=2):
    content = [{"type": "text", "text": text}]
    for png in images:
        content.append({"type": "image_url", "image_url": {"url": b64png(png)}})
    body = {"model": model, "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": content}],
            "max_tokens": max_tokens, "usage": {"include": True}}
    zdr = model not in NO_ZDR
    body["provider"] = {"zdr": True, "data_collection": "deny"} if zdr else {"data_collection": "deny"}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    err = None
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            r = requests.post(URL, headers={"Authorization": "Bearer " + key(), "Content-Type": "application/json"},
                              data=json.dumps(body), timeout=timeout)
            dt = time.time() - t0
            j = r.json()
            if r.status_code != 200 or "choices" not in j:
                err = f"HTTP {r.status_code}: {str(j)[:400]}"
                # retry without response_format / data_collection if the router rejects it
                if r.status_code in (400, 404) and "response_format" in body:
                    body.pop("response_format")
                elif r.status_code == 404 and not zdr and "provider" in body:
                    body.pop("provider")
                time.sleep(2 + 3 * attempt)
                continue
            msg = j["choices"][0]["message"]
            out = msg.get("content") or ""
            if j["choices"][0].get("finish_reason") == "error" or not out.strip():
                err = f"finish={j['choices'][0].get('finish_reason')} empty={not out.strip()} {str(j.get('error') or '')[:200]}"
                time.sleep(3 + 5 * attempt)
                continue
            u = j.get("usage") or {}
            rec = {"ts": time.time(), "tag": tag, "model": model, "provider": j.get("provider"), "zdr_requested": zdr,
                   "latency_s": round(dt, 2), "prompt_tokens": u.get("prompt_tokens"),
                   "completion_tokens": u.get("completion_tokens"),
                   "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                   "cost": u.get("cost"), "finish": j["choices"][0].get("finish_reason"), "n_images": len(images)}
            with open(LOG, "a") as f:
                f.write(json.dumps(rec) + "\n")
            return {"text": out, "parsed": parse_json(out), **rec}
        except Exception as e:  # network / json
            err = repr(e)[:400]
            time.sleep(2 + 3 * attempt)
    rec = {"ts": time.time(), "tag": tag, "model": model, "error": err}
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return {"text": "", "parsed": None, "error": err, "model": model, "cost": 0, "latency_s": None,
            "prompt_tokens": 0, "completion_tokens": 0}


def parse_json(s):
    if not s:
        return None
    s2 = s.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", s2, re.S)
    if m:
        s2 = m.group(1)
    try:
        return json.loads(s2)
    except Exception:
        pass
    i, j = s2.find("{"), s2.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(s2[i:j + 1])
        except Exception:
            return None
    return None
