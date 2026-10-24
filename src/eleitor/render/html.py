from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

TEMPLATE_PATH = Path(__file__).resolve().parent / "template.html"
MAPA_URNAS_TEMPLATE_PATH = Path(__file__).resolve().parent / "mapa_urnas.html"
CORRELACAO_TEMPLATE_PATH = Path(__file__).resolve().parent / "correlacao.html"
LEAFLET_DIR = Path(__file__).resolve().parent / "vendor" / "leaflet"
LEAFLET_IMAGENS = (
    "layers.png",
    "layers-2x.png",
    "marker-icon.png",
    "marker-icon-2x.png",
    "marker-shadow.png",
)


def render_html(dados: dict[str, Any]) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    payload = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return template.replace("/*__DADOS__*/", payload)


def _leaflet_css() -> str:
    """CSS do Leaflet com as imagens embutidas em data URI."""

    css = (LEAFLET_DIR / "leaflet.css").read_text(encoding="utf-8")
    for nome in LEAFLET_IMAGENS:
        caminho = LEAFLET_DIR / "images" / nome
        if not caminho.exists():
            continue
        b64 = base64.b64encode(caminho.read_bytes()).decode("ascii")
        css = css.replace(f"images/{nome}", f"data:image/png;base64,{b64}")
    return css


def _leaflet_js() -> str:
    """JS do Leaflet embutido (sem CDN, para não depender de unpkg)."""

    js = (LEAFLET_DIR / "leaflet.js").read_text(encoding="utf-8")
    return js.replace("</script", "<\\/script")


def render_mapa_urnas(
    dados: dict[str, Any], fundo: dict[str, Any] | None = None
) -> str:
    """HTML do mapa eleitoral por local de votação (Leaflet embutido + tiles)."""

    template = MAPA_URNAS_TEMPLATE_PATH.read_text(encoding="utf-8")
    template = template.replace("/*__LEAFLET_CSS__*/", _leaflet_css())
    template = template.replace("/*__LEAFLET_JS__*/", _leaflet_js())
    if fundo:
        fundo_json = json.dumps(
            fundo, ensure_ascii=False, separators=(",", ":")
        ).replace("<", "\\u003c")
    else:
        fundo_json = "null"
    template = template.replace("/*__FUNDO__*/", fundo_json)
    payload = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return template.replace("/*__DADOS__*/", payload)


def render_correlacao(dados: dict[str, Any]) -> str:
    """HTML standalone da correlação e dos limites de co-votação."""

    template = CORRELACAO_TEMPLATE_PATH.read_text(encoding="utf-8")
    payload = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return template.replace("/*__DADOS__*/", payload)
