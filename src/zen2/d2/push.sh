#!/bin/bash
# push.sh FILE... -> copies local files to /work/2d/ on the box (base64 via SSM), then prints md5
cd /Users/dhiren/Downloads/Deccan/zen2/d2
t=$(mktemp /tmp/push.XXXX.sh)
echo "mkdir -p /work/2d; cd /work/2d" > $t
for f in "$@"; do echo "base64 -d > '$f' <<'B64EOF'" >> $t; base64 -i "$f" >> $t; echo "B64EOF" >> $t; echo "md5sum '$f'" >> $t; done
./r.sh $t 120; rm -f $t
