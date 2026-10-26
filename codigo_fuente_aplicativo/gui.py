"""Tkinter interface: forms on the left, progress, summary tiles, results and log on the right."""
import json
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import sv_ttk

from common import (APP_NAME, DEFAULT_SUFFIXES, STATUS_KIND, Reporter, data_dir, parse_suffixes, read_references,
                    set_window_icon, setup_logger)
from converter import ConvertOptions, run_conversion, webp_available
from odoo_client import API_KEY_HELP, OdooClient, OdooError, is_local, normalize_url
from uploader import UploadOptions, run_upload

NAVY = "#162031"
NAVY_LIGHT = "#223047"
ACCENT = "#8fb7c5"
TEXT = "#1f2937"
MUTED = "#5b6472"
KIND_COLORS = {
    "ok": ("#e7f6ec", "#166534"),
    "error": ("#fde8e8", "#991b1b"),
    "warn": ("#fff4e0", "#92400e"),
    "": ("#eef2f7", NAVY_LIGHT),
}
SIZE_CHOICES = {
    "Máximo 1920 px sin deformar (recomendado)": ((1920, 1920), "contain"),
    "Cuadrado 1024 x 1024 con fondo transparente": ((1024, 1024), "pad"),
    "Mantener el tamaño original": (None, "contain"),
    "Personalizado": ("custom", None),
}
FIT_CHOICES = {
    "Rellenar con fondo transparente": "pad",
    "Ajustar dentro de la medida": "contain",
    "Recortar para llenar": "cover",
    "Estirar (puede deformar)": "stretch",
}
LOG_COLORS = {"info": TEXT, "success": "#15803d", "warning": "#b45309", "error": "#b91c1c"}
COLUMN_WIDTHS = {"Referencia": 150, "Archivo": 190, "Archivo original": 190, "Archivo .webp": 190,
                 "Código en Odoo": 150, "Producto": 260, "Estado": 130, "Detalle": 360}
TILES_PER_ROW = 4
EVENTS_PER_TICK = 400


