import struct, sys
d = open(sys.argv[1], 'rb').read()
n = int(sys.argv[2]) if len(sys.argv) > 2 else 120
# header: 15 bytes 'ACIS BinaryFile', then tokens
i = 15
def tok(i):
    t = d[i]; i += 1
    if t in (2,): return t, d[i], i + 1
    if t == 3: return t, struct.unpack('<h', d[i:i+2])[0], i + 2
    if t in (4, 0x0C, 0x15): return t, struct.unpack('<i', d[i:i+4])[0], i + 4
    if t == 5: return t, struct.unpack('<f', d[i:i+4])[0], i + 4
    if t == 6: return t, struct.unpack('<d', d[i:i+8])[0], i + 8
    if t == 7: L = d[i]; return t, d[i+1:i+1+L].decode('latin1'), i + 1 + L
    if t == 8: L = struct.unpack('<H', d[i:i+2])[0]; return t, d[i+2:i+2+L].decode('latin1'), i + 2 + L
    if t in (9, 0x12): L = struct.unpack('<I', d[i:i+4])[0]; return t, d[i+4:i+4+L].decode('latin1'), i + 4 + L
    if t in (0x0D, 0x0E): L = d[i]; return t, d[i+1:i+1+L].decode('latin1'), i + 1 + L
    if t in (0x13, 0x14): return t, struct.unpack('<3d', d[i:i+24]), i + 24
    if t in (0x0A, 0x0B, 0x0F, 0x10, 0x11): return t, None, i
    return t, '??', i
out = []
for k in range(n):
    if i >= len(d): break
    t, v, i2 = tok(i)
    out.append('%d:%02x=%s' % (i, t, v if not isinstance(v, float) else round(v, 5)))
    if v == '??': break
    i = i2
print('\n'.join(out))
