"""BOX-C: for each stage-2-failure / ValueError job: result record, stage-2 log, last read-back block, missing-file detail."""
import json, sys, re, boto3, collections
s3 = boto3.client("s3", region_name="ap-south-1")
BK = "bim-proprietary-data"; ST = "cad-disk-extract/zenitude-data-3/_state/conv/sds2/results/"
out = []
for f in sys.argv[1:-1]:
    for jid in open(f).read().split():
        try:
            r = json.loads(s3.get_object(Bucket=BK, Key=ST + jid + ".json")["Body"].read())
        except Exception as e:
            out.append(dict(id=jid, err=str(e)[:200])); continue
        o = dict(id=jid, name=r.get("name"), version=r.get("version"), conv=(r.get("converter") or {}).get("label"),
                 status=r.get("status"), reason=r.get("reason"), stage2_reason=r.get("stage2_reason"),
                 validate=r.get("validate"), s2_err=(r.get("stage2") or {}).get("error"), log_tail=r.get("log_tail"),
                 error=r.get("error"), detail=r.get("detail"), n_files=r.get("n_files"), model_files=r.get("model_files"),
                 steel_ratio=(r.get("stage2") or {}).get("steel_ratio"), man=(r.get("manifest") or {}).get("class_reasons"),
                 man_class=(r.get("manifest") or {}).get("class"), weight=(r.get("manifest") or {}).get("weight"),
                 outputs=r.get("outputs"))
        pre = (r.get("outputs") or {}).get("prefix")
        lf = [x for x in (r.get("outputs") or {}).get("files", []) if x.endswith("stage2.log")]
        if pre and lf:
            try:
                txt = s3.get_object(Bucket=BK, Key=pre + lf[0])["Body"].read().decode("utf-8", "replace")
                vb = re.findall(r"with solids: (\d+); BRep valid: (\d+)", txt)
                o["verify_blocks"] = vb
                o["repair_lines"] = re.findall(r"read-back repair pass.*", txt)[:4]
                o["after"] = re.findall(r"manifest after read-back.*", txt)[:1]
                o["log_head_err"] = [l for l in txt.splitlines() if "Error" in l or "Traceback" in l][:6]
                o["log_len"] = len(txt)
            except Exception as e:
                o["log_err"] = str(e)[:200]
        out.append(o)
json.dump(out, open(sys.argv[-1], "w"), indent=1, default=str)
print("done", len(out))