class ScrollFrame(ttk.Frame):
    """Vertical scrolling container so the forms fit on small screens."""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas, padding=(14, 12))
        window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.body.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(window, width=event.width))
        self.bind("<Enter>", lambda _: self.bind_all("<MouseWheel>", self.on_wheel))
        self.bind("<Leave>", lambda _: self.unbind_all("<MouseWheel>"))

    def on_wheel(self, event):
        if self.body.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-event.delta / 120), "units")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        set_window_icon(self)
        self.geometry("1280x860")
        self.minsize(1100, 700)
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        self.logger = setup_logger()
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.worker = None
        self.closing = False
        self.rows = []
        self.tiles = {}
        self.report_path = ""
        self.settings_file = data_dir() / "config.json"
        self.settings = self.load_settings()
        sv_ttk.set_theme("light")
        self.configure(background="#fafafa")
        self.build_style()
        self.build_vars()
        self.build_header()
        self.build_body()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self.poll_events)
        if not webp_available():
            self.log("error", "Esta instalación no soporta WebP: la conversión no funcionará.")

    def load_settings(self):
        try:
            return json.loads(self.settings_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_settings(self):
        keys = ("conv_source", "conv_output", "conv_ref_mode", "conv_ref_file", "size_choice", "fit_choice",
                "url", "database", "login", "up_folder", "up_ref_mode", "up_ref_file", "suffixes")
        data = {key: getattr(self, key).get() for key in keys}
        for key in ("quality", "workers", "width", "height", "use_suffixes", "recursive", "overwrite"):
            try:
                data[key] = getattr(self, key).get()
            except tk.TclError:
                pass
        try:
            self.settings_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def build_style(self):
        style = ttk.Style(self)
        style.configure("Card.TLabelframe.Label", font=("Segoe UI Semibold", 11), foreground=NAVY_LIGHT)
        style.configure("Hint.TLabel", foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Field.TLabel", font=("Segoe UI Semibold", 10))
        style.configure("Status.TLabel", font=("Segoe UI Semibold", 11), foreground=NAVY_LIGHT)
        style.configure("Percent.TLabel", font=("Segoe UI Semibold", 26), foreground=NAVY_LIGHT)
        style.configure("Treeview", rowheight=26)

    def build_vars(self):
        s = self.settings
        string = lambda key, default="": tk.StringVar(self, s.get(key, default))
        self.conv_source = string("conv_source")
        self.conv_output = string("conv_output")
        self.conv_ref_mode = string("conv_ref_mode", "all")
        self.conv_ref_file = string("conv_ref_file")
        self.size_choice = string("size_choice", next(iter(SIZE_CHOICES)))
        if self.size_choice.get() not in SIZE_CHOICES:
            self.size_choice.set(next(iter(SIZE_CHOICES)))
        self.fit_choice = string("fit_choice", next(iter(FIT_CHOICES)))
        self.width = tk.IntVar(self, s.get("width", 1024))
        self.height = tk.IntVar(self, s.get("height", 1024))
        self.quality = tk.IntVar(self, s.get("quality", 90))
        self.recursive = tk.BooleanVar(self, s.get("recursive", False))
        self.conv_overwrite = tk.BooleanVar(self, False)
        self.url = string("url")
        self.database = string("database")
        self.login = string("login")
        self.api_key = tk.StringVar(self)
        self.show_key = tk.BooleanVar(self, False)
        self.up_folder = string("up_folder")
        self.up_ref_mode = string("up_ref_mode", "all")
        self.up_ref_file = string("up_ref_file")
        self.use_suffixes = tk.BooleanVar(self, s.get("use_suffixes", True))
        self.suffixes = string("suffixes", DEFAULT_SUFFIXES)
        self.overwrite = tk.BooleanVar(self, s.get("overwrite", True))
        self.workers = tk.IntVar(self, s.get("workers", 4))
        self.connection_text = tk.StringVar(self, "Sin probar.")
        self.status_text = tk.StringVar(self, "Listo para empezar.")
        self.percent_text = tk.StringVar(self, "0 %")
        self.count_text = tk.StringVar(self, "")
        self.time_text = tk.StringVar(self, "")
        self.filter_text = tk.StringVar(self, "Todos")

    def build_header(self):
        header = tk.Frame(self, bg=NAVY, padx=22, pady=14)
        header.pack(fill="x")
        left = tk.Frame(header, bg=NAVY)
        left.pack(side="left")
        tk.Label(left, text=APP_NAME, bg=NAVY, fg="white", font=("Segoe UI Semibold", 18)).pack(anchor="w")
        tk.Label(left, text="1. Convierta las fotos a WebP   •   2. Súbalas a los productos de Odoo por referencia interna",
                 bg=NAVY, fg=ACCENT, font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 0))
        badge = tk.Label(header, text="Conexión segura: solo HTTPS y clave API", bg=NAVY_LIGHT, fg="white",
                         font=("Segoe UI", 9), padx=12, pady=6)
        badge.pack(side="right")

    def build_body(self):
        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=12, pady=12)
        self.tabs = ttk.Notebook(body)
        self.tabs.add(self.build_convert_tab(self.tabs), text="  1. Convertir imágenes  ")
        self.tabs.add(self.build_upload_tab(self.tabs), text="  2. Subir a Odoo  ")
        if self.settings.get("url"):
            self.tabs.select(1)
        body.add(self.tabs, weight=2)
        body.add(self.build_monitor(body), weight=3)

    def card(self, parent, title):
        frame = ttk.LabelFrame(parent, text=f" {title} ", style="Card.TLabelframe", padding=(12, 8, 12, 12))
        frame.pack(fill="x", pady=(0, 12))
        frame.columnconfigure(0, weight=1)
        return frame

    def path_field(self, parent, label, var, kind):
        ttk.Label(parent, text=label, style="Field.TLabel").pack(anchor="w", pady=(6, 2))
        row = ttk.Frame(parent)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Examinar...", command=lambda: self.browse(var, kind)).pack(side="left", padx=(8, 0))
        return row

    def text_field(self, parent, label, var, hint="", **entry_options):
        ttk.Label(parent, text=label, style="Field.TLabel").pack(anchor="w", pady=(6, 2))
        entry = ttk.Entry(parent, textvariable=var, **entry_options)
        entry.pack(fill="x")
        if hint:
            ttk.Label(parent, text=hint, style="Hint.TLabel").pack(anchor="w", pady=(2, 0))
        return entry

    def browse(self, var, kind):
        current = var.get().strip()
        start = current if Path(current).is_dir() else str(Path(current).parent) if current else str(Path.home())
        if kind == "dir":
            chosen = filedialog.askdirectory(parent=self, initialdir=start, title="Seleccione la carpeta")
        else:
            chosen = filedialog.askopenfilename(parent=self, initialdir=start, title="Seleccione el archivo de referencias",
                                                filetypes=[("Texto", "*.txt *.csv"), ("Todos", "*.*")])
        if chosen:
            var.set(str(Path(chosen)))

    def references_card(self, parent, mode_var, file_var):
        frame = self.card(parent, "¿Qué referencias procesar?")
        ttk.Radiobutton(frame, text="Todas las imágenes de la carpeta", value="all", variable=mode_var).pack(anchor="w")
        ttk.Radiobutton(frame, text="Solo las referencias de un archivo .txt (una por línea)", value="file",
                        variable=mode_var).pack(anchor="w", pady=(4, 0))
        self.path_field(frame, "Archivo de referencias", file_var, "file")
        info = ttk.Label(frame, style="Hint.TLabel")
        info.pack(anchor="w", pady=(4, 0))
        update = lambda *_: info.configure(text=self.references_hint(mode_var, file_var))
        mode_var.trace_add("write", update)
        file_var.trace_add("write", update)
        update()
        ttk.Separator(frame).pack(fill="x", pady=10)
        ttk.Checkbutton(frame, text="Tratar como la misma referencia las que terminan en:",
                        variable=self.use_suffixes).pack(anchor="w")
        ttk.Entry(frame, textvariable=self.suffixes).pack(fill="x", pady=(4, 0))
        ttk.Label(frame, text="Separe con comas. Ej.: ref_0244 = ref_0244_PROMOCIONALES", style="Hint.TLabel").pack(anchor="w")

    def references_hint(self, mode_var, file_var):
        if mode_var.get() != "file":
            return "Se procesan todas las imágenes encontradas."
        path = Path(file_var.get().strip())
        if not path.is_file():
            return "Seleccione el archivo con las referencias internas."
        return f"{len(read_references(path)):,} referencias en el archivo."

    def build_convert_tab(self, parent):
        scroll = ScrollFrame(parent)
        tab = scroll.body
        folders = self.card(tab, "Carpetas")
        self.path_field(folders, "Carpeta con las imágenes originales", self.conv_source, "dir")
        self.path_field(folders, "Carpeta donde guardar los .webp", self.conv_output, "dir")
        ttk.Checkbutton(folders, text="Incluir subcarpetas", variable=self.recursive).pack(anchor="w", pady=(8, 0))
        self.references_card(tab, self.conv_ref_mode, self.conv_ref_file)

        options = self.card(tab, "Tamaño y calidad")
        ttk.Label(options, text="Tamaño", style="Field.TLabel").pack(anchor="w", pady=(0, 2))
        ttk.Combobox(options, textvariable=self.size_choice, values=list(SIZE_CHOICES), state="readonly").pack(fill="x")
        custom = ttk.Frame(options)
        ttk.Label(custom, text="Ancho").pack(side="left")
        ttk.Spinbox(custom, from_=16, to=4096, textvariable=self.width, width=6).pack(side="left", padx=(4, 12))
        ttk.Label(custom, text="Alto").pack(side="left")
        ttk.Spinbox(custom, from_=16, to=4096, textvariable=self.height, width=6).pack(side="left", padx=(4, 12))
        ttk.Combobox(custom, textvariable=self.fit_choice, values=list(FIT_CHOICES), state="readonly",
                     width=30).pack(side="left", fill="x", expand=True)
        quality = ttk.Frame(options)
        quality.pack(fill="x", pady=(10, 0))
        ttk.Label(quality, text="Calidad (1-100)", style="Field.TLabel").pack(side="left")
        ttk.Spinbox(quality, from_=1, to=100, textvariable=self.quality, width=6).pack(side="left", padx=8)
        toggle = lambda *_: (custom.pack(fill="x", pady=(8, 0), before=quality)
                             if self.size_choice.get() == "Personalizado" else custom.pack_forget())
        self.size_choice.trace_add("write", toggle)
        toggle()
        ttk.Checkbutton(options, text="Rehacer los .webp que ya existen en la carpeta de destino",
                        variable=self.conv_overwrite).pack(anchor="w", pady=(10, 0))

        self.convert_button = ttk.Button(tab, text="Convertir imágenes", style="Accent.TButton",
                                         command=self.start_conversion)
        self.convert_button.pack(anchor="e", ipadx=10, ipady=2)
        return scroll

    def build_upload_tab(self, parent):
        scroll = ScrollFrame(parent)
        tab = scroll.body
        conn = self.card(tab, "Conexión segura con Odoo")
        self.text_field(conn, "URL de Odoo", self.url, "Ej.: https://miempresa.odoo.com (solo https)")
        self.text_field(conn, "Base de datos (opcional)", self.database,
                        "Déjela vacía si el servidor tiene una sola base, como en Odoo.sh.")
        self.text_field(conn, "Usuario (correo)", self.login, "Se verifica que la clave API pertenezca a este usuario.")
        ttk.Label(conn, text="Clave API", style="Field.TLabel").pack(anchor="w", pady=(6, 2))
        key_row = ttk.Frame(conn)
        key_row.pack(fill="x")
        self.key_entry = ttk.Entry(key_row, textvariable=self.api_key, show="•")
        self.key_entry.pack(side="left", fill="x", expand=True)
        ttk.Checkbutton(key_row, text="Mostrar", variable=self.show_key,
                        command=lambda: self.key_entry.configure(show="" if self.show_key.get() else "•")).pack(side="left", padx=8)
        ttk.Button(key_row, text="¿Cómo obtenerla?", command=self.show_api_key_help).pack(side="left")
        ttk.Label(conn, text="La clave no se guarda en el equipo. Use un usuario dedicado, nunca uno administrador.",
                  style="Hint.TLabel").pack(anchor="w", pady=(2, 0))
        test_row = ttk.Frame(conn)
        test_row.pack(fill="x", pady=(10, 0))
        self.test_button = ttk.Button(test_row, text="Probar conexión", command=self.test_connection)
        self.test_button.pack(side="left")
        self.connection_label = ttk.Label(test_row, textvariable=self.connection_text, style="Hint.TLabel",
                                          wraplength=420, justify="left")
        self.connection_label.pack(side="left", padx=10, fill="x", expand=True)

        images = self.card(tab, "Imágenes")
        self.path_field(images, "Carpeta con las imágenes a subir", self.up_folder, "dir")
        ttk.Button(images, text="Usar la carpeta de .webp del paso 1",
                   command=lambda: self.up_folder.set(self.conv_output.get())).pack(anchor="w", pady=(8, 0))
        self.references_card(tab, self.up_ref_mode, self.up_ref_file)

        options = self.card(tab, "Opciones de carga")
        ttk.Checkbutton(options, text="Actualizar las imágenes que ya existen en Odoo",
                        variable=self.overwrite).pack(anchor="w")
        ttk.Label(options, text="Si la desmarca, los productos que ya tienen imagen la conservan.",
                  style="Hint.TLabel").pack(anchor="w")
        workers = ttk.Frame(options)
        workers.pack(fill="x", pady=(10, 0))
        ttk.Label(workers, text="Subidas simultáneas", style="Field.TLabel").pack(side="left")
        ttk.Spinbox(workers, from_=1, to=8, textvariable=self.workers, width=4).pack(side="left", padx=8)
        ttk.Label(workers, text="4 es adecuado para Odoo.sh", style="Hint.TLabel").pack(side="left")

        buttons = ttk.Frame(tab)
        buttons.pack(fill="x")
        self.upload_button = ttk.Button(buttons, text="Subir imágenes", style="Accent.TButton",
                                        command=lambda: self.start_upload(False))
        self.upload_button.pack(side="right", ipadx=10, ipady=2)
        self.validate_button = ttk.Button(buttons, text="Validar sin subir", command=lambda: self.start_upload(True))
        self.validate_button.pack(side="right", padx=8, ipady=2)
        return scroll

    def build_monitor(self, parent):
        frame = ttk.Frame(parent, padding=(12, 0, 0, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)

        progress = ttk.LabelFrame(frame, text=" Progreso ", style="Card.TLabelframe", padding=(14, 8, 14, 12))
        progress.grid(row=0, column=0, sticky="ew")
        progress.columnconfigure(1, weight=1)
        ttk.Label(progress, textvariable=self.percent_text, style="Percent.TLabel", width=7).grid(
            row=0, column=0, rowspan=2, sticky="w")
        ttk.Label(progress, textvariable=self.status_text, style="Status.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(progress, textvariable=self.count_text, style="Hint.TLabel").grid(row=1, column=1, sticky="w")
        self.cancel_button = ttk.Button(progress, text="Cancelar", command=self.cancel, state="disabled")
        self.cancel_button.grid(row=0, column=2, rowspan=2, sticky="e")
        self.progress = ttk.Progressbar(progress, maximum=100)
        self.progress.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 6))
        ttk.Label(progress, textvariable=self.time_text, style="Hint.TLabel").grid(row=3, column=0, columnspan=3, sticky="w")

        summary = ttk.LabelFrame(frame, text=" Resumen (clic para filtrar) ", style="Card.TLabelframe", padding=10)
        summary.grid(row=1, column=0, sticky="ew", pady=12)
        self.tiles_frame = ttk.Frame(summary)
        self.tiles_frame.pack(fill="x")
        for column in range(TILES_PER_ROW):
            self.tiles_frame.columnconfigure(column, weight=1, uniform="tile")
        self.tiles_empty = ttk.Label(self.tiles_frame, text="Aquí verá cuántas imágenes quedaron en cada estado.",
                                     style="Hint.TLabel")
        self.tiles_empty.grid(row=0, column=0, columnspan=TILES_PER_ROW, sticky="w")

        self.monitor = ttk.Notebook(frame)
        self.monitor.grid(row=2, column=0, sticky="nsew")
        self.monitor.add(self.build_results(self.monitor), text="  Resultados  ")
        self.monitor.add(self.build_log(self.monitor), text="  Registro  ")
        return frame

    def build_log(self, parent):
        frame = ttk.Frame(parent, padding=6)
        self.log_text = tk.Text(frame, wrap="word", font=("Consolas", 9), state="disabled", relief="flat",
                                background="#f8fafc", foreground=TEXT, padx=8, pady=6)
        scroll = ttk.Scrollbar(frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for level, color in LOG_COLORS.items():
            self.log_text.tag_configure(level, foreground=color)
        return frame

    def build_results(self, parent):
        frame = ttk.Frame(parent, padding=6)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        bar = ttk.Frame(frame)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(bar, text="Mostrar:").pack(side="left")
        self.filter_box = ttk.Combobox(bar, textvariable=self.filter_text, values=["Todos"], state="readonly", width=24)
        self.filter_box.pack(side="left", padx=6)
        self.filter_box.bind("<<ComboboxSelected>>", lambda _: self.refresh_tree())
        ttk.Button(bar, text="Carpeta de reportes", command=lambda: os.startfile(data_dir("reportes"))).pack(side="right")
        self.report_button = ttk.Button(bar, text="Abrir reporte en Excel", command=self.open_report, state="disabled")
        self.report_button.pack(side="right", padx=6)
        self.tree = ttk.Treeview(frame, show="headings")
        yscroll = ttk.Scrollbar(frame, command=self.tree.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        yscroll.grid(row=1, column=1, sticky="ns")
        xscroll.grid(row=2, column=0, sticky="ew")
        for kind, (background, _) in KIND_COLORS.items():
            if kind:
                self.tree.tag_configure(kind, background=background)
        return frame

    def show_api_key_help(self):
        messagebox.showinfo(
            APP_NAME,
            "Cómo obtener la clave API:\n\n"
            "1. Entre a Odoo con el usuario de carga de imágenes.\n"
            "2. Haga clic en su nombre (arriba a la derecha) > Mi perfil.\n"
            "3. Abra la pestaña Seguridad de la cuenta.\n"
            "4. Haga clic en Nueva clave API, escriba una descripción y elija la duración.\n"
            "5. Copie la clave (solo se muestra una vez) y péguela en este aplicativo.\n\n"
            "Use un usuario dedicado que solo tenga el permiso Productos: Crear, nunca un administrador. "
            "Si la clave se pierde o se expone, elimínela en la misma pantalla y genere otra.",
            parent=self,
        )

    def log(self, level, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{datetime.now():%H:%M:%S}  {text}\n", level)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def set_running(self, running):
        state = "disabled" if running else "normal"
        for button in (self.convert_button, self.upload_button, self.validate_button, self.test_button):
            button.configure(state=state)
        self.cancel_button.configure(state="normal" if running else "disabled")

    def run_worker(self, title, target, *args):
        self.save_settings()
        self.stop.clear()
        self.report_path = ""
        self.report_button.configure(state="disabled")
        self.set_running(True)
        self.status_text.set(title)
        self.percent_text.set("0 %")
        self.count_text.set("")
        self.time_text.set("")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        reporter = Reporter(self.events, self.logger)

        def work():
            try:
                target(*args, reporter, self.stop)
            except Exception as error:
                self.logger.exception("Error inesperado")
                reporter.error(f"Error inesperado: {error}")
                reporter.finished(f"El proceso se detuvo por un error inesperado: {error}")

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def validate_folder(self, var, label):
        path = Path(var.get().strip())
        if not var.get().strip() or not path.is_dir():
            messagebox.showerror(APP_NAME, f"{label}: la carpeta no existe.\n\n{var.get()}", parent=self)
            return None
        return path

    def selected_references(self, mode_var, file_var):
        if mode_var.get() != "file":
            return None
        path = Path(file_var.get().strip())
        if not path.is_file():
            messagebox.showerror(APP_NAME, "Seleccione el archivo .txt con las referencias internas.", parent=self)
            return False
        references = read_references(path)
        if not references:
            messagebox.showerror(APP_NAME, f"El archivo de referencias está vacío:\n\n{path}", parent=self)
            return False
        return references

    def int_value(self, var, label, low, high):
        try:
            value = int(var.get())
        except (tk.TclError, ValueError):
            value = None
        if value is None or not low <= value <= high:
            messagebox.showerror(APP_NAME, f"{label} debe ser un número entre {low} y {high}.", parent=self)
            return None
        return value

    def start_conversion(self):
        if not webp_available():
            return messagebox.showerror(APP_NAME, "Esta instalación no soporta WebP.", parent=self)
        source = self.validate_folder(self.conv_source, "Carpeta de originales")
        if not source:
            return
        output_text = self.conv_output.get().strip()
        if not output_text:
            return messagebox.showerror(APP_NAME, "Indique la carpeta donde guardar los .webp.", parent=self)
        output = Path(output_text)
        try:
            output.mkdir(parents=True, exist_ok=True)
            probe = output / ".prueba_escritura"
            probe.write_text("ok")
            probe.unlink()
        except OSError as error:
            return messagebox.showerror(APP_NAME, f"No se puede escribir en la carpeta de destino:\n\n{error}", parent=self)
        references = self.selected_references(self.conv_ref_mode, self.conv_ref_file)
        quality = self.int_value(self.quality, "La calidad", 1, 100)
        if references is False or quality is None:
            return
        size, fit = SIZE_CHOICES[self.size_choice.get()]
        if size == "custom":
            width = self.int_value(self.width, "El ancho", 16, 4096)
            if width is None:
                return
            height = self.int_value(self.height, "El alto", 16, 4096)
            if height is None:
                return
            size, fit = (width, height), FIT_CHOICES[self.fit_choice.get()]
        options = ConvertOptions(
            source=source, output=output, references=references,
            suffixes=parse_suffixes(self.suffixes.get()) if self.use_suffixes.get() else (),
            recursive=self.recursive.get(), size=size, fit=fit, quality=quality,
            overwrite=self.conv_overwrite.get(),
        )
        self.run_worker("Convirtiendo imágenes...", run_conversion, options)

    def build_client(self):
        try:
            url = normalize_url(self.url.get())
        except OdooError as error:
            messagebox.showerror(APP_NAME, str(error), parent=self)
            return None
        if url.startswith("http://") and not is_local(url):
            messagebox.showerror(APP_NAME, "Por seguridad solo se permiten direcciones https://.\n\n"
                                           "Odoo.sh siempre usa https://", parent=self)
            return None
        if not self.api_key.get().strip():
            messagebox.showerror(APP_NAME, "Ingrese la clave API.\n\n" + API_KEY_HELP, parent=self)
            return None
        self.url.set(url)
        return OdooClient(url, self.database.get(), self.login.get(), self.api_key.get())

    def test_connection(self):
        client = self.build_client()
        if not client:
            return
        self.connection_text.set("Conectando...")
        self.connection_label.configure(foreground=MUTED)

        def work():
            try:
                self.events.put(("connection", True, client.connect(), client.url, client.warnings()))
            except OdooError as error:
                self.events.put(("connection", False, str(error), "", []))
            except Exception as error:
                self.logger.exception("Error al probar la conexión")
                self.events.put(("connection", False, f"Error inesperado: {error}", "", []))

        threading.Thread(target=work, daemon=True).start()

    def start_upload(self, validate_only):
        client = self.build_client()
        if not client:
            return
        folder = self.validate_folder(self.up_folder, "Carpeta de imágenes")
        if not folder:
            return
        references = self.selected_references(self.up_ref_mode, self.up_ref_file)
        workers = self.int_value(self.workers, "Las subidas simultáneas", 1, 8)
        if references is False or workers is None:
            return
        if not validate_only and not messagebox.askyesno(
            APP_NAME,
            f"Se subirán las imágenes de:\n{folder}\n\nA: {client.url}\n"
            f"Referencias: {'todas las de la carpeta' if references is None else f'{len(references):,} del archivo'}\n"
            f"Actualizar imágenes que ya existen: {'SÍ' if self.overwrite.get() else 'no'}\n\n¿Continuar?",
            parent=self,
        ):
            return
        options = UploadOptions(
            folder=folder, references=references,
            suffixes=parse_suffixes(self.suffixes.get()), include_suffixes=self.use_suffixes.get(),
            overwrite=self.overwrite.get(), validate_only=validate_only, workers=workers,
        )
        self.run_worker("Validando contra Odoo..." if validate_only else "Subiendo imágenes a Odoo...", run_upload, client, options)

    def cancel(self):
        if not (self.worker and self.worker.is_alive()):
            return
        if not self.closing and not messagebox.askyesno(
                APP_NAME, "¿Desea cancelar el proceso?\n\nLo que ya se procesó se conserva; el resto queda como "
                          "'Cancelada' en el archivo de pendientes.", icon="warning", default="no", parent=self):
            return
        self.stop.set()
        self.cancel_button.configure(state="disabled")
        self.status_text.set("Cancelando... se termina lo que está en curso.")

    def poll_events(self):
        for _ in range(EVENTS_PER_TICK):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            getattr(self, "on_" + event[0])(*event[1:])
        if self.closing and not (self.worker and self.worker.is_alive()):
            self.destroy()
            return
        self.after(100, self.poll_events)

    def on_begin(self, columns):
        self.rows = []
        self.tree.delete(*self.tree.get_children())
        self.tree.configure(columns=columns)
        for column in columns:
            self.tree.heading(column, text=column, anchor="w")
            self.tree.column(column, width=COLUMN_WIDTHS.get(column, 160), minwidth=80, stretch=column == "Detalle")
        self.filter_text.set("Todos")
        self.filter_box.configure(values=["Todos"])
        for tile in self.tiles.values():
            tile["frame"].destroy()
        self.tiles = {}
        self.tiles_empty.grid()

    def on_log(self, level, text):
        self.log(level, text)

    def on_status(self, text):
        self.status_text.set(text)

    def on_progress(self, snapshot, extra):
        if str(self.progress.cget("mode")) != "determinate":
            self.progress.stop()
            self.progress.configure(mode="determinate")
        self.progress["value"] = snapshot["percent"]
        self.percent_text.set(f"{snapshot['percent']:.0f} %")
        self.status_text.set(extra or "Procesando...")
        self.count_text.set(f"{snapshot['done']:,} de {snapshot['total']:,} imágenes   •   {snapshot['rate']:.1f} imágenes/s")
        self.time_text.set(f"Transcurrido: {snapshot['elapsed']}      Tiempo restante estimado: {snapshot['eta']}")

    def tile(self, status):
        if status in self.tiles:
            return self.tiles[status]
        self.tiles_empty.grid_remove()
        background, foreground = KIND_COLORS[STATUS_KIND.get(status, "")]
        index = len(self.tiles)
        frame = tk.Frame(self.tiles_frame, bg=background, padx=12, pady=8, cursor="hand2")
        frame.grid(row=index // TILES_PER_ROW, column=index % TILES_PER_ROW, sticky="ew", padx=4, pady=4)
        number = tk.Label(frame, text="0", bg=background, fg=foreground, font=("Segoe UI Semibold", 18), cursor="hand2")
        number.pack(anchor="w")
        label = tk.Label(frame, text=status, bg=background, fg=foreground, font=("Segoe UI", 9), cursor="hand2")
        label.pack(anchor="w")
        for widget in (frame, number, label):
            widget.bind("<Button-1>", lambda _, value=status: self.apply_filter(value))
        self.tiles[status] = {"frame": frame, "number": number, "count": 0}
        return self.tiles[status]

    def apply_filter(self, status):
        self.filter_text.set(status if self.filter_text.get() != status else "Todos")
        self.monitor.select(0)
        self.refresh_tree()

    def on_row(self, values):
        self.rows.append(values)
        status = values[self.status_index()]
        tile = self.tile(status)
        tile["count"] += 1
        tile["number"].configure(text=f"{tile['count']:,}")
        known = list(self.filter_box.cget("values"))
        if status not in known:
            self.filter_box.configure(values=known + [status])
        if self.filter_text.get() in ("Todos", status):
            self.tree.insert("", "end", values=values, tags=(STATUS_KIND.get(status, ""),))

    def status_index(self):
        return list(self.tree.cget("columns")).index("Estado")

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        wanted, index = self.filter_text.get(), self.status_index()
        for values in self.rows:
            if wanted in ("Todos", values[index]):
                self.tree.insert("", "end", values=values, tags=(STATUS_KIND.get(values[index], ""),))

    def on_done(self, summary, report):
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress["value"] = 100 if not self.stop.is_set() else self.progress["value"]
        self.set_running(False)
        self.status_text.set("Proceso cancelado." if self.stop.is_set() else "Proceso terminado.")
        self.log("success", summary)
        self.report_path = report
        self.report_button.configure(state="normal" if report else "disabled")
        self.monitor.select(0 if self.rows else 1)
        if not self.closing:
            messagebox.showinfo(APP_NAME, summary + (f"\n\nReporte: {report}" if report else ""), parent=self)

    def on_connection(self, ok, text, url, warnings):
        self.connection_text.set(("Conexión correcta: " if ok else "No se pudo conectar: ") + text)
        self.connection_label.configure(foreground="#15803d" if ok else "#b91c1c")
        self.log("success" if ok else "error", self.connection_text.get())
        for note in warnings:
            self.log("warning", note)
        if warnings:
            self.connection_text.set(self.connection_text.get() + "\n\nAtención: " + "\n".join(warnings))
            self.connection_label.configure(foreground="#b45309")
            messagebox.showwarning(APP_NAME, "\n\n".join(warnings), parent=self)
        if ok:
            self.url.set(url)
            self.save_settings()

    def open_report(self):
        if self.report_path and Path(self.report_path).is_file():
            os.startfile(self.report_path)

    def on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_NAME, "Hay un proceso en curso. ¿Desea cancelarlo y salir?", parent=self):
                return
            self.closing = True
            self.cancel()
            return
        self.save_settings()
        self.api_key.set("")
        self.destroy()


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        # Own taskbar identity so Windows shows the app icon instead of the python.exe one
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Nodosys.CargaImagenesOdoo")
    except (AttributeError, OSError):
        pass
    App().mainloop()
