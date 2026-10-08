##  JoistGirderMtrl.py Version 2.02
##  Copyright (c) 2009 Bruce Vaughan, BV Detailing & Design, Inc.
##  All rights reserved.
##  NOT FOR SALE. The software is provided "as is" without any warranty.
#######################################################################
'''
Add web and chord material to a joist member, mem.series == "G". There
is no check for the mem.series attribute.

The distance between chord material is hard coded to script variable
"web_space".

Web diagonal materials are angles applied to the outside face of the
chord vertical legs and web vertical material is flat bar and is
positioned between the chords.

Note:
    All girders selected must be the same length. If option ==
    "Pick Points", the points must be selected along the first
    member in jst_list.

User can enter the number of evenly spaced panels, select panel
points in plan, or select beam/joist members to locate the panel
points.

All joist girder bottom chords are extended.

The script does not add seat material.

Presently, the material is added similar to Vulcraft girder type BG.

Version History:
    2.00 (6/29/09) - Initial version

    2.01 (7/12/09) - Add member information to dialog box

    2.02 (8/3/09) - Add variables to control bottom chord extensions

#######################################################################
###### THIS VERSION WILL NOT WORK IN SDS/2 VERSIONS PRIOR TO 7.125 ####
#######################################################################
'''
import os
from math import *

from member import Member, MemberLocate, MemberPropertySet, MemberProperties
# for member.error
import member
from param import *
from point import Point, PointLocate
from flat_bar import FlatBar
from rolled_section import RolledSection
from job import Job
from fab import Fabricator
from shape import Shape

from macrolib.MemSelection import mem_select, memAreaSelect
from macrolib.FileDefaults import import_data, export_data
from macrolib.PointPlane3D import validColTup
from macrolib.highlight_points import add_cc, remove_cc
from macrolib.angle import rtod, dtor
from macrolib.L3D import LineLineIntersect3D

