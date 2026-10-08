"""Shared helpers for the S3D (MLNG@1) -> JSON/PCF/IFC/STEP/GLB pipeline.

Read-only against SQL Server: only SELECTs and #temp tables are ever issued.
"""
import os, re, json, gzip, time, pickle, datetime, math, hashlib

ROOT = os.environ.get('S3D_ROOT', '/data/s3d')
WORK = os.path.join(ROOT, 'work')
META = os.path.join(WORK, 'meta')
OUT = os.path.join(ROOT, 'out')            # mirrors s3://.../zenitude-data-2/model/
LOGS = os.path.join(ROOT, 'logs')
S3_BUCKET = 'annotationprod'
S3_PREFIX = 'cad-disk-extract/zenitude-data-2/model'
S3_STATE = 'cad-disk-extract/zenitude-data-2/_state/s3d3d_status.json'

MDB, CDB, SCH = 'MLNG@1_MDB', 'MLNG@1_CDB', 'MLNG@1_CDB_SCHEMA'

# relation GUIDs (origin -> target), see S3D_DATA_MODEL.md 1.5
R = dict(
    SystemHierarchy='A8CE36E7-A53F-4558-8DF9-F0BCE6583327',
    OwnsParts='3C9A3EEE-3F54-441F-A3D4-DCFC4615E88D',
    madeFrom='B0E39EC4-0141-11D2-8FF2-080036E94503',
    ProxyOwner='5280312B-E69C-11D1-A966-080036069A02',
    PathGenParts='C9820593-3838-11D2-BE94-080036B8A403',
    RelConnPart='71EEA3EB-F909-48B8-92A3-E04ED3E6E780',
    FlowPorts='42188F92-332B-11D4-93F0-080036B9BD03',
    DistribPorts='BFE914B5-978E-11D3-BFF3-080036B8A403',
    MatCtl='ED1D6AE6-1E81-42F7-A101-D79DD9F18096',
    PartClassParts='7FAA6155-07BE-11D2-BC6B-0800360DCD02',
    PartNozzles='F6AD318F-4BE0-11D2-BC7F-0800360DCD02',
    MatCtlForComp='33F05030-A9D7-4687-A7E0-43431A7EE452',
    OwnsDistConn='67E1D32D-38B0-4885-8F1A-784627305608',
    GenConnItems='95A02A64-195B-46D4-BE9E-2A4A15A9F90D',
    SystemHasSupport='F2B9B39A-909D-4F1B-9ED5-2E66D26EAFEC',
    SupportHasComponents='1781C544-33A0-4982-ACE1-BCBCBAEA5006',
    SupportHasCS='0E77B4AF-2DEB-4D45-953F-F59D0D36A601',
    OccAssyHasPart='1613374A-A8F0-11D4-BA3D-009027955FAD',
    PathRunUsesSpec='A53D19B6-21DE-4563-B7BC-03DE5D632E29',
    MemberToXS='11E4BF30-95B6-4996-82FE-5CEDABBC5359',
    DefinitionXS='A1471E95-F9E0-409F-8BCB-6B2AF3132017',
    Operand='93F52989-9504-11D4-9D40-00105AA5BAEB',
    Material='78A872D0-953C-11D4-9D40-00105AA5BAEB',
    DesignParent='E679D79A-0661-4802-990C-7DC0B8799D06',
    SysParent='07F5F6E2-8377-4F1B-93A2-3CB33D95F87F',
    HasEqpAsChild='795C63BB-2BB5-480D-AE62-FE999C446645',
    SOtoSI='A3B0F642-C087-4C77-A64B-23D322ED5C37',
    HasShapes='B6BBA674-B690-422F-9471-0F50934271F8',
    ShapeDefinedFrom='80E8EAB6-2D26-44C4-ACCF-1F13DDE339F4',
    AssemblyHierarchy='017E453B-10DB-11D2-8A4C-00A0C9065DF6',
    ConnHasPorts='5CF7C409-546D-11D2-B328-080036024603',
)

CLS = dict(pipe=80012, comp=80005, instr=80054, spec=80055, run=80013, pipeline=210007,
           turn=80036, branch=80035, straight=80037, alongleg=80034, end=80033)


