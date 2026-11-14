import os, sys, types
HERE = 'D:/MGAS/android_autoexplore'
sys.path.insert(0, HERE + '/app/src/main/python')
os.environ.setdefault('MAPBOT_ROOT', HERE + '/app/src/main/assets/mapbot_pack')
os.environ.pop('MAPBOT_ANDROID', None)
mod = types.ModuleType('rapidocr_onnxruntime'); mod.RapidOCR = object
sys.modules['rapidocr_onnxruntime'] = mod
for m in ('airtest', 'airtest.core', 'airtest.core.api'):
    sys.modules[m] = types.ModuleType(m)
sys.modules['airtest.core.api'].touch = lambda *a, **k: None
import cv2, spots as SP, marks as MK, explore_loop as EL, mapsim as MS, mapsolve as MV
COLS = MV.COLS
img = cv2.imread('D:/MGAS/_tmpman/run_new.png')
cells = SP.Board('S21001').state(img)
mk = MK.scan_board_fast(img)
cd = {'st': cells, 'marks': mk, 'buy': set(), 'buy_hidden': set()}
st = {'obs': {}, 'marks': mk, 'nogo_rc': set(), 'done': set()}
mg = EL._cells_for_model(st, cd, log=[], tag='p', mark_revealed=False)
sim = MS.MapSim.from_observation(mg, SP.spot_rows())
prob = MV.Problem(sim)
ch = MV._build_cache(prob)
bit = ch['bit']
for k in sorted(ch.keys()):
    v = ch[k]
    if isinstance(v, int) and v > 0xff:
        print(k, 'bits', bin(v).count('1'))
camp_nb = ch.get('camp_nb', 0); empt = ch.get('EMPTY_ADJ', 0); obs = ch.get('obs_lit', 0)
b15 = prob.blocks[15]
print('block15 obs', getattr(b15,'observed',None), 'plain', b15.plain, 'cells', b15.cells, 'spot', b15.spot)
print('camp_nb', bool(camp_nb & bit[15]), 'EMPTY_ADJ', bool(empt & bit[15]), 'obs_lit', bool(obs & bit[15]))
print('15 in visible()', 15 in prob.visible(frozenset()))
c = b15.cells[0]; r, cc = c // COLS + 1, c % COLS + 1
d = mg.get((r,cc)) or {}
print('cell', (r,cc), 'revealed', d.get('revealed'), 'ratio', d.get('ratio'), 'floor_lit', d.get('floor_lit'), 'floor', d.get('floor'))
print('camp', prob.camp, 'camp_cells', getattr(prob,'camp_cells',None))
