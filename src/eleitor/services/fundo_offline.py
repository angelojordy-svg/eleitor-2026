"""Gera o fundo offline do mapa (mosaico de tiles) para embutir no HTML.

O mosaico é baixado uma única vez no build e guardado em cache. O HTML
publicado não faz requisição a OSM/Esri no modo offline.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import statistics
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

ATTR_OSM = "© OpenStreetMap contributors"
ATTR_ESRI = (
    "Tiles © Esri — Source: Esri, HERE, Garmin, © OpenStreetMap contributors"
)
TTL_CACHE = 30 * 24 * 3600.0
UA = "Mozilla/5.0 (compatible; eleitor-mapa/0.1; uso local)"
HEADERS = {
    "User-Agent": UA,
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}
URL_OSM = "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"
URL_ESRI = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Street_Map/MapServer/tile/{z}/{y}/{x}"
)


class FundoOfflineError(Exception):
    """Não foi possível baixar/costurar o fundo offline."""


@dataclass
class Camada:
    url: str
    bounds: list[list[float]]
    zoom: int
    fonte: str
    largura: int
    altura: int


@dataclass
class FundoOffline:
    baixo: Camada
    alto: Camada | None
    attr: str
    gerado_em: str

    def para_dict(self) -> dict[str, Any]:
        def camada(item: Camada | None) -> dict[str, Any] | None:
            if item is None:
                return None
            return {"url": item.url, "bounds": item.bounds}

        return {
            "baixo": camada(self.baixo),
            "alto": camada(self.alto),
            "attr": self.attr,
            "gerado_em": self.gerado_em,
        }


def _slug(texto: Any) -> str:
    bruto = unicodedata.normalize("NFKD", str(texto or ""))
    sem_acento = "".join(c for c in bruto if not unicodedata.combining(c))
    return "".join(c if c.isalnum() else "-" for c in sem_acento.lower()).strip("-")


def dir_cache() -> Path:
    override = os.environ.get("ELEITOR_FUNDO_DIR")
    if override:
        return Path(override)
    raiz = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if raiz:
        return Path(raiz) / "eleitor" / "fundo"
    return Path.home() / ".cache" / "eleitor" / "fundo"


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    raio = 6_371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * raio * math.asin(math.sqrt(a))


def _bbox_locais(
    locais: list[dict[str, Any]], raio_km: float | None = None
) -> tuple[float, float, float, float]:
    pontos = [(float(local["lat"]), float(local["lon"])) for local in locais]
    if not pontos:
        raise FundoOfflineError("O payload não tem locais com coordenadas.")
    if raio_km is not None:
        centro_lat = statistics.median(p[0] for p in pontos)
        centro_lon = statistics.median(p[1] for p in pontos)
        perto = [
            p for p in pontos if _haversine(centro_lat, centro_lon, p[0], p[1]) <= raio_km
        ]
        if len(perto) >= 10:
            pontos = perto
    lats = [p[0] for p in pontos]
    lons = [p[1] for p in pontos]
    return (min(lats), min(lons), max(lats), max(lons))


def _expandir(
    bbox: tuple[float, float, float, float], graus: float
) -> tuple[float, float, float, float]:
    min_lat, min_lon, max_lat, max_lon = bbox
    return (
        max(-85.0, min_lat - graus),
        max(-180.0, min_lon - graus),
        min(85.0, max_lat + graus),
        min(180.0, max_lon + graus),
    )


def _lon_para_x(lon: float, zoom: int) -> float:
    return (lon + 180.0) / 360.0 * (2**zoom)


def _lat_para_y(lat: float, zoom: int) -> float:
    seguro = max(-85.05112878, min(85.05112878, lat))
    rad = math.radians(seguro)
    return (
        1.0 - math.log(math.tan(rad) + 1.0 / math.cos(rad)) / math.pi
    ) / 2.0 * (2**zoom)


def tile_range(
    bbox: tuple[float, float, float, float], zoom: int
) -> tuple[int, int, int, int]:
    """(x0, x1, y0, y1) inclusivo dos tiles que cobrem o bbox."""

    n = 2**zoom
    min_lat, min_lon, max_lat, max_lon = bbox
    x0 = max(0, min(n - 1, int(math.floor(_lon_para_x(min_lon, zoom)))))
    x1 = max(0, min(n - 1, int(math.floor(_lon_para_x(max_lon, zoom)))))
    y0 = max(0, min(n - 1, int(math.floor(_lat_para_y(max_lat, zoom)))))
    y1 = max(0, min(n - 1, int(math.floor(_lat_para_y(min_lat, zoom)))))
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    return x0, x1, y0, y1


def tile_bounds(zoom: int, x: int, y: int) -> tuple[float, float, float, float]:
    """(sul, oeste, norte, leste) do tile em lat/lon."""

    n = 2**zoom
    oeste = x / n * 360.0 - 180.0
    leste = (x + 1) / n * 360.0 - 180.0
    norte = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    sul = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return sul, oeste, norte, leste


def bounds_mosaico(
    zoom: int, x0: int, x1: int, y0: int, y1: int
) -> list[list[float]]:
    sul, oeste, _, _ = tile_bounds(zoom, x0, y1)
    _, _, norte, leste = tile_bounds(zoom, x1, y0)
    return [[sul, oeste], [norte, leste]]


def _url_tile(fonte: str, zoom: int, x: int, y: int) -> str:
    if fonte == "osm":
        return URL_OSM.format(z=zoom, x=x, y=y)
    return URL_ESRI.format(z=zoom, y=y, x=x)


def _baixar_tile(
    client: httpx.Client, fonte: str, zoom: int, x: int, y: int
) -> bytes | None:
    url = _url_tile(fonte, zoom, x, y)
    for tentativa in range(2):
        try:
            resposta = client.get(url)
            if resposta.status_code == 200 and len(resposta.content) > 50:
                return resposta.content
        except httpx.HTTPError:
            pass
        time.sleep(0.2 * (tentativa + 1))
    return None


def _escolher_fonte(
    client: httpx.Client, bbox: tuple[float, float, float, float], zoom: int
) -> str:
    x0, x1, y0, y1 = tile_range(bbox, zoom)
    x = (x0 + x1) // 2
    y = (y0 + y1) // 2
    for fonte in ("osm", "esri-street"):
        if _baixar_tile(client, fonte, zoom, x, y) is not None:
            return fonte
    raise FundoOfflineError("OSM e Esri Street não responderam com tiles válidos.")


def _ler_cache(
    jpg: Path, meta_path: Path, refazer: bool
) -> Camada | None:
    if refazer or not jpg.exists() or not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - float(meta.get("gerado_em_ts", 0)) > TTL_CACHE:
        return None
    try:
        b64 = base64.b64encode(jpg.read_bytes()).decode("ascii")
    except OSError:
        return None
    return Camada(
        url=f"data:image/jpeg;base64,{b64}",
        bounds=meta["bounds"],
        zoom=int(meta["zoom"]),
        fonte=str(meta["fonte"]),
        largura=int(meta["largura"]),
        altura=int(meta["altura"]),
    )


def _gerar_camada(
    client: httpx.Client,
    bbox: tuple[float, float, float, float],
    zoom: int,
    fonte: str,
    qualidade: int,
    prefixo: str,
    refazer: bool,
    progresso: Callable[[str], None] | None,
) -> Camada:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - dependência declarada
        raise FundoOfflineError(
            "Pillow não instalado. Rode: pip install Pillow"
        ) from exc

    x0, x1, y0, y1 = tile_range(bbox, zoom)
    colunas = x1 - x0 + 1
    linhas = y1 - y0 + 1
    total = colunas * linhas
    if total > 600:
        raise FundoOfflineError(
            f"Zoom {zoom} exigiria {total} tiles; reduza o zoom/detalhe."
        )

    bounds = bounds_mosaico(zoom, x0, x1, y0, y1)
    chave = hashlib.sha1(
        f"{fonte}|{zoom}|{bounds}|{qualidade}|{colunas}x{linhas}".encode("utf-8")
    ).hexdigest()[:16]
    cache = dir_cache()
    cache.mkdir(parents=True, exist_ok=True)
    jpg = cache / f"{prefixo}_z{zoom}_{chave}.jpg"
    meta_path = cache / f"{prefixo}_z{zoom}_{chave}.json"

    existente = _ler_cache(jpg, meta_path, refazer)
    if existente is not None:
        if progresso:
            progresso(f"Fundo offline z{zoom}: reaproveitado do cache ({existente.largura}x{existente.altura}).")
        return existente

    if progresso:
        progresso(
            f"Fundo offline z{zoom}: baixando {total} tiles de {fonte} "
            f"({colunas}x{linhas})..."
        )
    imagem = Image.new("RGB", (colunas * 256, linhas * 256), (235, 239, 244))
    falhas = 0
    feitos = 0
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            conteudo = _baixar_tile(client, fonte, zoom, x, y)
            feitos += 1
            if conteudo is None:
                falhas += 1
                continue
            try:
                tile = Image.open(io.BytesIO(conteudo)).convert("RGB")
                if tile.size != (256, 256):
                    tile = tile.resize((256, 256))
                imagem.paste(tile, ((x - x0) * 256, (y - y0) * 256))
            except Exception:
                falhas += 1
            if feitos % 10 == 0 and progresso:
                progresso(f"Fundo offline z{zoom}: {feitos}/{total} tiles...")
            time.sleep(0.08)

    if falhas > total * 0.35:
        raise FundoOfflineError(
            f"{falhas}/{total} tiles falharam no zoom {zoom}; fundo descartado."
        )

    buffer = io.BytesIO()
    imagem.save(buffer, format="JPEG", quality=qualidade, optimize=True)
    jpg.write_bytes(buffer.getvalue())
    meta = {
        "bounds": bounds,
        "zoom": zoom,
        "fonte": fonte,
        "largura": imagem.width,
        "altura": imagem.height,
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gerado_em_ts": time.time(),
        "falhas": falhas,
        "tiles": total,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
    return Camada(
        url=f"data:image/jpeg;base64,{b64}",
        bounds=bounds,
        zoom=zoom,
        fonte=fonte,
        largura=imagem.width,
        altura=imagem.height,
    )


def gerar_fundo(
    payload: dict[str, Any],
    zoom_baixo: int = 12,
    zoom_detalhe: int = 15,
    raio_detalhe_km: float = 8.0,
    qualidade: int = 85,
    refazer: bool = False,
    progresso: Callable[[str], None] | None = None,
) -> FundoOffline:
    """Baixa/costura o mosaico do município e do detalhe urbano."""

    locais = payload.get("locais") or []
    meta = payload.get("meta") or {}
    municipio = str(meta.get("municipio") or "municipio").split("/")[0]
    prefixo = f"{_slug(municipio)}_{meta.get('ano') or 2026}"
    bbox_baixo = _expandir(_bbox_locais(locais), 0.01)
    bbox_alto = _expandir(_bbox_locais(locais, raio_detalhe_km), 0.012)
    bbox_alto = (
        max(bbox_baixo[0], bbox_alto[0]),
        max(bbox_baixo[1], bbox_alto[1]),
        min(bbox_baixo[2], bbox_alto[2]),
        min(bbox_baixo[3], bbox_alto[3]),
    )

    with httpx.Client(
        headers=HEADERS, timeout=30.0, follow_redirects=True
    ) as client:
        fonte = _escolher_fonte(client, bbox_baixo, zoom_baixo)
        if progresso:
            progresso(f"Fundo offline: fonte {fonte}.")
        baixo = _gerar_camada(
            client, bbox_baixo, zoom_baixo, fonte, qualidade,
            prefixo, refazer, progresso,
        )

        alto: Camada | None = None
        try:
            x0, x1, y0, y1 = tile_range(bbox_alto, zoom_detalhe)
            total_alto = (x1 - x0 + 1) * (y1 - y0 + 1)
            if total_alto <= 400:
                alto = _gerar_camada(
                    client, bbox_alto, zoom_detalhe, fonte, qualidade,
                    prefixo, refazer, progresso,
                )
            elif progresso:
                progresso(
                    f"Detalhe urbano ignorado: {total_alto} tiles no zoom {zoom_detalhe}."
                )
        except FundoOfflineError as exc:
            if progresso:
                progresso(f"Detalhe urbano indisponível: {exc}")

    attr = ATTR_OSM if fonte == "osm" else ATTR_ESRI
    return FundoOffline(
        baixo=baixo,
        alto=alto,
        attr=attr,
        gerado_em=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
