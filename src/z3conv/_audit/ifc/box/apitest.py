import ifcopenshell, ifcopenshell.geom, sys
print('ifcopenshell', ifcopenshell.version)
s = ifcopenshell.geom.settings()
for k in ('disable-opening-subtractions', 'disable_opening_subtractions', 'DISABLE_OPENING_SUBTRACTIONS'):
    try:
        s.set(k, True); print('set ok', k)
    except Exception as e:
        print('set fail', k, type(e).__name__, str(e)[:120])
try:
    print('settings names', [n for n in dir(s) if 'OPEN' in n.upper()][:20])
except Exception as e:
    print(e)
try:
    print(s.setting_names()[:80])
except Exception as e:
    print('setting_names fail', e)
f = ifcopenshell.file(schema='IFC2X3')
print('file ok')
