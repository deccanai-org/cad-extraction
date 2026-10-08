"""Read only archive indexes of exact alternate SDS2 job copies; no extraction."""
import io
import json
import zipfile

import boto3
import py7zr

from inventory.probe_archives import S3File


BUCKET = "bim-proprietary-data"
PAIRS = [
    (
        "Completed_Jobs_Data/SDS_Jobs_7.312/Ben Hur Steel.7z",
        "Ben Hur Steel/IKEA_JOB",
    ),
    (
        "Completed_Jobs_Data/SDS_Jobs_7.312/MMW.7z",
        "MMW/SimLearn Nation Center/SimLearn Nation Center_JOB",
    ),
    (
        "Completed_Jobs_Data/SDS_Jobs_7.331/ME.7z",
        "ME/White Deer ISD/1581_J_ Seq 3 thru 5_091515",
    ),
    (
        "Completed_Jobs_Data/Server12 Completed Jobs.zip",
        "Jobs On 7.258/Cives/Cives_Job-7.258",
    ),
]


def check(archive, root):
    key = "Disk-2/" + archive
    size = boto3.client("s3").head_object(Bucket=BUCKET, Key=key)["ContentLength"]
    f = S3File(key, size)
    with io.BufferedReader(f, buffer_size=1 << 20) as buffered:
        if archive.lower().endswith(".zip"):
            with zipfile.ZipFile(buffered) as z:
                names = [i.filename for i in z.infolist()]
        else:
            with py7zr.SevenZipFile(buffered, mode="r") as z:
                names = [i.filename for i in z.list()]
    names = {n.replace("\\", "/").casefold() for n in names}
    pre = root.replace("\\", "/").casefold().rstrip("/") + "/"
    needed = ("main/jsetup", "main/job_mtrl", "mem/mem_idx", "subm/subm_idx")
    return {
        "archive": archive,
        "job_root": root,
        "object_bytes": size,
        "fetched_bytes": f.fetched,
        "present": {p: pre + p in names for p in needed},
    }


for archive, root in PAIRS:
    try:
        print(json.dumps(check(archive, root), ensure_ascii=False), flush=True)
    except Exception as e:
        print(json.dumps({"archive": archive, "job_root": root, "error": f"{type(e).__name__}: {e}"}), flush=True)
