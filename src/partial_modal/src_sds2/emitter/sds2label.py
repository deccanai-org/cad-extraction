"""GlobalIds of the IFC emitted from an SDS/2 conversion (tools/sds2ifc emitter) and of the products of the shipped STEP
(the pipeline's delivered reader): one function, so both sides name an instance the same way.

  guid(salt, key)   the IFC base-64 GlobalId of the first 128 bits of sha256(salt '|' key); salt = the sha256 of the
                    shipped STEP file (hex), key = key(label, occurrence)
  key(label, k)     the instance label as the STEP stores it, without leading / trailing blanks (component / product name: '<member type> #<member> /
                    <piece name> (piece <id>, inst <n>)', 'BOLT ... (inst <n>)', ...); the k-th repeat of a label in
                    document order (k >= 1) gets '\\x00<k>' appended"""
import hashlib

_CHARS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$'


def compress(hex32):
    bs = [int(hex32[i:i + 2], 16) for i in range(0, 32, 2)]

    def b64(v, n):
        return ''.join(_CHARS[(v >> (6 * i)) & 63] for i in reversed(range(n)))
    return b64(bs[0], 2) + ''.join(b64((bs[i] << 16) + (bs[i + 1] << 8) + bs[i + 2], 4) for i in range(1, 16, 3))


def key(label, k=0):
    label = label.strip()          # the STEP reader strips the leading blank of untyped members' labels (' #12 / ...')
    return label if not k else '%s\x00%d' % (label, k)


def guid(salt, k):
    return compress(hashlib.sha256((salt + '|' + k).encode('utf-8')).hexdigest()[:32])
