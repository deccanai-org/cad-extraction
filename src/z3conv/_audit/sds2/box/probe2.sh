#!/bin/bash
/opt/conv/env/bin/python -c "import OCP; print('OCP ok', OCP.__file__)" 2>&1 | tail -1
ls /opt/ | head; ls /opt/conv/ | head -20
for p in /opt/conv/*/bin/python /opt/*/bin/python3; do echo $p; $p -c "import OCP; print('  OCP ok')" 2>&1 | tail -1; done
