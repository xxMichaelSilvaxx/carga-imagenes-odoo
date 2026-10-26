"""Installs the libraries of requirements.txt before the GUI starts; uses only the standard library."""
import importlib
import importlib.util
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from common import APP_NAME, data_dir, set_window_icon

APP_DIR = Path(__file__).resolve().parent
ENTRY_POINT = APP_DIR / "carga_imagenes.py"
REQUIREMENTS = APP_DIR / "requirements.txt"
VENV_DIR = APP_DIR / ".venv"
REQUIRED_MODULES = ("PIL", "requests", "openpyxl", "sv_ttk")
WINDOWS = sys.platform == "win32"
# Without it every pip/venv subprocess launched from pythonw.exe flashes a console window
NO_WINDOW = subprocess.CREATE_NO_WINDOW if WINDOWS else 0


def missing_modules():
    return [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]


def venv_python(windowed=False):
    if WINDOWS:
        return VENV_DIR / "Scripts" / ("pythonw.exe" if windowed else "python.exe")
    return VENV_DIR / "bin" / "python"


def console_python():
    current = Path(sys.executable)
    console = current.with_name("python.exe")
    return console if current.name.lower() == "pythonw.exe" and console.is_file() else current


def venv_ready():
    python = venv_python()
    if not python.is_file():
        return False
    check = [str(python), "-c", "import " + ", ".join(REQUIRED_MODULES)]
    return subprocess.run(check, capture_output=True, creationflags=NO_WINDOW).returncode == 0


class InstallWindow(tk.Tk):
    """Progress window while pip downloads the libraries; run() returns True when everything got installed."""

    def __init__(self, python, create_venv):
        super().__init__()
        self.python = python
        self.create_venv = create_venv
        self.events = queue.Queue()
        self.process = None
        self.result = False
        self.log_file = data_dir("logs") / "instalacion.log"
        self.title(APP_NAME)
        set_window_icon(self)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Preparando el aplicativo", font=("Segoe UI Semibold", 12)).pack(anchor="w")
        ttk.Label(frame, justify="left", text="Se están descargando e instalando los componentes necesarios.\n"
                                               "Requiere internet y puede tardar unos minutos.").pack(anchor="w", pady=(6, 12))
        self.bar = ttk.Progressbar(frame, mode="indeterminate", length=460)
        self.bar.pack(fill="x")
        self.bar.start(12)
        self.detail = tk.StringVar(self, "Iniciando...")
        ttk.Label(frame, textvariable=self.detail, foreground="#5b6472", width=70).pack(anchor="w", pady=(8, 0))
        self.update_idletasks()
        x = (self.winfo_screenwidth() - self.winfo_width()) // 2
        y = (self.winfo_screenheight() - self.winfo_height()) // 3
        self.geometry(f"+{x}+{y}")

    def steps(self):
        pip = [str(self.python), "-m", "pip", "install", "--disable-pip-version-check", "--progress-bar", "off",
               "-r", str(REQUIREMENTS)]
        if self.create_venv:
            yield "Creando el entorno del aplicativo...", [str(console_python()), "-m", "venv", str(VENV_DIR)]
        yield "Descargando componentes...", pip

    def work(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        with self.log_file.open("a", encoding="utf-8") as log:
            for message, command in self.steps():
                self.events.put(message)
                log.write(f"\n$ {' '.join(command)}\n")
                try:
                    self.process = subprocess.Popen(
                        command, cwd=APP_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                        encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
                except OSError as error:
                    log.write(f"{error}\n")
                    self.events.put(False)
                    return
                for line in self.process.stdout:
                    log.write(line)
                    self.events.put(line.strip())
                if self.process.wait() != 0:
                    self.events.put(False)
                    return
        self.events.put(True)

    def poll(self):
        while not self.events.empty():
            event = self.events.get_nowait()
            if isinstance(event, bool):
                self.finish(event)
                return
            if event:
                self.detail.set(event[:100])
        self.after(100, self.poll)

    def finish(self, ok):
        self.result = ok
        self.bar.stop()
        if not ok:
            messagebox.showerror(APP_NAME, "No se pudieron instalar los componentes necesarios.\n\n"
                                           "Revise la conexión a internet y vuelva a abrir el aplicativo.\n\n"
                                           f"Detalle técnico: {self.log_file}", parent=self)
        self.destroy()

    def on_close(self):
        if messagebox.askyesno(APP_NAME, "¿Cancelar la instalación?\n\n"
                                         "El aplicativo no podrá abrirse hasta completarla.", parent=self):
            if self.process and self.process.poll() is None:
                self.process.terminate()
            self.bar.stop()
            self.destroy()

    def run(self):
        threading.Thread(target=self.work, daemon=True).start()
        self.after(100, self.poll)
        self.mainloop()
        return self.result


def install_venv():
    return InstallWindow(venv_python(), create_venv=not venv_python().is_file()).run()


def ensure_requirements():
    """Return once the libraries import; otherwise install them, outside a venv into the app's own .venv."""
    if getattr(sys, "frozen", False) or not missing_modules():
        return
    if sys.prefix != sys.base_prefix:
        if not InstallWindow(console_python(), create_venv=False).run():
            sys.exit(1)
        importlib.invalidate_caches()
        return
    # The system Python is never modified: the app restarts from its own .venv
    if not venv_ready() and not install_venv():
        sys.exit(1)
    subprocess.Popen([str(venv_python(windowed=True)), str(ENTRY_POINT), *sys.argv[1:]], cwd=APP_DIR)
    sys.exit(0)


def create_shortcut():
    """Desktop shortcut that opens the app from the .venv without a console window, using icon.ico."""
    script = ("$path = Join-Path ([Environment]::GetFolderPath('Desktop')) ($env:LINK_NAME + '.lnk'); "
              "$link = (New-Object -ComObject WScript.Shell).CreateShortcut($path); "
              "$link.TargetPath = $env:LINK_TARGET; $link.Arguments = $env:LINK_ARGS; "
              "$link.WorkingDirectory = $env:LINK_DIR; $link.IconLocation = $env:LINK_ICON; $link.Save()")
    env = dict(os.environ, LINK_NAME=APP_NAME, LINK_TARGET=str(venv_python(windowed=True)),
               LINK_ARGS=f'"{ENTRY_POINT}"', LINK_DIR=str(APP_DIR), LINK_ICON=str(APP_DIR / "icon.ico"))
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
    try:
        return subprocess.run(command, env=env, capture_output=True, creationflags=NO_WINDOW).returncode == 0
    except OSError:
        return False


def main():
    """Entry point of Instalar.bat: syncs the .venv with requirements.txt, creates the shortcut and opens the app."""
    if not install_venv():
        sys.exit(1)
    message = "La instalación terminó correctamente."
    if WINDOWS and create_shortcut():
        message += f"\n\nSe creó el acceso directo «{APP_NAME}» en el escritorio."
    root = tk.Tk()
    root.withdraw()
    set_window_icon(root)
    messagebox.showinfo(APP_NAME, message + "\n\nEl aplicativo se abrirá ahora.", parent=root)
    root.destroy()
    subprocess.Popen([str(venv_python(windowed=True)), str(ENTRY_POINT)], cwd=APP_DIR)


if __name__ == "__main__":
    main()
