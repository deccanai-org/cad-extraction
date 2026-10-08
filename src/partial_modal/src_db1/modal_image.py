"""modal_image.py - the src_db1 stage image (contract of app/pmpstages/plugins.py: build(modal, root) -> modal.Image).

amazonlinux:2023 + Modal's python 3.11 (runtime, runs stage.py) - the OS of the bench that reproduced the shipped STEPs
  (171/171 perfect tier + the partial samples) and of the conversion fleet (the decoder / STEP stage load the SYSTEM libm,
  glibc 2.34 there). NOTE (2026-10-07, corrected): the n1 mismatch first blamed on Debian's glibc was the HOST CPU - the
  same AL2023 image reproduces n1 on AVX-512 hosts and misses by the same 9,603 lines on AVX2-only hosts
  (tests/results/diag_cpu_repro.json); regen_core.py pins the numeric kernels per CPU profile and stage.py refuses
  AVX2-only hosts (host_unsuitable -> retry). AL2023 is kept as the production OS; Debian was not re-tested +
  /opt/conv/env    micromamba conda env = env/conda_env.lock.txt exactly (310 name=version=build specs, conda-forge):
                   python 3.11.17, pythonocc-core 8.0.1 (OCC 8.0.1), ifcopenshell 0.9.0, numpy 2.4.6 -> regen_core.py,
                   stepcmp.py, and ifc2step6's OCC read-back verifier (found as <venv python realpath>/../env/bin/python)
  /opt/conv/ifc84  venv on that python = env/ifc84.requirements.txt exactly (--no-deps): ifcopenshell 0.8.4.post1,
                   numpy 2.4.6 ... -> the decoder (convert_one.py) and the STEP stage (ifc2step6.py), db1_facts.py
  /opt/kits/kit_v, /opt/kits/kit_u   the decoder kits (md5 == S3 version-history manifests, kit_manifests/)
Build gates (the image build fails otherwise): env/check_env.py (installed envs == locks; no OCC inside the venv, as in
production) and env/check_kits.py. No credentials, no secrets. The component code itself (/pmp/src_db1) is added by the
caller (the app copies the component folder; modal_src_db1.py adds its code files)."""
import os

SYS_LIBS = ['libgl1', 'libxrender1', 'libxext6', 'libsm6', 'libfontconfig1', 'libxkbcommon0', 'libxi6']
# the same libraries on Amazon Linux 2023 (dnf names)
AL2023_PKGS = ['tar', 'bzip2', 'gzip', 'findutils', 'which', 'ca-certificates', 'mesa-libGL', 'libXrender', 'libXext', 'libSM',
               'fontconfig', 'libxkbcommon', 'libXi']
AL2023_IMAGE = 'public.ecr.aws/amazonlinux/amazonlinux:2023'
BASE = os.environ.get('PMP_DB1_BASE', 'al2023')          # 'al2023' (default) | 'debian' (diagnostics only)


def _base(modal):
    if BASE == 'debian':
        return modal.Image.debian_slim(python_version='3.11').apt_install('curl', 'bzip2', 'ca-certificates', *SYS_LIBS)
    return (modal.Image.from_registry(AL2023_IMAGE, add_python='3.11')
            .run_commands('dnf install -y -q ' + ' '.join(AL2023_PKGS) + ' && dnf clean all',
                          'rpm -q glibc > /opt/glibc.version && cat /opt/glibc.version'))


def build(modal, root):
    root = str(root)
    env = os.path.join(root, 'env')
    return (
        _base(modal)
        .add_local_file(os.path.join(env, 'conda_env.lock.txt'), '/opt/pmp_env/conda_env.lock.txt', copy=True)
        .add_local_file(os.path.join(env, 'ifc84.requirements.txt'), '/opt/pmp_env/ifc84.requirements.txt', copy=True)
        .run_commands(
            'mkdir -p /opt/conv && cd /opt/conv && curl -sSL --retry 5 https://micro.mamba.pm/api/micromamba/linux-64/latest '
            '-o mm.tar.bz2 && tar xjf mm.tar.bz2 bin/micromamba && rm mm.tar.bz2 && /opt/conv/bin/micromamba --version '
            '> /opt/conv/micromamba.version',
            "grep -v '^#' /opt/pmp_env/conda_env.lock.txt | grep -v '^$' > /opt/pmp_env/specs.txt",
            'MAMBA_ROOT_PREFIX=/opt/conv/mamba /opt/conv/bin/micromamba create -y -q -p /opt/conv/env --override-channels '
            '-c conda-forge $(cat /opt/pmp_env/specs.txt) && MAMBA_ROOT_PREFIX=/opt/conv/mamba /opt/conv/bin/micromamba clean -a -y',
            '/opt/conv/env/bin/python -m venv /opt/conv/ifc84',
            "/opt/conv/ifc84/bin/pip install -q --no-deps --no-cache-dir $(grep -v '^#' /opt/pmp_env/ifc84.requirements.txt "
            "| grep -v '^$')",
        )
        .add_local_file(os.path.join(env, 'check_env.py'), '/opt/pmp_env/check_env.py', copy=True)
        .run_commands('PATH=/opt/conv/bin:$PATH MAMBA_ROOT_PREFIX=/opt/conv/mamba python /opt/pmp_env/check_env.py '
                      '/opt/pmp_env/conda_env.lock.txt /opt/pmp_env/ifc84.requirements.txt')
        .add_local_dir(os.path.join(root, 'kits', 'kit_v'), '/opt/kits/kit_v', copy=True)
        .add_local_dir(os.path.join(root, 'kits', 'kit_u'), '/opt/kits/kit_u', copy=True)
        .add_local_dir(os.path.join(root, 'kit_manifests'), '/opt/kits/_manifests', copy=True)
        .add_local_file(os.path.join(env, 'check_kits.py'), '/opt/pmp_env/check_kits.py', copy=True)
        .run_commands('python /opt/pmp_env/check_kits.py /opt/kits /opt/kits/_manifests')
        .env({'PMP_CONV_HOME': '/opt/conv', 'PMP_KITS': '/opt/kits', 'PYTHONHASHSEED': '0'})
    )
