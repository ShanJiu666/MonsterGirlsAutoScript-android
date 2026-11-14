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
cost, plan = MV.solve(prob, max_states=60000, max_secs=10, report={})
print('cost', cost, 'plan', plan)
cp = prob.cells_for_plan(plan or [])
def g(c):
    r, cc = c // COLS + 1, c % COLS + 1
    d = mg.get((r, cc)) or {}
    return (r, cc), d.get('revealed'), d.get('ratio'), d.get('floor_lit'), d.get('sid')
for i, t in enumerate(cp):
    rc, bi, w = t
    b = prob.blocks.get(bi)
    mem = [g(c) for c in (b.cells or [])]
    print('step', i, 'pick', rc, 'bi', bi, 'cost', w,
          'block_obs', getattr(b, 'observed', None), 'n_mem', len(mem))
    for m in mem:
        print('    ', m)
print('--- blocks in visible that are observed, members ---')
vis = prob.visible(frozenset())
for bi in range(len(prob.blocks)):
    b = prob.blocks[bi]
    if getattr(b, 'observed', False) and b.cells:
        mem = [g(c) for c in b.cells]
        lit = [m for m in mem if m[1]]
        if len(mem) > 1:
            print('bi', bi, 'cells', b.cells, 'nmem', len(mem), 'nlit', len(lit))
