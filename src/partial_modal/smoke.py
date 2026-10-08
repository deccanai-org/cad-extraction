import modal
app = modal.App("pmp-smoke")
img = modal.Image.debian_slim(python_version="3.11").pip_install("numpy")
@app.function(image=img, cpu=1, memory=512, timeout=120)
def hello(x):
    import os, platform, multiprocessing
    return dict(x=x, py=platform.python_version(), cpus=multiprocessing.cpu_count())
@app.local_entrypoint()
def main():
    print(list(hello.map(range(3))))
