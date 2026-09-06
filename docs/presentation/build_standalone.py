import base64
import pathlib
import re

base = pathlib.Path(r"D:\Opencode\1\MagSim\docs\presentation")
html = (base / "magsim_presentation.html").read_text(encoding="utf-8")


def repl(m):
    src = m.group(1)
    p = base / src
    data = p.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    ext = p.suffix.lower().lstrip(".")
    mime = "image/png" if ext == "png" else "image/jpeg"
    return 'src="data:%s;base64,%s"' % (mime, b64)


out = re.sub(r'src="(img/[^"]+)"', repl, html)
(base / "magsim_presentation_standalone.html").write_text(out, encoding="utf-8")
print("standalone written:", len(out) // 1024, "KB")