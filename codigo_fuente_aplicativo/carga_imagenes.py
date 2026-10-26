"""Entry point of the image conversion and upload tool for Odoo."""
import multiprocessing
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == "__main__":
    # Required so the conversion process pool works inside the packaged .exe
    multiprocessing.freeze_support()
    from installer import ensure_requirements

    ensure_requirements()
    from gui import main

    main()
