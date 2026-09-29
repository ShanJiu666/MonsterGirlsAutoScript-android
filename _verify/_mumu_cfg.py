import json, io, glob, os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

for f in glob.glob(r'D:/MuMu Player 12/vms/*/configs/extra_config.json'):
    inst = os.path.basename(os.path.dirname(os.path.dirname(f)))
    d = json.load(io.open(f, encoding='utf-8'))
    out = []

    def walk(o, p=''):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, p + '.' + k)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, p + '[%d]' % i)
        else:
            if any(t in p.lower() for t in ('width', 'height', 'reso', 'dpi', 'size', 'render', 'name')):
                out.append((p, o))

    walk(d)
    print('== %s  playerName=%s  keys=%d' % (inst, d.get('playerName'), len(d)))
    for p, v in out[:14]:
        print('    %s = %s' % (p, v))
