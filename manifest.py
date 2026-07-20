# -*- coding: utf-8 -*-
"""manifest.py — Registro append-only de conversaciones importadas al vault.

Motivacion (incidente real 2026-07-19): faltaban conversaciones en el vault
y no habia manera de saber si nunca se importaron, si venian de un zip
corrupto, o si el pipeline las habia comido en silencio. Sin trazabilidad
disco->export, cada anomalia era una investigacion a ciegas. Este manifiesto
convierte esas preguntas en un grep:
  - ¿de que zip salio esta nota? -> grep <conv_id>
  - ¿que conversaciones trajo este zip? -> grep <basename del zip>
  - ¿cuando se procesaron y en que orden? -> ordenar por ts

Formato: JSONL (una linea JSON autocontenida por conversacion). Elegido
sobre JSON puro porque el append es trivial, la inspeccion es un grep, y
un corte a mitad no corrompe el archivo entero -- solo pierde la ultima
linea, que es reprocesable.

Decisiones de diseno (V0ra + Claude, 2026-07-19):
- Acumulativo, nunca sobrescribir. El historico no ocupa nada y "cuando
  se importo por primera vez esta conversacion" es una pregunta valiosa.
- Cubre solo el paso 1 (import -> RAW): el resto son transformaciones.
- Estados: 'escrita' (todo bien) y 'error' (excepcion capturada). Las
  vacias no se registran porque los adaptadores las descartan antes.
- Tolerante a fallos de escritura: si el manifiesto no puede escribirse,
  el import continua -- la trazabilidad no debe bloquear la importacion.
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Optional


MANIFEST_FILENAME = "conversaciones_manifest.jsonl"


class ConversationManifest:
    """Escritor incremental. Se abre una vez por ejecucion, se llama a
    record() por cada conversacion, y se cierra al final. Silencioso ante
    errores de I/O: registrar es opcional, importar no."""

    def __init__(self, logs_dir: Optional[Path], export_name: Optional[str] = None):
        self.export_name = export_name or ""
        self.path: Optional[Path] = None
        self._fh = None
        self.escritas = 0
        self.errores = 0
        if not logs_dir:
            return
        try:
            logs_dir = Path(logs_dir)
            logs_dir.mkdir(parents=True, exist_ok=True)
            self.path = logs_dir / MANIFEST_FILENAME
            # append en modo texto UTF-8 con newline explicito para no ganar
            # \r\n en Windows (el JSONL lo prefiere \n a secas)
            self._fh = open(self.path, "a", encoding="utf-8", newline="\n")
        except OSError:
            self._fh = None
            self.path = None

    def record(self, *, conv_id: Optional[str], provider: str, titulo: str,
               fecha_conv: Optional[str], nota_rel: Optional[str],
               estado: str = "escrita", detalle: Optional[str] = None) -> None:
        if self._fh is None:
            return
        entrada = {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "conv_id": conv_id or "",
            "provider": provider or "",
            "titulo": (titulo or "").strip(),
            "fecha_conv": fecha_conv or "",
            "export": self.export_name,
            "nota": nota_rel or "",
            "estado": estado,
        }
        if detalle:
            entrada["detalle"] = detalle[:400]  # cotas defensivas ante tracebacks largos
        try:
            self._fh.write(json.dumps(entrada, ensure_ascii=False) + "\n")
            self._fh.flush()  # persistencia inmediata: si el proceso muere,
                              # las lineas ya escritas se conservan
        except OSError:
            return
        if estado == "escrita":
            self.escritas += 1
        elif estado == "error":
            self.errores += 1

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None
