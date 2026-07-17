# -*- coding: utf-8 -*-
"""providers — Adaptadores multi-proveedor de MemorIA2GO.

Cada adaptador convierte el export nativo de un proveedor al modelo
intermedio que consume el resto del pipeline (el contrato de salida de
parse_json_conversations en split_chatgpt_export.py). La detección es
siempre por estructura interna del JSON, nunca por nombre de archivo:
el zip de Claude también contiene un conversations.json y sin esta
distinción el pipeline lo tragaría en silencio generando notas vacías.

Adaptadores:
  claude_adapter  — export de claude.ai (validado contra export real 2026-07-16)
  grok_adapter    — export de grok.com/X (validado contra export real 2026-07-16)
"""
