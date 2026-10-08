##  JoistWeb.py Version 1.00
##  Copyright (c) 2007 Bruce Vaughan, BV Detailing & Design, Inc.
##  All rights reserved.
##  NOT FOR SALE. The software is provided "as is" without any warranty.
#######################################################################
# Add joist web material
from member import Member, MemberLocate
from param import *
from point import Point, PointLocate
from rnd_bar import RndBar
from math import *

def add_web(mem, pt, dist, a):
    rb1 = RndBar()
    rb1.member = mem
    rb1.pt1 = pt
    rb1.pt2 = pt + mem.translate(dist, 0.0, 0.0)
    rb1.grade = "A36"
    rb1.centered = "Yes"
    rb1.bar_diameter = 1
    rb1.work_pt_dist = dist
    rb1.length = dist
    rb1.mtrl_type = "Round bar"
    rb1.finish = "Red oxide"
    rb1.ref_pt_offset = (0, 0, 0)
    rb1.add()
    rb1.rotate(rb1.member, (0.000000, 0.000000, a)) 

ClearSelection()
while 1:
    try:
        mem = MemberLocate("Select joist member")
    except:
        break
    if mem == None:
        Warning("You did not select a joist member.")
        break
    rise = mem.depth-1
    run = mem.left.location.dist(mem.right.location)-12
    panels = int(run/(rise*2))
    panel_width = (run/panels)
    
    ptWP = mem.left.location + mem.translate(6.0, -0.5, 0.0)
    ptListTop = [ptWP+mem.translate(panel_width*i, 0.0, 0.0) for i in range(panels)]
    ptListBott = [ptWP+mem.translate(panel_width*i+panel_width/2, -rise, 0.0) for i in range(panels)]
                 
    diag = (rise**2 + (panel_width/2)**2)**0.5
    angle_deg = atan2(rise, (panel_width/2)) * 180.0 / pi
    
    for pt in ptListTop:
        add_web(mem, pt, diag, -angle_deg)
    
    for pt in ptListBott:
        add_web(mem, pt, diag, angle_deg)
    break
ClearSelection()
    

