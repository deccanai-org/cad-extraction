from OCP.BRep import BRep_Builder, BRep_Tool as _BT
class BRep_Tool:
    Triangulation = staticmethod(lambda f, loc: _BT.Triangulation_s(f, loc))
