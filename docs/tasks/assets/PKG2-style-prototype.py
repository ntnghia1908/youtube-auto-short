"""Thumbnail style prototypes A/B/C (1280x720) for one Địa Tạng episode. ffmpeg only."""
import subprocess
import sys
from pathlib import Path

LIB = Path("/home/ntnghia/.local/share/auto-short/post-images")
FD = Path("/home/ntnghia/.claude/jobs/1c1feb65/tmp/font-dl")
OUT = Path(sys.argv[1]) if __name__ == "__main__" else Path(".")
EP = sys.argv[2] if __name__ == "__main__" and len(sys.argv) > 2 else "74"
OUT.mkdir(parents=True, exist_ok=True) if __name__ == "__main__" else None
SERIF, ANTON, SANS = FD / "PlayfairSCBold.ttf", FD / "Anton.ttf", FD / "ExtraBold.ttf"
OLD = FD / "OldStandardBold.ttf"


class G:
    """Tiny filtergraph builder: text goes through textfiles only."""

    def __init__(self, work):
        self.work, self.parts, self.n, self.inputs = work, [], 0, []

    def inp(self, path):
        self.inputs += ["-i", str(path)]
        return f"{len(self.inputs) // 2 - 1}:v"

    def add(self, s, src=None):
        self.n += 1
        lab = f"s{self.n}"
        self.parts.append((f"[{src}]" if src else "") + s + f"[{lab}]")
        return lab

    def text(self, base, txt, font, size, color, x, y, border=0, bcolor="black", shadow=0):
        self.n += 1
        f = self.work / f"t{self.n}.txt"
        f.write_text(txt, encoding="utf-8")
        extra = f":borderw={border}:bordercolor={bcolor}" if border else ""
        extra += f":shadowx={shadow}:shadowy={shadow}:shadowcolor=black@0.7" if shadow else ""
        return self.add(f"drawtext=fontfile={font}:textfile={f}:expansion=none:fontsize={size}:fontcolor={color}"
                        f":x={x}:y={y}{extra}", base)

    def gold_text(self, base, txt, font, size, x, y, w=1280, h=720, top="0xfff3b0", bottom="0xb8862b", stroke=4):
        """Gradient-filled text: shadow/stroke pass, then a vertical gold gradient through a text mask."""
        sh = self.text(base, txt, font, size, "0x2a1606", f"({x})+3", y + 4, border=stroke, bcolor="0x2a1606")
        self.n += 1
        f = self.work / f"t{self.n}.txt"
        f.write_text(txt, encoding="utf-8")
        mask = self.add(f"color=c=black:s={w}x{h},drawtext=fontfile={font}:textfile={f}:expansion=none:"
                        f"fontsize={size}:fontcolor=white:x={x}:y={y},format=gray")
        grad = self.add(f"gradients=s={w}x{h}:c0={top}:c1={bottom}:x0=0:y0={y}:x1=0:y1={y}+{size}:nb_colors=2:speed=0.00001,format=rgba")
        g = self.add("alphamerge", f"{grad}][{mask}")
        return self.add("overlay=0:0", f"{sh}][{g}")

    def render(self, last, out):
        graph = ";\n".join(self.parts)
        script = self.work / "graph.txt"
        script.write_text(graph, encoding="utf-8")
        p = subprocess.run(["ffmpeg", "-v", "error", "-y", *self.inputs, "-filter_complex_script", str(script),
                            "-map", f"[{last}]", "-frames:v", "1", "-q:v", "2", str(out)], capture_output=True, text=True)
        if p.returncode:
            print(graph)
            raise SystemExit(p.stderr)
        print(out)


