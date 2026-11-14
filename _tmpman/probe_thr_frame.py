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

def run(png, thr, verbose=False):
    EL.MODEL_REVEAL_RATIO_MIN = thr
    img = cv2.imread(png)
    cells = SP.Board('S21001').state(img)
    mk = MK.scan_board_fast(img)
    cd = {'st': cells, 'marks': mk, 'buy': set(), 'buy_hidden': set()}
    st = {'obs': {}, 'marks': mk, 'nogo_rc': set(), 'done': set()}
    mg = EL._cells_for_model(st, cd, log=[], tag='p', mark_revealed=False)
    sim = MS.MapSim.from_observation(mg, SP.spot_rows())
    prob = MV.Problem(sim)
    cost, plan = MV.solve(prob, max_states=60000, max_secs=10, report={})
    cp = prob.cells_for_plan(plan or [])
    if not cp:
        return cost, None, None
    rc, bi, w = cp[0]
    d = mg.get(rc) or {}
    b = prob.blocks.get(bi)
    return cost, rc, dict(ratio=d.get('ratio'), revealed=d.get('revealed'),
                          floor_lit=d.get('floor_lit'),
                          obs=getattr(b, 'observed', None),
                          order=[tuple(t[0]) for t in cp])

for thr in (0.75, 0.80, 0.82, 0.85):
    for png, lb in (('D:/MGAS/_tmpman/run_new.png', 'map2(出问题)'),
                    ('D:/MGAS/_tmpman/run_map1.png', 'map1')):
        cost, rc, info = run(png, thr)
        print('thr %.2f %s cost %s first %s %s' % (thr, lb, cost, rc, info))
    print()
