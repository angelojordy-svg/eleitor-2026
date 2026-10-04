from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TEMPLATE_PATH = Path(__file__).resolve().parent / "template.html"


def render_html(dados: dict[str, Any]) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    payload = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return template.replace("/*__DADOS__*/", payload)
