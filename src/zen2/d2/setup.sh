mkdir -p /work/2d && cd /work/2d
python3 -m venv venv 2>&1 | tail -2 || { apt-get install -y python3-venv >/dev/null 2>&1; python3 -m venv venv; }
./venv/bin/pip install -q --upgrade pip 2>&1 | tail -1
./venv/bin/pip install -q pymupdf ezdxf olefile numpy pillow matplotlib boto3 scipy opencv-python-headless 2>&1 | tail -3
./venv/bin/python -c "import fitz, ezdxf, olefile, numpy, PIL, matplotlib, cv2, scipy; print(fitz.__doc__, ezdxf.__version__, olefile.__version__, numpy.__version__, cv2.__version__)"
