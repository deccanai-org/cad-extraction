"""stub of convfleet for testing the patched grade/worker.py check_step offline: S3 calls served from a local directory"""
import os, shutil
ROOT = 'cad-disk-extract/zenitude-data-3'; B = 'local'
LOCAL = os.environ['STUB_S3_DIR']


class _S3:
    def head_object(self, Bucket, Key):
        return {'ContentLength': os.path.getsize(os.path.join(LOCAL, os.path.basename(Key)))}

    def download_file(self, Bucket, Key, dst):
        shutil.copy(os.path.join(LOCAL, os.path.basename(Key)), dst)


s3 = _S3()
