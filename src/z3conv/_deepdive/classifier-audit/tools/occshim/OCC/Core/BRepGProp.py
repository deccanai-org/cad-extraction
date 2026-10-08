from OCP.BRepGProp import BRepGProp as _B
class brepgprop:
    VolumeProperties = staticmethod(lambda s, g: _B.VolumeProperties_s(s, g))
