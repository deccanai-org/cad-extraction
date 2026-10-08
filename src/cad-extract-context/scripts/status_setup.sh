#!/bin/bash
# Owner-approved 10-03 (AskUserQuestion "Approve both"): move the live status publisher (publish_sources.py -> dhigdec/cad-extract-status,
# counts only) from the Mac to the coordinator box, with a repo-only GitHub deploy key generated on the box. Idempotent. Run via:
#   bash /tmp/z3c/ssmcli.sh ap-south-1 i-039e769ea62de0fa1 /tmp/z3c/status_setup.sh 300
# Phase 1 (key not yet on GitHub): installs git, makes the deploy key (private key stays on this box, 600), prints the PUBLIC key for the
#   owner to add at github.com/dhigdec/cad-extract-status -> Settings -> Deploy keys (allow write access).
# Phase 2 (key accepted): clones the repo, installs systemd unit z3status (publish_sources.py 120, instance role).
set -u
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/status; K=/root/.ssh/status_deploy; PY=/opt/conv/env/bin/python
mkdir -p $D /root/.ssh && chmod 700 /root/.ssh
command -v git >/dev/null || dnf install -y -q git >/dev/null 2>&1
[ -f $K ] || ssh-keygen -q -t ed25519 -N '' -C 'cad-status-coordinator' -f $K
chmod 600 $K
grep -q github.com /root/.ssh/known_hosts 2>/dev/null || ssh-keyscan -t ed25519 github.com >> /root/.ssh/known_hosts 2>/dev/null
cat > /root/.ssh/config <<'EOF'
Host github-status
  HostName github.com
  User git
  IdentityFile /root/.ssh/status_deploy
  IdentitiesOnly yes
EOF
for f in publish_sources.py stats_agg.py z4_loose_types.json; do
  aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/status/$f $D/$f
done
echo "publisher: $(grep -c PUB_PROFILE $D/publish_sources.py) env hooks, $(wc -l < $D/publish_sources.py) lines"
if ! ssh -o BatchMode=yes -T github-status 2>&1 | grep -qi "successfully authenticated"; then
  echo "== PHASE 1: add this PUBLIC deploy key (write access) to github.com/dhigdec/cad-extract-status -> Settings -> Deploy keys:"
  cat $K.pub
  exit 0
fi
echo "== PHASE 2: GitHub accepts the key"
[ -d $D/cad-extract-status/.git ] || git clone -q github-status:dhigdec/cad-extract-status.git $D/cad-extract-status
git -C $D/cad-extract-status config user.name 'cad-status-bot'
git -C $D/cad-extract-status config user.email 'cad-status-bot@users.noreply.github.com'
git -C $D/cad-extract-status pull -q --rebase || true
cat > /etc/systemd/system/z3status.service <<EOF
[Unit]
Description=CAD live status publisher (counts only) -> dhigdec/cad-extract-status
After=network-online.target
[Service]
Environment=AWS_DEFAULT_REGION=ap-south-1
Environment=PUB_PROFILE=
Environment=PUB_REPO=$D/cad-extract-status
Environment=PUB_PRIVATE_HTML=$D/private.html
WorkingDirectory=$D
ExecStart=$PY $D/publish_sources.py 120
Restart=always
RestartSec=30
Nice=10
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q z3status
systemctl restart z3status
sleep 45
systemctl is-active z3status
journalctl -u z3status --no-pager -n 6 | cut -c1-200
git -C $D/cad-extract-status log --oneline -2