def portrait_fade(g, path, crop, place_w, fade, h=720):
    """Scale to height, crop around the person, fade the left edge to transparent."""
    src = g.inp(path)
    cw, cx = crop
    return g.add(f"scale=-2:{h},crop={cw}:{h}:{cx}:0,format=rgba,"
                 f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='255*min(1,X/{fade})*min(1,({h}-Y)/40+0.0)'", src)


def style_a():
    work = OUT / "a"; work.mkdir(exist_ok=True)
    g = G(work)
    # warm dark background with a soft glow behind the title
    bg = g.add("color=c=0x16100b:s=1280x720,format=rgb24,"
               "geq=r='22+70*exp(-((X-360)^2+(Y-330)^2)/90000)':g='16+45*exp(-((X-360)^2+(Y-330)^2)/90000)'"
               ":b='11+18*exp(-((X-360)^2+(Y-330)^2)/90000)'")
    por = portrait_fade(g, LIB / "42.jpg", (700, 170), 700, 220)
    por = g.add("colorchannelmixer=rr=1.05:gg=0.97:bb=0.88", por)
    b = g.add("overlay=600:0", f"{bg}][{por}")
    b = g.add("vignette=PI/5", b)
    b = g.gold_text(b, "KINH", SERIF, 64, 70, 70)
    b = g.gold_text(b, "ĐỊA TẠNG", SERIF, 150, 55, 140)
    b = g.gold_text(b, "BỒ TÁT BỔN NGUYỆN", SERIF, 62, 66, 298)
    b = g.text(b, "CHỦ GIẢNG: PHÁP SƯ TỊNH KHÔNG", SANS, 26, "0xe8d6b0", 72, 400)
    b = g.add("drawbox=x=70:y=480:w=250:h=92:color=0xb3261e:t=fill,drawbox=x=70:y=480:w=250:h=92:color=0xf2c46a:t=3", b)
    b = g.gold_text(b, f"TẬP {EP}", OLD, 64, "70+(250-text_w)/2", 492, top="0xfff6c8", bottom="0xe0a93c", stroke=2)
    g.render(b, OUT / "A-nen-toi-chu-vang.jpg")


def style_b():
    work = OUT / "b"; work.mkdir(exist_ok=True)
    g = G(work)
    bg = g.add("color=c=0x0c0a08:s=1280x720")
    gold = g.add("gradients=s=1280x80:c0=0xf7d774:c1=0xa8761c:c2=0xf3d27a:c3=0x9a6a18:x0=0:y0=0:x1=1280:y1=80:nb_colors=4:speed=0.00001")
    gold2 = g.add("gradients=s=1280x80:c0=0xa8761c:c1=0xf7d774:c2=0x9a6a18:c3=0xf3d27a:x0=0:y0=0:x1=1280:y1=80:nb_colors=4:speed=0.00001")
    b = g.add("overlay=0:0", f"{bg}][{gold}")
    b = g.add("overlay=0:640", f"{b}][{gold2}")
    por = portrait_fade(g, LIB / "25.jpg", (560, 140), 560, 200, h=560)
    b = g.add("overlay=700:80", f"{b}][{por}")
    b = g.text(b, "KINH ĐỊA TẠNG", ANTON, 118, "white", 60, 120, shadow=4)
    b = g.text(b, "BỒ TÁT BỔN NGUYỆN", ANTON, 84, "white", 62, 262, shadow=4)
    b = g.text(b, "CHỦ GIẢNG", OLD, 30, "0xd9c08a", 64, 392)
    b = g.text(b, "PHÁP SƯ TỊNH KHÔNG", OLD, 34, "0xd9c08a", 64, 428)
    b = g.add("drawbox=x=62:y=500:w=300:h=86:color=0xa31d18:t=fill", b)
    b = g.gold_text(b, f"TẬP {EP}", OLD, 66, "62+(300-text_w)/2", 506, top="0xfff1b8", bottom="0xd9a441", stroke=1)
    g.render(b, OUT / "B-vien-vang.jpg")


def style_c():
    work = OUT / "c"; work.mkdir(exist_ok=True)
    g = G(work)
    paper = g.add("color=c=0xf1e6cf:s=1280x720,format=rgb24,"
                  "geq=r='241-25*((X/1280)^2)':g='230-28*((X/1280)^2)':b='207-30*((X/1280)^2)'")
    art = g.inp(LIB / "102.jpg")
    art = g.add("scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,hue=s=0.2,"
                "colorchannelmixer=aa=0.22,format=rgba,colorchannelmixer=aa=0.22", art)
    b = g.add("overlay=0:0", f"{paper}][{art}")
    # white-background portrait -> key out white, keep a soft edge
    src = g.inp(LIB / "11.jpg")
    por = g.add("crop=560:1000:260:60,scale=-2:700,colorkey=0xffffff:0.12:0.08,format=rgba", src)
    b = g.add("overlay=40:20", f"{b}][{por}")
    b = g.text(b, "Kinh", OLD, 56, "0x5a3412", 600, 70)
    b = g.text(b, "Địa Tạng Bồ Tát", OLD, 92, "0x5a3412", 520, 130, shadow=0)
    b = g.add("drawbox=x=540:y=268:w=660:h=78:color=0x2f4a34:t=fill,drawbox=x=548:y=276:w=644:h=62:color=0xd8b56a:t=2", b)
    b = g.text(b, "Bổn Nguyện Kinh", OLD, 50, "0xf3dfa6", 700, 279)
    b = g.add("drawbox=x=560:y=378:w=620:h=2:color=0xb58a44:t=fill", b)
    b = g.text(b, f"Tập {EP}", OLD, 88, "0x8a1c14", 760, 400)
    b = g.text(b, "Chủ giảng: Lão pháp sư Tịnh Không", OLD, 34, "0x4a3a2a", 610, 530)
    g.render(b, OUT / "C-thuy-mac.jpg")


if __name__ == "__main__":
  for fn in (style_a, style_b, style_c):
      fn()
