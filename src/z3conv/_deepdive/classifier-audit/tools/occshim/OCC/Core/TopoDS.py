from OCP.TopoDS import TopoDS_Compound, TopoDS as _T
class topods:
    Face = staticmethod(getattr(_T, 'Face_s', None) or _T.Face)
