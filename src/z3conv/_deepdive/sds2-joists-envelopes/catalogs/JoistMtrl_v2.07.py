##  JoistMtrl.py Version 2.07
##  Copyright (c) 2009 Bruce Vaughan, BV Detailing & Design, Inc.
##  All rights reserved.
##  NOT FOR SALE. The software is provided "as is" without any warranty.
#######################################################################
'''
Add web and chord material to a joist member.

## Version 1.01 (8/5/07) -  Add ClearSelection() to work in SDS/2 7.1xx
## Version 2.00 (10/5/07) - Add dialog box, encapsulate in run_script()
##                          Material file browse
##                          Add bottom chord extensions
##                          Save default values
##                          Convert web_dia to float in dd1
##                          Make correction to web_dia assignment
## Version 2.01 (6/14/08) - Add colors, grade, finish
## Version 2.02 (7/1/08) -  Add import Job, Fabricator
## Version 2.03 (8/3/08) -  Option to enter # of panels
## Version 2.04 (9/10/08) - Change break to return, addtest for empty
##                          jst_list
## Version 2.05 (10/12/08) - Set joist member properties "chord_mtrl"
##                           and "web_dia"
## Version 2.06 (3/8/09) - Add variable selectionType ('Area', 'Single')
## Version 2.07 (7/12/09) - Add member informaton to dialog box
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
from rnd_bar import RndBar
from rolled_section import RolledSection
from job import Job
from fab import Fabricator

from macrolib.MemSelection import mem_select, memAreaSelect
from macrolib.FileDefaults import import_data, export_data
from macrolib.PointPlane3D import validColTup

def main():
    #####################################################################
    ## Variables section
    # system path for defaults file
    default_file_path = os.path.join(os.getcwd(), "macro", "Defaults")

    # defaults file name
    def_file = "JoistMtrl.txt"
    script_name = "JoistMtrl_v2.06.py"

    web_diaList = ['0','1/4','3/8','1/2','5/8','3/4','7/8','1']
    finishList = ["None", "Red Oxide", "Yellow Zinc", "Gray Oxide", "Sandblasted", "Blued Steel", "Galvanized"]
    chordGradeList = Job().steel_grades("Angle").keys()
    webGradeList = Job().steel_grades("Plate").keys()
    number_panels_options = ['Auto',2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20]
    
    # Type of user selection of joist members - valid choices: ('Area', 'Single')
    selectionType = 'Area'
    #####################################################################
    ## Defaults section
    web_dia = 0.5
    web_finish = "Yellow Zinc"
    web_grade = webGradeList[0]
    chord_mtrl = 'L1 1/2x1 1/2x3/16'
    chord_grade = chordGradeList[0]
    chord_finish = "Gray Oxide"
    chord_extend = 4.0
    bc_ext_left = 'No'
    bc_set_left = 4.5
    bc_ext_right = 'No'
    bc_set_right = 4.5
    chord_color = '135,135,135'
    web_color = '255,0,0'
    number_panels = 'Auto'

    def add_web(mem, pt, dist, a):
        rb1 = RndBar()
        rb1.member = mem
        rb1.pt1 = pt
        rb1.pt2 = pt + mem.translate(dist, 0.0, 0.0)
        rb1.grade = web_grade
        rb1.centered = "Yes"
        rb1.bar_diameter = web_dia
        rb1.work_pt_dist = dist
        rb1.length = dist
        rb1.mtrl_type = "Round bar"
        rb1.mtrl_usage = 'Joist Web'
        rb1.finish = web_finish
        rb1.color = validColTup(web_color)
        rb1.ref_pt_offset = (0, 0, 0)
        rb1.add()
        rb1.rotate(rb1.member, (0.000000, 0.000000, a))

    def add_chord(mem, pt1, pt2, toe_dir, a):
        rl1 = RolledSection()
        rl1.member = mem
        rl1.pt1 = pt1
        rl1.pt2 = pt2
        rl1.section_size = chord_mtrl
        rl1.grade = chord_grade
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
        rl1.ref_pt_offset = (0.000000, 0.000000, 0.000000)
        rl1.add()
        rl1.rotate(rl1.member, (a, 0.000000, 0.000000))
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
            jst_list = mem_select("Select a JOIST member", ['Joist', ], ['All', ])
        elif selectionType == 'Area':
            jst_list = memAreaSelect("Select JOIST members by area", ['Joist', ], ['All', ])
        else:
            Warning("Invalid string value for variable selectionType")
            return
        
        if not jst_list:
            return
        mem1 = jst_list[0]
        ## DIALOG BOX 1 #################################
        dlg1 = Dialog("Joist Material")
        dlg1.menu('number_panels', number_panels_options, number_panels, 'Number of web panels')
        
        dlg1.group_title("Joist Information (mem1)")
        dlg1.line("Size: %s  Series: %s" % (mem1.size, mem1.series))
        dlg1.line("Left setback: %s  Left conn_setback: %s" % (mem1.left.setback, mem1.left.conn_setback))
        dlg1.line("Right setback: %s  Right conn_setback: %s" % (mem1.right.setback, mem1.right.conn_setback))
        
        dlg1.group_title("Chord Material")
        dlg1.mtrl_browse('chord_mtrl', ("Angle",), chord_mtrl, "Chord material size" )
        dlg1.menu("chord_grade", chordGradeList, chord_grade, "Chord material grade")
        dlg1.menu("chord_finish", finishList, chord_finish, "Chord finish")
        dlg1.entry("chord_color", chord_color, "Chord material color")
        
        dlg1.group_title("Web Material")
        dlg1.menu("web_dia", web_diaList, dim_print(web_dia), "Diameter of web members")
        dlg1.menu("web_grade", webGradeList, web_grade, "Web material grade")
        dlg1.menu("web_finish", finishList, web_finish, "Web finish")
        dlg1.entry("web_color", web_color, "Web material color")
        
        dlg1.group_title("Bottom Chord Extensions")
        dlg1.menu("bc_ext_left", ['Yes', 'No'], bc_ext_left, "Extend BC LEFT end")
        dlg1.entry("bc_set_left", dim_print(bc_set_left), "LEFT end setback")
        dlg1.menu("bc_ext_right", ['Yes', 'No'], bc_ext_right, "Extend BC RIGHT end")
        dlg1.entry("bc_set_right", dim_print(bc_set_right), "RIGHT end setback")
        
        try:
            dd1 = dlg1.done()
        except ResponseNotOK:
            break

        # When fraction is selected from menu in dialog box, 'str' type is retained.
        # Convert 'str' to 'float' using 'param.dim'
        
        dd1["web_dia"] = dim(dd1["web_dia"])
        
        for key, value in dd1.items():
            exec "%s = %s" % (key, repr(value)) in None

        export_data(os.path.join(default_file_path, def_file), dd1, script_name, 'TS')

        # series = mem.series # 'K'
        # mem.left.conn_setback
        for mem in jst_list:
            ## ADD WEB MATERIAL ###############################
            rise = mem.depth-1
            if number_panels == 'Auto':
                run = mem.left.location.dist(mem.right.location)-12-mem.left.setback-mem.right.setback
                panels = int(run/(rise*2))
                panel_width = (run/panels)

                ptWP = mem.left.location + mem.translate(mem.left.setback+6.0, -0.5, 0.0)
                ptListTop = [ptWP+mem.translate(panel_width*i, 0.0, 0.0) for i in range(panels)]
                ptListBott = [ptWP+mem.translate(panel_width*i+panel_width/2, -rise, 0.0) for i in range(panels)]
            
            else:
                # The number of panels represents the number of panel spaces along the top chord
                run = mem.left.location.dist(mem.right.location)-mem.left.setback-mem.right.setback
                panels = number_panels
                panel_width = (run/panels)

                ptWP = mem.left.location + mem.translate(mem.left.setback, -0.5, 0.0)
                # omit the first and last diagonals from point lists
                # add them in separately
                # dist from joist WP to 1st diagonal WP is hard coded at 6"
                end_diag = (rise**2 + ((panel_width/2)-6)**2)**0.5
                angle_deg = atan2(rise, (panel_width/2)-6) * 180.0 / pi
                add_web(mem, ptWP+mem.translate(6,0,0), end_diag, -angle_deg)
                add_web(mem, ptWP+mem.translate(panel_width*(number_panels-1)+panel_width/2, -rise, 0.0), end_diag, angle_deg)
                
                ptListTop = [ptWP+mem.translate(panel_width*i, 0.0, 0.0) for i in range(1, panels)]
                ptListBott = [ptWP+mem.translate(panel_width*i+panel_width/2, -rise, 0.0) for i in range(0, panels-1)]
         
            diag = (rise**2 + (panel_width/2)**2)**0.5
            angle_deg = atan2(rise, (panel_width/2)) * 180.0 / pi

            if web_dia > 0.0:
                for pt in ptListTop:
                    add_web(mem, pt, diag, -angle_deg)

                for pt in ptListBott:
                    add_web(mem, pt, diag, angle_deg)
                
            ## ADD CHORD MATERIAL #############################
            
            ptWP1 = mem.left.location + mem.translate(mem.left.setback-mem.left.conn_setback, 0.0, web_dia/2)
            ptWP2 = mem.right.location + mem.translate(-mem.right.setback+mem.right.conn_setback, 0.0, web_dia/2)
            ptWP3 = mem.left.location + mem.translate(mem.left.setback-mem.left.conn_setback, 0.0, -web_dia/2)
            ptWP4 = mem.right.location + mem.translate(-mem.right.setback+mem.right.conn_setback, 0.0, -web_dia/2)
            '''
            ptWP1 = mem.left.location + mem.translate(mem.left.setback, 0.0, web_dia/2)
            ptWP2 = mem.right.location + mem.translate(-mem.right.setback, 0.0, web_dia/2)
            ptWP3 = mem.left.location + mem.translate(mem.left.setback, 0.0, -web_dia/2)
            ptWP4 = mem.right.location + mem.translate(-mem.right.setback, 0.0, -web_dia/2)'''

            if bc_ext_left == 'Yes':
                ptListBott[0] = mem.left.location + mem.translate(chord_extend + bc_set_left, -rise - 0.5, 0.0)
            if bc_ext_right == 'Yes':
                ptListBott[-1] = mem.right.location + mem.translate(-chord_extend - bc_set_right, -rise - 0.5, 0.0)
            
            ptWP5 = ptListBott[0] + mem.translate(-chord_extend, -0.5, -web_dia/2)
            ptWP6 = ptListBott[-1] + mem.translate(chord_extend, -0.5, -web_dia/2)
            ptWP7 = ptListBott[0] + mem.translate(-chord_extend, -0.5, web_dia/2)
            ptWP8 = ptListBott[-1] + mem.translate(chord_extend, -0.5, web_dia/2)

            add_chord(mem, ptWP1, ptWP2, 'In', 0.0)
            add_chord(mem, ptWP3, ptWP4, 'Out', 0.0)
            add_chord(mem, ptWP5, ptWP6, 'In', 180.0)
            add_chord(mem, ptWP7, ptWP8, 'Out', 180.0)

            ## Set joist member properties
            ## NOTE: MEMBER PROPERTIES MUST EXIST!
            try:
                MemberPropertySet(mem, "chord_mtrl", chord_mtrl)
                MemberPropertySet(mem, "web_dia", str(web_dia))
            except member.error, e:
                pass
            ClearSelection()        

        if not yes_or_no('Select another joist?'):
            return
  
## end run_script() #########################################################
if __name__ == '__main__':
    try:
        main()
    finally:
        ClearSelection()
        del main