def main():
    #####################################################################
    ## Variables section
    # system path for defaults file
    default_file_path = os.path.join(os.getcwd(), "macro", "Defaults")

    # defaults file name
    def_file = "JoistGirderMtrl.txt"
    script_name = "JoistGirderMtrl_v2.02.py"

    # DIALOG BOX IMAGES
    image_path = os.path.join(os.getcwd(), "macro", "Images")
    image_name1 = os.path.join(image_path, "JoistGirderMaterial1.gif")

    web_space = 1.0
    finishList = ["None", "Red Oxide", "Yellow Zinc", "Gray Oxide",
                  "Sandblasted", "Blued Steel", "Galvanized"]
    angleGradeList = Job().steel_grades("Angle").keys()
    plateGradeList = Job().steel_grades("Plate").keys()
    optionList = ["Even Spacing", "Pick Points", "Select Bms/Jsts"]
    girderTypeList = ["BG",]
    
    # Type of user selection of joist members - valid choices: ('Area', 'Single')
    selectionType = 'Area'
    pw = 48
    
    # highlight point construction circle radius and color
    cc_rad = 2
    cc_color = 'Red'

    firstWP = 6.0
    bottWPdist = 1.5
    # minimum setback web Ls at bottom chord
    minGap = 0.0625

    # Member properties
    chordProperty = "chord_mtrl"
    webProperty = "web_dia"

    # Where BC is not extended, run BC dist beyond panel point
    bcEndDist = 6.0

    #####################################################################
    ## Defaults section
    girderType = "BG"
    option = "Even Spacing"
    web_finish = "Gray Oxide"
    plate_grade = plateGradeList[0]
    chord_mtrl = 'L5x3 1/2x5/16'
    web_mtrl = 'L1 1/2x1 1/2x3/16'
    web_width = 2
    angle_grade = angleGradeList[0]
    chord_finish = "Gray Oxide"
    chord_extend = 4.0

    bc_set_left = 4.5

    bc_set_right = 4.5
    chord_color = '135,135,135'
    web_color = '255,0,0'
    number_panels = 6

    # Extend bottom chords
    extend_leftBC = 'Yes'
    extend_rightBC = 'Yes'
    #####################################################################

    def add_web_vert(mem, pt, dist, a):
        rb1 = FlatBar()
        rb1.Member = mem
        rb1.Point1 = pt
        rb1.Point2 = pt + mem.translate(dist, 0.0, 0.0)
        rb1.MaterialGrade = plate_grade
        rb1.Centered = "Yes"
        rb1.Thickness = web_space
        rb1.Width = web_width
        rb1.WorkpointSlopeDistance = dist
        rb1.MaterialSetbackLeftEnd = 0
        rb1.MaterialSetbackRightEnd = 0
        rb1.length = dist
        rb1.mtrl_type = "Flat bar"
        rb1.mtrl_usage = 'Joist Web'
        rb1.finish = web_finish
        rb1.MaterialColor3d = validColTup(web_color)
        rb1.ReferencePointOffset = (0, 0, 0)
        rb1.Add()
        rb1.Rotate(rb1.member, (0, 0, a))

    def add_web_diag(mem, pt, dist, sbLeft, sbRight, toe_dir, a):
        rl1 = RolledSection()
        rl1.member = mem
        rl1.pt1 = pt
        rl1.pt2 = pt + mem.translate(dist, 0.0, 0.0)
        rl1.section_size = web_mtrl
        rl1.grade = angle_grade
        rl1.centered = 'No'
        rl1.llv = 'HZ.'
        rl1.ToeInOrOut = toe_dir
        rl1.work_pt_dist = dist
        rl1.end_cut_left = "Standard Cut"
        rl1.end_cut_right = "Standard Cut"
        rl1.MaterialSetbackLeftEnd = sbLeft
        rl1.MaterialSetbackRightEnd = sbRight
        rl1.length = dist - sbLeft - sbRight
        rl1.mtrl_type = 'Angle'
        rl1.finish = web_finish
        rl1.color = validColTup(web_color)
        rl1.mtrl_usage = 'Joist Web'
        rl1.ref_pt_offset = (0, 0, 0)
        rl1.add()
        rl1.rotate(rl1.member, (0, 0, a))

    def add_chord(mem, pt1, pt2, toe_dir, a):
        rl1 = RolledSection()
        rl1.member = mem
        rl1.pt1 = pt1
        rl1.pt2 = pt2
        rl1.section_size = chord_mtrl
        rl1.grade = angle_grade
        rl1.centered = 'No'
        rl1.llv = 'HZ.'
        rl1.toe_io = toe_dir
        rl1.work_pt_dist = pt1.dist(pt2)
        rl1.end_cut_left = "Standard Cut"
        rl1.end_cut_right = "Standard Cut"
        rl1.length = pt1.dist(pt2)
        rl1.mtrl_type = 'Angle'
        rl1.finish = chord_finish
        rl1.color = validColTup(chord_color)
        rl1.mtrl_usage = 'Joist Chord'
        rl1.ref_pt_offset = (0, 0, 0)
        rl1.add()
        rl1.rotate(rl1.member, (a, 0, 0))
    #################################################
    ## Import default values
    dd0 = import_data(os.path.join(default_file_path, def_file))
    if dd0:
        for key, value in dd0.items():
            exec "%s = %s" % (key, repr(value)) in None

    while True:
        ClearSelection()
        # Adjust variable selectionType in Variables Section
        if selectionType == 'Single':
            jst_list = mem_select("Select a JOIST GIRDER member", ['Joist', ], ['All', ])
        elif selectionType == 'Area':
            jst_list = memAreaSelect("Select JOIST GIRDER members by area", ['Joist', ], ['All', ])
        else:
            Warning("Invalid string value for variable selectionType")
            return
        
        if not jst_list:
            return
        else: mem1 = jst_list[0]
        ClearSelection()
        SelectionAdd(mem1)
        RedrawScreen()
        
        ## DIALOG BOX 1 #################################
        dlg1 = Dialog("Joist Material")
        dlg1.menu("print_doc", ("Yes", "No"), "No",
                  "Print documentation only".center(pw))
        dlg1.menu('option', optionList, option,
                  'Panel point options'.center(pw))
        dlg1.entry('number_panels', number_panels,
                   'Number of web panels, "Even Spacing" option'.center(pw))
        dlg1.menu('girderType', girderTypeList, girderType,
                  'Girder configuration type'.center(pw))
        
        dlg1.tabset_begin()
        dlg1.tab("General Information")
        dlg1.group_title("Joist Girder Information")
        dlg1.line("Size: %s  Series: %s" % (mem1.size, mem1.series))
        dlg1.line("Left setback: %s  Left conn_setback: %s" % (mem1.left.setback, mem1.left.conn_setback))
        dlg1.line("Right setback: %s  Right conn_setback: %s" % (mem1.right.setback, mem1.right.conn_setback))
        
        dlg1.group_title("Chord Material")
        dlg1.mtrl_browse('chord_mtrl', ("Angle",), chord_mtrl,
                         "Chord material size".center(pw))
        dlg1.menu("angle_grade", angleGradeList, angle_grade,
                  "Angle material grade".center(pw))
        dlg1.menu("chord_finish", finishList, chord_finish,
                  "Chord finish".center(pw))
        dlg1.entry("chord_color", chord_color,
                   "Chord material color".center(pw))
        
        dlg1.group_title("Web Material")
        dlg1.line("Distance between chord materials = %s" % (web_space))
        dlg1.mtrl_browse('web_mtrl', ("Angle",), web_mtrl,
                         "Web material size".center(pw))
        dlg1.entry("web_width", dim_print(web_width),
                   "Width of web verticals".center(pw))
        dlg1.menu("plate_grade", plateGradeList, plate_grade,
                  "Material grade for web verticals".center(pw))
        dlg1.menu("web_finish", finishList, web_finish,
                  "Web finish".center(pw))
        dlg1.entry("web_color", web_color,
                   "Web material color".center(pw))
        
        dlg1.group_title("Bottom Chord Extensions")
        dlg1.menu("extend_leftBC", ('Yes', 'No'), extend_leftBC,
                  "Extend LEFT BC".center(pw))
        dlg1.entry("bc_set_left", dim_print(bc_set_left),
                   "Left end setback".center(pw))
        dlg1.menu("extend_rightBC", ('Yes', 'No'), extend_rightBC,
                  "Extend RIGHT BC".center(pw))
        dlg1.entry("bc_set_right", dim_print(bc_set_right),
                   "Right end setback".center(pw))

        dlg1.tab("Image")
        dlg1.group_title("Even Spacing, 8 Panels")
        dlg1.image(image_name1)
        
        dlg1.tabset_end()
        
        try:
            dd1 = dlg1.done()
        except ResponseNotOK:
            break
        
        for key, value in dd1.items():
            exec "%s = %s" % (key, repr(value)) in None

        if print_doc == "Yes":
            print __doc__
            return

        export_data(os.path.join(default_file_path, def_file),
                    dd1, script_name, 'TS')
        
        ptList = [mem1.left.location + mem1.translate(firstWP, 0, 0),]
        cc_list = [add_cc(ptList[0], cc_rad, cc_color),]
        if option == "Even Spacing":
            distLeft = 0.0
            spacing = mem1.left.location.dist(mem1.right.location)/float(number_panels)
            for i in range(number_panels-1):
                distLeft += spacing
                ptList.append(mem1.left.location + mem1.translate(distLeft, 0, 0))
                cc_list.append(add_cc(ptList[-1], cc_rad, cc_color))
        elif option == "Pick Points":
            while True:
                pt = PointLocate("Select panel point")
                if pt:
                    ptList.append(pt)
                    cc_list.append(add_cc(pt, cc_rad, cc_color))
                else:
                    break
        elif option == "Select Bms/Jsts":
            bm_list = memAreaSelect("Select BEAM or JOIST members by area",
                                     ['Joist', 'Beam'], ['All', ])
            for bm in bm_list:
                B = LineLineIntersect3D(mem1.left.location,
                                        mem1.right.location,
                                        bm.left.location,
                                        bm.right.location)
                if B.Pmem1 and B.on_segment1:
                    ptList.append(B.Pmem1)
                else:
                    Warning("One of the selected beams is not supported by the girder.")
            
        ptList.append(mem1.right.location + mem1.translate(-firstWP, 0, 0))
        if len(ptList) < 4:
            Warning("There must be at least 3 panels. OK to EXIT")
            return

        # Convert ptList to local coordinates
        XList = []
        for i, pt in enumerate(ptList):
            ptLoc = mem1.trans_to_local(pt - mem1.left_location)
            XList.append(ptLoc.x-(ptLoc.y*tan(dtor(mem1.slope))))
        XList.sort()

        chordK = Shape(chord_mtrl).k
        chordThk = Shape(chord_mtrl).thick
        webLeg = Shape(web_mtrl).LL_depth

        ClearSelection()
        for mem in jst_list:
            SelectionAdd(mem)
            RedrawScreen()
            ## ADD WEB MATERIAL ###############################
            rise = mem.depth-bottWPdist
            number_panels = len(XList)-1
            # add web diagonals except last one
            for i in range(number_panels-1):
                # web material Z rotation in radians
                Zrot = atan2(rise, (XList[i+1]-XList[i]))
                WPdist = ((XList[i+1]-XList[i])**2 + rise**2)**0.5
                if not i%2:
                    ptWP1 = mem.left.location + mem.translate(XList[i], 0, web_space/2+chordThk)
                    ptWP2 = mem.left.location + mem.translate(XList[i], 0, -web_space/2-chordThk)
                    if i == 0:
                        XoffLeft = chordK/sin(Zrot)
                    else:
                        XoffLeft = max([chordK/sin(Zrot), webLeg*tan(Zrot)])
                    XoffRight = max([minGap, chordK/sin(Zrot)+webLeg/tan(Zrot)-bottWPdist/sin(Zrot)])
                    add_web_diag(mem, ptWP1, WPdist, XoffLeft, XoffRight, "In", -rtod(Zrot))
                    add_web_diag(mem, ptWP2, WPdist, XoffLeft, XoffRight, "Out", -rtod(Zrot))
                else:
                    ptWP1 = mem.left.location + mem.translate(XList[i], -mem.depth+bottWPdist, web_space/2+chordThk)
                    ptWP2 = mem.left.location + mem.translate(XList[i], -mem.depth+bottWPdist, -web_space/2-chordThk)
                    XoffLeft = max([minGap, chordK/sin(Zrot)+webLeg/tan(Zrot)-bottWPdist/sin(Zrot)])
                    XoffRight = max([chordK/sin(Zrot), webLeg*tan(Zrot)])
                    add_web_diag(mem, ptWP1, WPdist, XoffLeft, XoffRight, "In", rtod(Zrot))
                    add_web_diag(mem, ptWP2, WPdist, XoffLeft, XoffRight, "Out", rtod(Zrot))
                    
            # add last diagonal
            Zrot = atan2(rise, (XList[-1]-XList[-2]))
            WPdist = ((XList[-1]-XList[-2])**2 + rise**2)**0.5
            XoffLeft = max([minGap, chordK/sin(Zrot)+webLeg/tan(Zrot)-bottWPdist/sin(Zrot)])
            XoffRight = chordK/sin(Zrot)
            ptWP1 = mem.left.location + mem.translate(XList[-2], -mem.depth+bottWPdist, web_space/2+chordThk)
            ptWP2 = mem.left.location + mem.translate(XList[-2], -mem.depth+bottWPdist, -web_space/2-chordThk)
            add_web_diag(mem, ptWP1, WPdist, XoffLeft, XoffRight, "In", rtod(Zrot))
            add_web_diag(mem, ptWP2, WPdist, XoffLeft, XoffRight, "Out", rtod(Zrot))
            
            # add web verticals
            for dist in XList[1:-1]:
                ptWP = mem.left.location + mem.translate(dist, -chordK, 0)
                add_web_vert(mem, ptWP, mem.depth-(chordK*2), -90)

            ## ADD CHORD MATERIAL #############################
            ptWP1 = mem.left.location + mem.translate(mem.left.setback-mem.left.conn_setback, 0.0, web_space/2)
            ptWP2 = mem.right.location + mem.translate(-mem.right.setback+mem.right.conn_setback, 0.0, web_space/2)
            ptWP3 = mem.left.location + mem.translate(mem.left.setback-mem.left.conn_setback, 0.0, -web_space/2)
            ptWP4 = mem.right.location + mem.translate(-mem.right.setback+mem.right.conn_setback, 0.0, -web_space/2)

            if extend_leftBC == 'Yes':
                ptWP5 = mem.left.location + mem.translate(bc_set_left-(mem.depth*tan(dtor(mem1.slope))), -mem.depth, -web_space/2)
                ptWP7 = mem.left.location + mem.translate(bc_set_left-(mem.depth*tan(dtor(mem1.slope))), -mem.depth, web_space/2)
            else:
                ptWP5 = mem.left.location + mem.translate(XList[1]-bcEndDist, -mem.depth, -web_space/2)
                ptWP7 = mem.left.location + mem.translate(XList[1]-bcEndDist, -mem.depth, web_space/2)
                
            if extend_rightBC == 'Yes':
                ptWP6 = mem.right.location + mem.translate(-bc_set_right-(mem.depth*tan(dtor(mem1.slope))), -mem.depth, -web_space/2)
                ptWP8 = mem.right.location + mem.translate(-bc_set_right-(mem.depth*tan(dtor(mem1.slope))), -mem.depth, web_space/2)
            else:
                ptWP6 = mem.left.location + mem.translate(XList[-2]+bcEndDist, -mem.depth, -web_space/2)
                ptWP8 = mem.left.location + mem.translate(XList[-2]+bcEndDist, -mem.depth, web_space/2)

            add_chord(mem, ptWP1, ptWP2, 'In', 0.0)
            add_chord(mem, ptWP3, ptWP4, 'Out', 0.0)
            add_chord(mem, ptWP5, ptWP6, 'In', 180.0)
            add_chord(mem, ptWP7, ptWP8, 'Out', 180.0)

            ## Set joist member properties
            ## NOTE: MEMBER PROPERTIES MUST EXIST!
            try:
                MemberPropertySet(mem, chordProperty, chord_mtrl)
                MemberPropertySet(mem, webProperty, str(web_space))
            except member.error, e:
                pass
            SelectionRemove(mem)

        ClearSelection()
        remove_cc(cc_list)
        if not yes_or_no('Select another joist?'):
            return
  
## end run_script() #########################################################
if __name__ == '__main__':
    try:
        main()
    finally:
        ClearSelection()
        del main

