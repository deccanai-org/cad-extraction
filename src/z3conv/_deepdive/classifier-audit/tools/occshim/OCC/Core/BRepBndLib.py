from OCP.BRepBndLib import BRepBndLib as _B
class brepbndlib:
    Add = staticmethod(lambda s, b, t=True: _B.Add_s(s, b, t))
