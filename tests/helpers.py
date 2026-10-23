import io
import zipfile

from PIL import Image


def png(size=(200, 100), color=(200, 30, 30)):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    out.seek(0)
    return out


def read_part(path, name):
    with zipfile.ZipFile(path) as z:
        return z.read(name).decode("utf-8")


def parts(path):
    with zipfile.ZipFile(path) as z:
        return {name: z.read(name) for name in z.namelist()}


def replace_part(path, name, data):
    """Rewrite one part of a zip file, keeping all others."""
    with zipfile.ZipFile(path) as z:
        items = [(info, z.read(info)) for info in z.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for info, content in items:
            z.writestr(info, data if info.filename == name else content)
