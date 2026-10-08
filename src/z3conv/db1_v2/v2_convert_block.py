    # ---- v2: bolt groups of the record-discovered engines (7.5x-8.x): decode, place, holes (db1bolts2; interface of db1bolts)
    import db1bolts, db1bolts2
    BOLTS2 = os.environ.get('DB1_BOLTS', '1') == '1'
    bgroups = []; bstats = {}; bdec = None
    if BOLTS2:
        try:
            bdec = db1bolts2.BoltDecoder(db, pts, cs, lay)
            bgroups = bdec.decode(M)
        except Exception as ex_:
            import traceback
            bstats['decode_error'] = f'{type(ex_).__name__}: {str(ex_)[:200]} {traceback.format_exc()[-400:]}'; bgroups = []
    bseq = {g['seq']: g for g in bgroups}

    def is_bolt_record(m):
        """member records whose attribute record is a bolt group (obj_type 10) are not parts"""
        if m.get('seq') in bseq: return True
        if m.get('prof') and db1bolts.P_BOLTPROF.match(m['prof'].strip().upper()): return True
        if m.get('attr') is None: return False
        rr = db.lookup_all(m['attr'])
        return bool(rr) and int(db.I([rr[0] + 13])[0]) == 10
    REGION = {}
    _body0 = body

    def body(m):
        """the builder's body() + the part's section region (bolt-axis / ply intervals and holes)"""
        b_ = _body0(m)
        if BOLTS2 and b_[0] is not None:
            try:
                if b_[3] == 'contour_plate':
                    pts_ = [tuple(p.Coordinates) for p in b_[1].OuterCurve.Points]
                    if len(pts_) > 1 and pts_[0] == pts_[-1]: pts_ = pts_[:-1]
                    REGION[m['seq']] = (pts_, [])
                else:
                    kind_, v_, how_ = section_for(m['prof'], cat)
                    reg_ = db1bolts.outline(kind_, v_) if kind_ else None
                    if reg_ is not None: REGION[m['seq']] = reg_
            except Exception:
                pass
        return b_

    def std_fn(s_, d_):
        """the model folder's own bolt catalog first, then Tekla's own dims (IFC harvest), then the standards tables"""
        cg_ = getattr(db1bolts, 'catalog_geometry', None)
        sg_ = cg_(s_, d_) if cg_ else None
        return sg_ or db1bolts.standard_geometry(s_, d_)
    cut_body = {}
    for m in M:
        if m.get('cut'):
            b = body(m)
            if b[0] is not None: cut_body[m['seq']] = b[:3]
            else: why['cut_body_unbuilt'] += 1
    applied = 0
    plist = []          # z3: one record per decoded part: [seq, profile, category, status, how/reason, GlobalId, n_cuts]
    # pass 1: bodies of the written parts (frame, depth, section region) for bolt placement and holes
    bodies = {}; isbolt = {}
    for m in M:
        if m.get('cut'): continue
        isbolt[id(m)] = BOLTS2 and is_bolt_record(m)
        if isbolt[id(m)]: continue
        bodies[id(m)] = body(m)
    BG = {}; HP = {}
    if BOLTS2 and bgroups:
        parts = {}; part_seqs = set()
        for m in M:
            b = bodies.get(id(m))
            if b and b[0] is not None:
                parts[m['seq']] = (b[0], b[2]); part_seqs.add(m['seq'])
        try:
            blinks = bdec.links(set(bseq), part_seqs)
            bstats['link_layout'] = getattr(bdec, 'link_layout', None)
            BG, HP, pst = db1bolts2.plan(bgroups, parts, REGION, blinks, std_fn, db1bolts.washer_t)
            bstats.update({str(k): v for k, v in pst.items()})
        except Exception as ex_:
            import traceback
            bstats['plan_error'] = f'{type(ex_).__name__}: {str(ex_)[:200]} {traceback.format_exc()[-400:]}'; BG, HP = {}, {}
    hole_prof = {}; holes_cut = 0; holes_round_for_slot = 0; holes_tol = 0
    # pass 2: write
    for m in M:
        if m.get('cut'):
            why['cut_part_excluded'] += 1; continue
        if isbolt.get(id(m)):
            continue
        b = bodies.get(id(m)) or body(m)
        if b[0] is None:
            why[b[1]] += 1; unres[m['prof'] or '<none>'] += 1
            plist.append([m.get('seq'), m.get('prof'), part_cat(m.get('prof'), b[1]), 'skipped', b[1], None, 0]); continue
        cuts = [cut_body[c] for c in links.get(m['seq'], []) if c in cut_body]
        applied += len(cuts)
        nh = 0
        for bb, z0, z1 in HP.get(m['seq'], []):
            dh, dec_ = db1bolts.hole_diameter(bb)
            holes_tol += 1 if dec_ else 0
            key = round(dh, 2)
            if key not in hole_prof:
                hole_prof[key] = out.profile('BOLT_HOLE_D%g' % key, 'CIRC', [dh / 2])
            p0 = bb['p0']
            cuts = cuts + [((p0 + bb['ez'] * (z0 - 2.0), bb['ez'], bb['ex']), hole_prof[key], (z1 - z0) + 4.0)]
            nh += 1
        holes_cut += nh
        cat_ = part_cat(m.get('prof'), b[3])
        cls = 'IfcPlate' if cat_ in ('connection', 'other') and b[3] not in ('parametric_stud_shank', 'parametric_anchor') else (
              'IfcMechanicalFastener' if b[3] in ('parametric_stud_shank', 'parametric_anchor') else 'IfcBeam')
        e = out.element(cls, approx_name(m['prof'], b[3]), b[0], b[1], b[2], cuts)
        plist.append([m.get('seq'), m.get('prof'), cat_, 'written', b[3], e.GlobalId, len(cuts)])
        src[b[3]] += 1
    # bolt groups: decoded ones written (or holes only); undecoded bolt records listed as skipped bolt groups
    for g in bgroups:
        bl_all = BG.get(g['seq']) or []
        bl = [bb for bb in bl_all if not bb.get('holes_only')]
        nm0 = g.get('prof') or f"BOLT {g['d']:g}x{g['L']:g}"
        if bl_all and not bl:
            plist.append([g['seq'], nm0, 'feature', 'written', 'holes_only_group', None, 0]); src['holes_only_group'] += 1
            continue
        if not bl:
            plist.append([g['seq'], nm0, 'connection', 'skipped', 'bolt_group_unplaced', None, 0]); why['bolt_group_unplaced'] += 1
            continue
        sg = bl[0].get('std'); tags = []
        if not sg: tags.append('head and nut nominal (1.6d across flats, 0.65d / 0.8d): no table for this standard/diameter')
        if any(bb.get('tol') is None for bb in bl): tags.append('hole = d + standard clearance (tolerance not decoded)')
        if any(bb.get('head_up') and not bb.get('axial_decoded') for bb in bl): tags.append('axial position from the connected plies (record grip centre differs)')
        if any(not bb.get('head_up') for bb in bl): tags.append('axial position unknown (no connected ply on the axis): shank centred on the bolt plane')
        if any(bb.get('wash_head') or bb.get('wash_nut') or bb.get('wash_2') for bb in bl) and not (sg and (sg.get('washer_t') or 'ISO' in sg.get('family', ''))):
            tags.append('washer thickness nominal')
        if (g.get('slot_parts') or 0) and ((g.get('slot_x') or 0) > 0 or (g.get('slot_y') or 0) > 0):
            tags.append('slotted holes cut as round holes (slotted parts not verified)'); holes_round_for_slot += 1
        nm = f"{nm0} {g.get('standard') or ''}" + (f" ({sg['family']}, {sg.get('mapping', '')})" if sg else '')
        nm = f"{nm} [approx: {'; '.join(tags)}]" if tags else nm
        e = out.bolt_group(nm.replace('  ', ' '), bl)
        plist.append([g['seq'], nm0, 'connection', 'written', 'bolt_group', e.GlobalId, 0]); src['bolt_group'] += 1
    for m in M:
        if isbolt.get(id(m)) and m['seq'] not in bseq:
            plist.append([m.get('seq'), m.get('prof'), 'connection', 'skipped', 'bolt_group_excluded', None, 0]); why['bolt_group_excluded'] += 1
    if BOLTS2 and os.environ.get('DB1_BOLT_DEBUG'):
        st['bolt_debug'] = {str(g['seq']): [[round(float(u), 3), round(float(v), 3), (round(float(bb['zh']), 3) if bb.get('zh') is not None else None),
                                              [round(float(x), 3) for x in bb['grip']] if bb.get('grip') else None, bb.get('axial')]
                                             for (u, v), bb in zip(g['uv'], BG.get(g['seq']) or [])] for g in bgroups}
    if BOLTS2:
        _all = [bb for g in bgroups for bb in (BG.get(g['seq']) or [])]
        _real = [bb for bb in _all if not bb.get('holes_only')]
        _wn = 0
        for bb in _real:
            _w = (bb.get('wash_head') or 0) + (bb.get('wash_nut') or 0) + (bb.get('wash_2') or 0)
            if _w and not db1bolts.washer_exact(bb) and not ((bb.get('std') or {}).get('washer_t')): _wn += _w
        st['bolt_stats'] = dict(bstats, groups_decoded=len(bgroups), groups_written=src.get('bolt_group', 0),
                                holes_only_groups=src.get('holes_only_group', 0), holes_cut=holes_cut, holes_tolerance_decoded=holes_tol,
                                # keys read by the grader (build_index.classify_db1), same meaning as the old-engine writer's
                                bolts=len(_all), standard_table_geometry=sum(1 for bb in _all if bb.get('std')),
                                holes_nominal_clearance=holes_cut - holes_tol,
                                washers=sum((bb.get('wash_head') or 0) + (bb.get('wash_nut') or 0) + (bb.get('wash_2') or 0) for bb in _real),
                                washers_nominal=_wn,
                                washer_side_inferred=sum(1 for bb in _real if (bb.get('wash_2') or 0) > 0),
                                bolts_shifted_to_plies=sum(1 for bb in _real if bb.get('head_up') and not bb.get('axial_decoded')),
                                bolts_without_holed_part=sum(1 for bb in _all if not bb.get('grip')),
                                slotted_groups_cut_round=holes_round_for_slot,
                                decoder={str(k): v for k, v in (bdec.stats.items() if bdec else [])},
                                standards=dict(collections.Counter(g.get('standard') or '?' for g in bgroups)),
                                geometry_sources=dict(collections.Counter(((BG.get(g['seq']) or [{}])[0].get('std') or {}).get('source') or 'nominal' for g in bgroups if BG.get(g['seq']))),
                                hole_diameter='stored bolt d + decoded tolerance (8.x group attribute / bolt string field 3)',
                                writer='db1bolts2 v2 (7.5x-9.x records) + db1bolts.bolt_group')
