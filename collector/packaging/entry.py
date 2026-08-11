"""PyInstaller giriş noktası.

Paket içi göreli import'lar (`from .config import ...`) ancak `collector` bir PAKET
olarak import edilirse çalışır; bu yüzden exe doğrudan `collector/__main__.py`'yi
script gibi değil, bu ince sarmalayıcıyı çalıştırır.

`run()` frozen'da hataları yakalar ve çıkışta pencereyi bekletir (çift tıklamada
pencere anında kapanmasın).
"""

from __future__ import annotations

import multiprocessing
import sys

from collector.__main__ import run

if __name__ == "__main__":
    multiprocessing.freeze_support()  # onefile'da alt süreç kazası olmasın
    sys.exit(run())
