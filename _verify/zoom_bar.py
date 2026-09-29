import sys
from PIL import Image

src = sys.argv[1]
dst = sys.argv[2]
y0 = int(sys.argv[3]) if len(sys.argv) > 3 else 1700
y1 = int(sys.argv[4]) if len(sys.argv) > 4 else 1840

im = Image.open(src)
print('full', im.size)
c = im.crop((0, y0, im.size[0], min(y1, im.size[1])))
c = c.resize((c.size[0] * 2, c.size[1] * 3), Image.NEAREST)
c.save(dst)
print('saved', dst, c.size)
