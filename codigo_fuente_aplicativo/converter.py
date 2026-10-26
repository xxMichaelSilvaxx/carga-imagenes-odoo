"""Image to WebP conversion, run in a process pool so the GUI stays responsive."""
import io
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, features

from common import SOURCE_EXTENSIONS, Matcher, Progress

FLAT_COLOR_LIMIT = 4096
COLUMNS = ("Referencia", "Archivo original", "Archivo .webp", "Estado", "Detalle")
CONVERTED = "Convertida"
COPIED = "Copiada sin convertir"
EXISTING = "Ya existía"
FAILED = "Error"
CANCELLED = "Cancelada"
NO_IMAGE = "Sin imagen en la carpeta"


@dataclass
class ConvertOptions:
    source: Path
    output: Path
    references: list | None
    suffixes: tuple
    recursive: bool
    size: tuple | None
    fit: str
    quality: int
    overwrite: bool
    workers: int = 0


def webp_available():
    return features.check("webp")


def pad_to(img, width, height):
    """Fit the whole image inside the box and center it over a transparent canvas."""
    fitted = img.copy()
    fitted.thumbnail((width, height), Image.LANCZOS)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.paste(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
    return canvas


def resize(img, width, height, fit):
    if fit == "pad":
        return pad_to(img, width, height)
    if fit == "stretch":
        return img.resize((width, height), Image.LANCZOS)
    if fit == "cover":
        return ImageOps.fit(img, (width, height), Image.LANCZOS)
    img = img.copy()
    img.thumbnail((width, height), Image.LANCZOS)
    return img


def looks_flat(img):
    """Flat graphics (logos, banners) compress far better lossless than lossy."""
    sample = img.resize((256, 256), Image.NEAREST)
    return sample.getcolors(maxcolors=FLAT_COLOR_LIMIT) is not None


def encode(img, quality, lossless):
    buffer = io.BytesIO()
    # exact=True keeps the RGB values hidden under fully transparent pixels
    img.save(buffer, "WEBP", quality=quality, lossless=lossless, method=4, exact=True)
    return buffer.getvalue()


def render(src, size, fit, quality):
    with Image.open(src) as img:
        img = ImageOps.exif_transpose(img)
        original = img.size
        img = img.convert("RGBA" if "A" in img.getbands() or "transparency" in img.info else "RGB")
        if size:
            img = resize(img, *size, fit)
        if not looks_flat(img):
            return encode(img, quality, False), img.size, original
        lossy, lossless = encode(img, quality, False), encode(img, quality, True)
        return min(lossy, lossless, key=len), img.size, original


def convert_job(src, dst, size, fit, quality):
    """Return (status, detail). Runs in a child process."""
    try:
        before = src.stat().st_size
        data, (width, height), original = render(src, size, fit, quality)
        step = quality
        # Already-compressed JPEGs can grow at high quality: step down before giving up
        while len(data) >= before and step - 10 >= 70:
            step -= 10
            data, (width, height), original = render(src, size, fit, step)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if len(data) >= before and (width, height) == original:
            copy = dst.with_suffix(src.suffix.lower())
            copy.write_bytes(src.read_bytes())
            return COPIED, f"El .webp pesaba más que el original; se copió {copy.name}"
        dst.write_bytes(data)
        return CONVERTED, f"{width}x{height}  {before // 1024} KB -> {len(data) // 1024} KB"
    except Exception as error:
        return FAILED, f"No se pudo convertir: {error}"


def collect(folder, recursive):
    pool = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(p for p in pool if p.is_file() and p.suffix.lower() in SOURCE_EXTENSIONS)


def filter_by_references(files, references, matcher):
    wanted = {matcher.exact(ref) for ref in references} | {matcher.base(ref) for ref in references}
    selected = [src for src in files if matcher.exact(src.stem) in wanted or matcher.base(src.stem) in wanted]
    found = {matcher.exact(src.stem) for src in selected} | {matcher.base(src.stem) for src in selected}
    missing = [ref for ref in references if matcher.exact(ref) not in found and matcher.base(ref) not in found]
    return selected, missing


def destination(src, options):
    return options.output / src.parent.relative_to(options.source) / (src.stem + ".webp")


def run_conversion(options, reporter, stop):
    reporter.begin(COLUMNS)
    if not webp_available():
        reporter.error("Esta instalación de Pillow no soporta WebP. Reinstale el aplicativo.")
        return reporter.finished("No se pudo convertir: falta soporte WebP.")

    reporter.status("Buscando imágenes...")
    reporter.info(f"Carpeta de origen: {options.source}")
    files = collect(options.source, options.recursive)
    reporter.info(f"Imágenes encontradas: {len(files):,}")
    missing = []
    if options.references is not None:
        files, missing = filter_by_references(files, options.references, Matcher(options.suffixes))
        reporter.info(f"Referencias del archivo: {len(options.references):,}  |  con imagen: {len(files):,}")
        for reference in missing:
            reporter.row(reference, "", "", NO_IMAGE, "No hay un archivo con esta referencia en la carpeta de origen")
        if missing:
            reporter.warning(f"Referencias sin imagen en la carpeta: {len(missing):,}")

    jobs, targets = [], {}
    for src in files:
        dst = destination(src, options)
        if dst.exists() and not options.overwrite:
            reporter.row(src.stem, src.name, dst.name, EXISTING, "Se omitió; marque 'Rehacer' para volver a convertirla")
            continue
        if dst in targets:
            reporter.warning(f"{src.name} y {targets[dst].name} generan el mismo {dst.name}; se convierte solo el primero")
            continue
        targets[dst] = src
        jobs.append((src, dst))

    if not jobs:
        report = reporter.write_report("conversion", missing)
        return reporter.finished("No hay imágenes nuevas por convertir.", report)

    workers = options.workers or max(1, min((os.cpu_count() or 2) - 1, 8, len(jobs)))
    reporter.info(f"Por convertir: {len(jobs):,}  |  destino: {options.output}  |  procesos: {workers}")
    progress = Progress(len(jobs))
    reporter.progress(progress)
    counts = {CONVERTED: 0, COPIED: 0, FAILED: 0}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(convert_job, src, dst, options.size, options.fit, options.quality): (src, dst)
                   for src, dst in jobs}
        for future in as_completed(futures):
            src, dst = futures[future]
            if future.cancelled():
                continue
            try:
                status, detail = future.result()
            except Exception as error:
                status, detail = FAILED, f"El proceso de conversión se interrumpió: {error}"
            counts[status] += 1
            reporter.row(src.stem, src.name, dst.name if status == CONVERTED else "", status, detail)
            if status == FAILED:
                reporter.error(f"{src.name}: {detail}")
            progress.step()
            reporter.progress(progress, f"{counts[CONVERTED]:,} convertidas")
            if stop.is_set():
                pool.shutdown(wait=True, cancel_futures=True)
                break

    pending = [src.stem for src, dst in jobs if not dst.exists() and not dst.with_suffix(src.suffix.lower()).exists()]
    cancelled = stop.is_set()
    summary = (f"{'Conversión cancelada' if cancelled else 'Conversión terminada'} en {progress.snapshot()['elapsed']}: "
               f"{counts[CONVERTED]:,} convertidas, {counts[COPIED]:,} copiadas sin convertir, "
               f"{counts[FAILED]:,} con error, {len(missing):,} referencias sin imagen.")
    report = reporter.write_report("conversion", missing + pending)
    return reporter.finished(summary, report)
