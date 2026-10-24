"""Photo gallery: style A with many portraits (radial feather mask), plus white-background cutouts.

Usage: gallery.py OUT_DIR  -> OUT_DIR/p<NN>.jpg and OUT_DIR/gallery.jpg (labelled grid).
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import proto  # noqa: E402  (reuses G, fonts, LIB)

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
# photo -> (focus x fraction of the person in the scaled image, white background?)
PHOTOS = {"67": (0.5, False)} if len(sys.argv) > 2 else {"42": (0.42, False), "25": (0.45, False), "72": (0.5, False), "32": (0.5, False), "12": (0.5, False),
          "06": (0.55, False), "13": (0.5, False), "18": (0.5, False), "19": (0.55, False), "20": (0.45, False),
          "24": (0.5, False), "02": (0.62, False), "67": (0.5, False), "11": (0.5, True), "37": (0.5, True),
          "71": (0.5, True), "16": (0.5, False), "23": (0.6, False)}


def portrait(g, name, focus, white, w=640, h=720):
    src = g.inp(proto.LIB / f"{name}.jpg")
    if white:  # key out the white studio background
        return g.add(f"scale=-2:{h},crop='min(iw,{w})':{h}:'max(0,iw*{focus}-{w}/2)':0,"
                     "colorkey=0xffffff:0.12:0.08,format=rgba", src)
    # cover the frame, then an elliptical feather that reaches 0 on every edge (+ a soft left ramp)
    return g.add(f"scale='max({w},iw*{h}/ih)':'max({h},ih*{w}/iw)',crop={w}:{h}:'min(iw-{w},max(0,iw*{focus}-{w}/2))':0,"
                 "format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                 "a='255*clip(2.2*(1-hypot((X-W*0.56)/(W*0.52),(Y-H*0.58)/(H*0.62))),0,1)*clip(X/180,0,1)'", src)


def style_a(name, focus, white, out):
    work = OUT / f"w{name}"
    work.mkdir(exist_ok=True)
    g = proto.G(work)
    bg = g.add("color=c=0x16100b:s=1280x720,format=rgb24,"
               "geq=r='22+70*exp(-((X-360)^2+(Y-330)^2)/90000)':g='16+45*exp(-((X-360)^2+(Y-330)^2)/90000)'"
               ":b='11+18*exp(-((X-360)^2+(Y-330)^2)/90000)'")
    por = portrait(g, name, focus, white)
    b = g.add("overlay=640:0", f"{bg}][{por}")
    b = g.add("vignette=PI/5", b)
    b = g.gold_text(b, "KINH", proto.SERIF, 64, 70, 70)
    b = g.gold_text(b, "ĐỊA TẠNG", proto.SERIF, 150, 55, 140)
    b = g.gold_text(b, "BỒ TÁT BỔN NGUYỆN", proto.SERIF, 62, 66, 298)
    b = g.text(b, "CHỦ GIẢNG: PHÁP SƯ TỊNH KHÔNG", proto.SANS, 26, "0xe8d6b0", 72, 400)
    b = g.add("drawbox=x=70:y=480:w=250:h=92:color=0xb3261e:t=fill,drawbox=x=70:y=480:w=250:h=92:color=0xf2c46a:t=3", b)
    b = g.gold_text(b, "TẬP 74", proto.OLD, 64, "70+(250-text_w)/2", 492, top="0xfff6c8", bottom="0xe0a93c", stroke=2)
    b = g.text(b, f"Ảnh {name}", proto.SANS, 34, "yellow", 1110, 660, border=3)
    g.render(b, out)


files = []
for name, (focus, white) in PHOTOS.items():
    out = OUT / f"p{name}.jpg"
    style_a(name, focus, white, out)
    files.append(out)
inputs = sum((["-i", str(f)] for f in files), [])
cols = 3
rows = -(-len(files) // cols)
graph = ";".join(f"[{i}]scale=640:360[v{i}]" for i in range(len(files)))
graph += ";" + "".join(f"[v{i}]" for i in range(len(files))) + \
    f"xstack=inputs={len(files)}:layout=" + "|".join(f"{(i % cols) * 640}_{(i // cols) * 360}" for i in range(len(files)))
subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-frames:v", "1", "-q:v", "3",
                str(OUT / "gallery.jpg")], check=True)
print(OUT / "gallery.jpg", rows)
