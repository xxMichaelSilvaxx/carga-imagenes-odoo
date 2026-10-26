"""Match images with product references and upload them through the product.image.upload service."""
import base64
import io
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from common import IMAGE_EXTENSIONS, Matcher, Progress
from odoo_client import OdooError

# Same limit Odoo enforces in odoo.tools.image (IMAGE_MAX_RESOLUTION)
MAX_PIXELS = 50_000_000
COLUMNS = ("Referencia", "Archivo", "Código en Odoo", "Producto", "Estado", "Detalle")
ADDED = "Nueva"
REPLACED = "Actualizada"
WOULD_ADD = "Se agregaría"
WOULD_REPLACE = "Se actualizaría"
KEPT = "Conservada"
NO_PRODUCT = "No existe en Odoo"
NO_IMAGE = "Sin imagen en la carpeta"
SKIPPED = "Omitida"
FAILED = "Error"
CANCELLED = "Cancelada"
PENDING_STATUSES = (FAILED, NO_IMAGE, CANCELLED)


@dataclass
class UploadOptions:
    folder: Path
    references: list | None
    suffixes: tuple
    include_suffixes: bool
    overwrite: bool
    validate_only: bool
    workers: int


@dataclass
class Target:
    reference: str
    code: str
    template_id: int
    name: str
    has_image: bool
    note: str = ""


@dataclass
class Job:
    image: Path
    templates: set = field(default_factory=set)
    targets: list = field(default_factory=list)


def collect_images(folder, matcher, reporter):
    grouped = defaultdict(list)
    for item in folder.iterdir():
        if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS:
            grouped[matcher.exact(item.stem)].append(item)
    images = {}
    for key, paths in grouped.items():
        # WebP first: it is the lightest version of the same picture
        paths.sort(key=lambda p: (p.suffix.lower() != ".webp", p.name.lower()))
        images[key] = paths[0]
        if len(paths) > 1:
            reporter.warning(f"Hay {len(paths)} archivos para '{paths[0].stem}'; se usa {paths[0].name}")
    return images


def read_valid_image(path, max_bytes):
    data = path.read_bytes()
    if not data:
        raise ValueError("El archivo está vacío")
    if len(data) > max_bytes:
        raise ValueError(f"El archivo pesa {len(data) // 1024 // 1024} MB; el máximo es "
                         f"{max_bytes // 1024 // 1024} MB. Conviértalo primero.")
    try:
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            img.verify()
    except Exception as error:
        raise ValueError(f"El archivo no es una imagen válida o está dañado ({error})") from None
    if width * height > MAX_PIXELS:
        raise ValueError(f"La imagen mide {width}x{height}; Odoo no acepta más de 50 megapíxeles. Conviértala primero.")
    return data


