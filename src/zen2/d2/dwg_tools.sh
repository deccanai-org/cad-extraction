#!/bin/bash
# installs ODA File Converter (.deb) and builds LibreDWG 0.14 under /work/2d/opt (does not replace /usr/local/bin/dwg2dxf)
L=/work/2d/logs/dwg_tools.log; mkdir -p /work/2d/logs /work/2d/dl; cd /work/2d/dl
log(){ echo "$(date -u +%FT%TZ) $*" >> $L; }
log start
curl -sL -m 600 -A "Mozilla/5.0" -o oda.deb "https://www.opendesign.com/guestfiles/get?filename=ODAFileConverter_QT6_lnxX64_11dll.deb"; log "oda download rc=$? size=$(stat -c %s oda.deb)"
file oda.deb >> $L
DEBIAN_FRONTEND=noninteractive apt-get install -y ./oda.deb >> $L 2>&1; log "oda install rc=$?"
dpkg -L odafileconverter 2>/dev/null | grep -i bin | head -5 >> $L
DEBIAN_FRONTEND=noninteractive apt-get install -y build-essential autoconf automake libtool pkg-config texinfo >> /work/2d/logs/apt_build.log 2>&1; log "build deps rc=$?"
curl -sL -m 600 -o libredwg-0.14.tar.xz https://github.com/LibreDWG/libredwg/releases/download/0.14/libredwg-0.14.tar.xz; log "ldwg download rc=$? size=$(stat -c %s libredwg-0.14.tar.xz)"
[ -s libredwg-0.14.tar.xz ] || { curl -sL -m 600 -o libredwg-0.14.tar.gz https://github.com/LibreDWG/libredwg/releases/download/0.14/libredwg-0.14.tar.gz; log "gz rc=$?"; }
tar xf libredwg-0.14.tar.* && cd libredwg-0.14 && ./configure --prefix=/work/2d/opt/libredwg-0.14 --disable-bindings --disable-docs > /work/2d/logs/ldwg_configure.log 2>&1 && make -j16 > /work/2d/logs/ldwg_make.log 2>&1 && make install > /work/2d/logs/ldwg_install.log 2>&1; log "ldwg build rc=$?"
/work/2d/opt/libredwg-0.14/bin/dwg2dxf --version >> $L 2>&1
log done
