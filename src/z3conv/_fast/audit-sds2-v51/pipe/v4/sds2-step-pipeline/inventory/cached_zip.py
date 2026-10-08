"""Open a huge zip on S3 with its central directory cached locally, so the directory is downloaded once
(68 GB server backup: 127.7 MB directory, 629,643 entries) and each member costs only its own bytes.
usage (library): z, f = open_cached(key, cache_dir); z.extract(info, dest); f.fetched -> bytes read from S3."""
import io, os, struct, zipfile
import boto3

BUCKET = "bim-proprietary-data"


class CachedTailFile(io.RawIOBase):
    """Seekable view of an S3 object: bytes from `tail_off` to the end come from a local cache file, everything
    else is fetched with ranged GETs (no cache, members are read once)."""
    def __init__(self, key, size, tail_off, tail_bytes):
        self.key, self.size, self.tail_off, self.tail = key, size, tail_off, tail_bytes
        self.pos, self.fetched, self.s3 = 0, 0, boto3.client("s3")
    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos
    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos
    def read(self, n=-1):
        if n is None or n < 0: n = self.size - self.pos
        n = max(0, min(n, self.size - self.pos))
        if n == 0: return b""
        if self.pos >= self.tail_off:
            o = self.pos - self.tail_off; out = self.tail[o:o + n]
        else:
            end = min(self.pos + n, self.tail_off) - 1
            out = self.s3.get_object(Bucket=BUCKET, Key=self.key, Range=f"bytes={self.pos}-{end}")["Body"].read()
            self.fetched += len(out)
        self.pos += len(out)
        return out
    def readinto(self, b):
        d = self.read(len(b)); b[:len(d)] = d; return len(d)


def open_cached(key, cache_dir):
    s3 = boto3.client("s3")
    size = s3.head_object(Bucket=BUCKET, Key=key)["ContentLength"]
    tail = s3.get_object(Bucket=BUCKET, Key=key, Range=f"bytes={size - 70000}-{size - 1}")["Body"].read()
    l = tail.rfind(b"PK\x06\x07")
    if l >= 0:
        z64 = struct.unpack("<Q", tail[l + 8:l + 16])[0]
        rec = s3.get_object(Bucket=BUCKET, Key=key, Range=f"bytes={z64}-{z64 + 55}")["Body"].read()
        cd_off = struct.unpack("<Q", rec[48:56])[0]
    else:
        e = tail.rfind(b"PK\x05\x06"); cd_off = struct.unpack("<I", tail[e + 16:e + 20])[0]
    os.makedirs(cache_dir, exist_ok=True)
    import hashlib                                  # stable name: Python's hash() is randomised per process
    cp = os.path.join(cache_dir, f"cd_{hashlib.md5(key.encode()).hexdigest()[:12]}_{cd_off}.bin")
    if not os.path.exists(cp) or os.path.getsize(cp) != size - cd_off:
        with open(cp + ".part", "wb") as f:
            body = s3.get_object(Bucket=BUCKET, Key=key, Range=f"bytes={cd_off}-{size - 1}")["Body"]
            for chunk in iter(lambda: body.read(1 << 20), b""): f.write(chunk)
        os.replace(cp + ".part", cp)
    f = CachedTailFile(key, size, cd_off, open(cp, "rb").read())
    return zipfile.ZipFile(io.BufferedReader(f, 1 << 16)), f