def connect(db=MDB, timeout=0):
    import pyodbc
    pw = open('/root/.mssql_sa').read().strip()
    cs = ('DRIVER={ODBC Driver 18 for SQL Server};SERVER=127.0.0.1;DATABASE={%s};UID=sa;PWD={%s};'
          'TrustServerCertificate=yes;Encrypt=no;ApplicationIntent=ReadOnly' % (db, pw))
    c = pyodbc.connect(cs, autocommit=True, timeout=30)
    c.timeout = timeout
    return c


_WRITE_RE = re.compile(r'\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|EXEC|GRANT|DENY)\b', re.I)


def _check_readonly(sql):
    """guard: only SELECT and #temp-table DDL/DML are allowed."""
    for m in _WRITE_RE.finditer(sql):
        tail = sql[m.end():m.end() + 80].lstrip()
        kw = m.group(1).upper()
        if kw in ('INSERT',) and re.match(r'(INTO\s+)?#', tail, re.I):
            continue
        if kw in ('CREATE', 'DROP', 'ALTER', 'TRUNCATE') and re.match(r'(TABLE|CLUSTERED\s+INDEX|INDEX|NONCLUSTERED\s+INDEX)\s+(\w+\s+ON\s+)?#', tail, re.I):
            continue
        if kw == 'CREATE' and re.match(r'(CLUSTERED\s+|NONCLUSTERED\s+)?INDEX\s+\w+\s+ON\s+#', tail, re.I):
            continue
        raise RuntimeError('refusing non-read-only SQL near: %r' % sql[max(0, m.start() - 40):m.end() + 60])


def query_sets(conn, sql, params=()):
    """run a (multi-statement) batch; return list of (columns, rows) for every result set."""
    _check_readonly(sql)
    cur = conn.cursor()
    cur.execute(sql, params) if params else cur.execute(sql)
    out = []
    while True:
        if cur.description:
            cols = [d[0] for d in cur.description]
            out.append((cols, cur.fetchall()))
        if not cur.nextset():
            break
    cur.close()
    return out


def query(conn, sql, params=()):
    s = query_sets(conn, sql, params)
    return s[-1] if s else ([], [])


def dicts(cols_rows):
    cols, rows = cols_rows
    return [dict(zip(cols, r)) for r in rows]


GUID_RE = re.compile(r'^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$')


def guid_list(oids):
    out = []
    for o in oids:
        o = str(o).strip('{}').upper()
        if not GUID_RE.match(o):
            raise ValueError('bad guid %r' % o)
        out.append("('%s')" % o)
    return ','.join(out)


def cls_of(oid):
    return int(str(oid)[:8], 16)


def safe_name(s, maxlen=120):
    s = (s or 'unnamed').strip()
    s = s.replace('"', 'in').replace("''", 'in')
    s = re.sub(r'[^A-Za-z0-9._()+-]+', '_', s).strip('_.')
    return (s or 'unnamed')[:maxlen]


def fnum(v, nd=6):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, nd)


def jdefault(o):
    if isinstance(o, (datetime.datetime, datetime.date)):
        return o.isoformat()
    if isinstance(o, bytes):
        return o.hex()
    if hasattr(o, 'hex') and not isinstance(o, (int, float)):
        return str(o)
    try:
        return float(o)
    except Exception:
        return str(o)


def write_json(path, obj, gz=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    gz = path.endswith('.gz') if gz is None else gz
    tmp = path + '.tmp%d' % os.getpid()
    data = json.dumps(obj, default=jdefault, separators=(',', ':'), ensure_ascii=False).encode()
    if gz:
        with gzip.open(tmp, 'wb', compresslevel=6) as f:
            f.write(data)
    else:
        with open(tmp, 'wb') as f:
            f.write(data)
    os.replace(tmp, path)


def read_json(path):
    op = gzip.open if path.endswith('.gz') else open
    with op(path, 'rb') as f:
        return json.loads(f.read())


def save_pkl(name, obj):
    os.makedirs(META, exist_ok=True)
    p = os.path.join(META, name + '.pkl')
    with open(p + '.tmp', 'wb') as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(p + '.tmp', p)


_pk = {}


def load_pkl(name):
    if name not in _pk:
        with open(os.path.join(META, name + '.pkl'), 'rb') as f:
            _pk[name] = pickle.load(f)
    return _pk[name]


def log(msg, fh=None):
    s = '%s %s' % (datetime.datetime.utcnow().strftime('%H:%M:%S'), msg)
    print(s, flush=True)
    if fh:
        fh.write(s + '\n'); fh.flush()


def utcnow():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