class Uploader:
    def __init__(self, client, options, reporter, stop):
        self.client = client
        self.options = options
        self.reporter = reporter
        self.stop = stop
        self.matcher = Matcher(options.suffixes if options.include_suffixes else ())
        self.counts = defaultdict(int)
        self.pending = []
        self.max_bytes = client.info.get("max_image_mb", 20) * 1024 * 1024
        self.chunk = client.info.get("max_products_per_image", 100)

    def row(self, target_or_reference, image, status, detail):
        code = name = ""
        if isinstance(target_or_reference, Target):
            target = target_or_reference
            reference, code, name = target.reference, target.code, target.name
            detail = " ".join(part for part in (detail, target.note) if part)
        else:
            reference = target_or_reference
        self.counts[status] += 1
        if status in PENDING_STATUSES:
            self.pending.append(reference)
        self.reporter.row(reference, image.name if image else "", code, name, status, detail)

    def load_catalog(self):
        rows, page_size = [], self.client.info.get("page_size", 5000)
        while not self.stop.is_set():
            self.reporter.status(f"Leyendo productos de Odoo... {len(rows):,}")
            page = self.client.call("get_catalog", offset=len(rows))
            rows.extend(page)
            if len(page) < page_size:
                break
        return rows

    def plan(self, images, catalog):
        by_code = defaultdict(list)
        by_base = defaultdict(set)
        for code, template_id, name, has_image in catalog:
            key = self.matcher.exact(code)
            entry = (code, template_id, name, has_image)
            # Variants of one template often share the reference; one row per template is enough
            if entry not in by_code[key]:
                by_code[key].append(entry)
            by_base[self.matcher.base(key)].add(key)
        images_by_base = defaultdict(list)
        for key, path in sorted(images.items()):
            images_by_base[self.matcher.base(key)].append(path)

        references = self.options.references
        if references is None:
            references = [path.stem for path in sorted(images.values(), key=lambda p: p.name.lower())]
        jobs, owner, seen = {}, {}, set()
        for reference in references:
            exact, base = self.matcher.exact(reference), self.matcher.base(reference)
            codes = by_base.get(base, set()) if self.options.include_suffixes else {exact} & by_code.keys()
            if not codes:
                image = images.get(exact) or images.get(base)
                self.row(reference, image, NO_PRODUCT, "La referencia interna no existe en Odoo o el producto está archivado")
                continue
            for code in sorted(codes - seen):
                seen.add(code)
                image, note = self.pick_image(code, images, images_by_base)
                for real_code, template_id, name, has_image in by_code[code]:
                    target = Target(reference, real_code, template_id, name, has_image, note)
                    if not image:
                        self.row(target, None, NO_IMAGE, "No hay un archivo con esta referencia en la carpeta")
                    elif owner.get(template_id, image) != image:
                        self.row(target, image, SKIPPED, f"El producto ya recibe {owner[template_id].name} desde otra variante")
                    elif has_image and not self.options.overwrite:
                        self.row(target, image, KEPT, "Ya tenía imagen; no se marcó 'Actualizar las imágenes que ya existen'")
                    else:
                        owner[template_id] = image
                        job = jobs.setdefault(image, Job(image))
                        job.templates.add(template_id)
                        job.targets.append(target)
        return list(jobs.values())

    def pick_image(self, code, images, images_by_base):
        if code in images:
            return images[code], ""
        if not self.options.include_suffixes:
            return None, ""
        base = self.matcher.base(code)
        if base in images:
            return images[base], f"(usa la imagen de la referencia base {images[base].stem})"
        siblings = images_by_base.get(base)
        if siblings:
            return siblings[0], f"(usa la imagen de {siblings[0].stem})"
        return None, ""

    def upload(self, job):
        """Return {template_id: (status, detail)}."""
        if self.stop.is_set():
            return {tid: (CANCELLED, "Proceso cancelado por el usuario") for tid in job.templates}
        try:
            data = read_valid_image(job.image, self.max_bytes)
            image = base64.b64encode(data).decode("ascii")
            size = f"{len(data) // 1024} KB"
            results = {}
            template_ids = sorted(job.templates)
            for start in range(0, len(template_ids), self.chunk):
                answer = self.client.call("set_image", template_ids=template_ids[start:start + self.chunk], image=image)
                results.update({tid: (REPLACED, f"{size}, reemplazó la imagen anterior") for tid in answer["replaced"]})
                results.update({tid: (ADDED, size) for tid in answer["added"]})
            return results
        except (ValueError, OSError, OdooError) as error:
            return {tid: (FAILED, str(error)) for tid in job.templates}
        except Exception as error:
            return {tid: (FAILED, f"Error inesperado: {error}") for tid in job.templates}

    def run(self):
        options, reporter = self.options, self.reporter
        reporter.status("Buscando imágenes en la carpeta...")
        images = collect_images(options.folder, self.matcher, reporter)
        reporter.info(f"Imágenes en la carpeta: {len(images):,}")
        if options.references is not None:
            reporter.info(f"Referencias del archivo: {len(options.references):,}")
        if not images:
            return reporter.finished(f"No hay imágenes ({', '.join(IMAGE_EXTENSIONS)}) en {options.folder}")

        catalog = self.load_catalog()
        if self.stop.is_set():
            return reporter.finished("Carga cancelada antes de empezar a subir.")
        reporter.info(f"Productos con referencia interna en Odoo: {len(catalog):,}")
        jobs = self.plan(images, catalog)
        total_products = sum(len(job.targets) for job in jobs)
        reporter.info(f"Imágenes por subir: {len(jobs):,} (para {total_products:,} productos)")

        if options.validate_only:
            for job in jobs:
                for target in job.targets:
                    self.row(target, job.image, WOULD_REPLACE if target.has_image else WOULD_ADD, "")
            return self.close("Validación terminada (no se modificó nada en Odoo)")

        progress = Progress(len(jobs))
        reporter.progress(progress)
        with ThreadPoolExecutor(max_workers=options.workers) as pool:
            futures = {pool.submit(self.upload, job): job for job in jobs}
            for future in as_completed(futures):
                job = futures[future]
                results = future.result()
                for target in job.targets:
                    status, detail = results.get(target.template_id, (FAILED, "Sin respuesta del servidor"))
                    self.row(target, job.image, status, detail)
                failed = {detail for status, detail in results.values() if status == FAILED}
                for detail in failed:
                    reporter.error(f"{job.image.name}: {detail}")
                progress.step()
                reporter.progress(progress, f"{self.counts[ADDED] + self.counts[REPLACED]:,} productos con imagen")
        title = "Carga cancelada" if self.stop.is_set() else "Carga terminada"
        return self.close(f"{title} en {progress.snapshot()['elapsed']}")

    def close(self, title):
        counts = self.counts
        parts = [f"{counts[status]:,} {status.lower()}" for status in
                 (ADDED, REPLACED, WOULD_ADD, WOULD_REPLACE, KEPT, NO_PRODUCT, NO_IMAGE, SKIPPED, FAILED, CANCELLED)
                 if counts[status]]
        summary = f"{title}: " + (", ".join(parts) if parts else "sin resultados") + "."
        report = self.reporter.write_report("subida", sorted(set(self.pending)))
        return self.reporter.finished(summary, report)


def run_upload(client, options, reporter, stop):
    reporter.begin(COLUMNS)
    reporter.status("Conectando con Odoo...")
    try:
        reporter.info(f"Conectado: {client.connect()}")
        for note in client.warnings():
            reporter.warning(note)
        return Uploader(client, options, reporter, stop).run()
    except OdooError as error:
        reporter.error(str(error))
        return reporter.finished(f"El proceso se detuvo: {error}")
