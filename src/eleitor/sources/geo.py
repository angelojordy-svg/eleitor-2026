"""Geometria do Brasil (malhas do IBGE) e projeção para SVG.

A API de malhas do IBGE devolve GeoJSON com a propriedade ``codarea``:
- para ``intrarregiao=UF``, o código IBGE da UF (2 dígitos, ex.: ``15`` = PA);
- para ``intrarregiao=municipio``, o código IBGE do município (7 dígitos),
  o mesmo valor do campo ``cdi`` do config de municípios do TSE.

O download é cacheado em disco e repetido com espera crescente porque o
serviço do IBGE responde 404 espúrio quando recebe requisições em rajada
(só a resposta 200 é gravada no cache).
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any, Callable

import httpx

MALHAS_BASE = "https://servicodados.ibge.gov.br/api/v3/malhas"
FORMATO = "application/vnd.geo+json"
USER_AGENT = "eleitor-cli/0.1 (consulta local; projeto de estudo)"
QUALIDADE_PADRAO = "minima"

# Mapa-múndi: Natural Earth 50m "map units" (domínio público). Os map units
# separam dependências (ex.: Guiana Francesa = GF), o que a malha de países
# não faz. A 110m fica de fora porque não tem 9 países com votos no exterior.
MUNDO_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_50m_admin_0_map_units.geojson"
)
MUNDO_URL_FALLBACK = (
    "https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@master/"
    "geojson/ne_50m_admin_0_map_units.geojson"
)
MUNDO_ARQUIVO = "mundo-50m.json"
# Antártida e territórios inabitados muito ao sul/oeste só aumentariam o
# viewBox sem ter cidade com votação.
MUNDO_EXCLUIR = {"AQ", "TF", "BV", "HM", "GS", "IO"}

# Projeção Albers (área igual) usada nos mapas oficiais do Brasil.
PHI0 = -12.0
LAM0 = -52.0
PHI1 = -5.0
PHI2 = -25.0


class GeoError(RuntimeError):
    pass


def geo_dir() -> Path:
    override = os.environ.get("ELEITOR_GEO_DIR")
    if override:
        return Path(override)
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if root:
        return Path(root) / "eleitor" / "geo"
    return Path.home() / ".cache" / "eleitor" / "geo"


def url_malha_ufs(qualidade: str = QUALIDADE_PADRAO) -> str:
    return f"{MALHAS_BASE}/paises/BR?formato={FORMATO}&qualidade={qualidade}&intrarregiao=UF"


def url_malha_municipios(uf: str, qualidade: str = QUALIDADE_PADRAO) -> str:
    return f"{MALHAS_BASE}/estados/{uf.upper()}?formato={FORMATO}&qualidade={qualidade}&intrarregiao=municipio"


def _arquivo(nome: str) -> Path:
    destino = geo_dir()
    destino.mkdir(parents=True, exist_ok=True)
    return destino / nome


def baixar_malha(url: str, nome_arquivo: str, tentativas: int = 6) -> dict[str, Any]:
    """Baixa (ou lê do cache local) uma malha do IBGE.

    O IBGE devolve 404 em rajadas; por isso tentamos novamente com espera
    crescente e gravamos em disco apenas respostas 200.
    """

    caminho = _arquivo(nome_arquivo)
    if caminho.exists():
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
            if dados.get("features"):
                return dados
        except (OSError, ValueError):
            pass

    ultimo_erro: str = ""
    with httpx.Client(
        timeout=90.0,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*"},
        follow_redirects=True,
    ) as cliente:
        for tentativa in range(tentativas):
            try:
                resposta = cliente.get(url)
            except httpx.HTTPError as exc:  # rede
                ultimo_erro = str(exc)
                time.sleep(1.5 * (tentativa + 1))
                continue
            if resposta.status_code == 200:
                try:
                    dados = resposta.json()
                except ValueError as exc:
                    ultimo_erro = f"resposta inválida: {exc}"
                    time.sleep(1.5 * (tentativa + 1))
                    continue
                if not dados.get("features"):
                    ultimo_erro = "sem feições"
                    time.sleep(1.5 * (tentativa + 1))
                    continue
                tmp = caminho.with_suffix(".tmp")
                tmp.write_text(json.dumps(dados, separators=(",", ":")), encoding="utf-8")
                tmp.replace(caminho)
                return dados
            ultimo_erro = f"HTTP {resposta.status_code}"
            time.sleep(1.5 * (tentativa + 1))

    raise GeoError(f"falha ao baixar malha do IBGE ({url}): {ultimo_erro}")


def malha_ufs(qualidade: str = QUALIDADE_PADRAO, forcar: bool = False) -> dict[str, Any]:
    caminho = _arquivo(f"ufs-{qualidade}.json")
    if forcar and caminho.exists():
        caminho.unlink()
    return baixar_malha(url_malha_ufs(qualidade), f"ufs-{qualidade}.json")


def malha_municipios(uf: str, qualidade: str = QUALIDADE_PADRAO) -> dict[str, Any]:
    return baixar_malha(url_malha_municipios(uf, qualidade), f"mun-{uf.lower()}-{qualidade}.json")


def url_malha_mundo() -> str:
    return MUNDO_URL


def malha_mundo(forcar: bool = False) -> dict[str, Any]:
    """Malha dos países/territórios do mundo (Natural Earth 50m)."""

    caminho = _arquivo(MUNDO_ARQUIVO)
    if forcar and caminho.exists():
        caminho.unlink()
    try:
        return baixar_malha(url_malha_mundo(), MUNDO_ARQUIVO)
    except GeoError:
        return baixar_malha(MUNDO_URL_FALLBACK, MUNDO_ARQUIVO)


def paths_municipios(
    uf: str,
    qualidade: str = QUALIDADE_PADRAO,
    largura: int = 1000,
    altura: int = 1000,
    eps: float = 0.5,
    precisao: int = 1,
) -> dict[str, Any]:
    """Paths dos municípios de uma UF, já encaixados no próprio quadro.

    Devolve ``{"itens": [[codarea_ibge, path], ...], "vb": [x, y, w, h]}``.
    Cada estado é projetado e enquadrado por si, então o mapa municipal
    aproveita toda a área do desenho (não é um recorte do mapa do Brasil).
    """

    malha = malha_municipios(uf, qualidade)
    itens, _ = geo_para_paths(malha, largura=largura, altura=altura, eps=eps, precisao=precisao)
    if not itens:
        return {"itens": [], "vb": [0, 0, largura, altura]}

    margem = 4.0
    x0 = min(info["bb"][0] for info in itens.values())
    y0 = min(info["bb"][1] for info in itens.values())
    x1 = max(info["bb"][0] + info["bb"][2] for info in itens.values())
    y1 = max(info["bb"][1] + info["bb"][3] for info in itens.values())
    vb = [
        round(x0 - margem, precisao),
        round(y0 - margem, precisao),
        round((x1 - x0) + 2 * margem, precisao),
        round((y1 - y0) + 2 * margem, precisao),
    ]
    return {
        "itens": [[codigo, info["p"]] for codigo, info in sorted(itens.items())],
        "vb": vb,
    }


# --------------------------------------------------------------------------
# Projeção e montagem do "d" do SVG
# --------------------------------------------------------------------------


def _albers(phi0: float, lam0: float, phi1: float, phi2: float) -> Callable[[float, float], tuple[float, float]]:
    rad = math.radians
    n = (math.sin(rad(phi1)) + math.sin(rad(phi2))) / 2.0
    c = math.cos(rad(phi1)) ** 2 + 2.0 * n * math.sin(rad(phi1))
    rho0 = math.sqrt(c - 2.0 * n * math.sin(rad(phi0))) / n

    def projetar(lon: float, lat: float) -> tuple[float, float]:
        rho = math.sqrt(max(0.0, c - 2.0 * n * math.sin(rad(lat)))) / n
        theta = n * rad(lon - lam0)
        return rho * math.sin(theta), rho0 - rho * math.cos(theta)

    return projetar


def _anel_externo(geometria: dict[str, Any]) -> list[list[tuple[float, float]]]:
    tipo = geometria.get("type")
    coords = geometria.get("coordinates") or []
    aneis: list[list[tuple[float, float]]] = []
    if tipo == "Polygon":
        for anel in coords:
            aneis.append([(float(p[0]), float(p[1])) for p in anel])
    elif tipo == "MultiPolygon":
        for poligono in coords:
            for anel in poligono:
                aneis.append([(float(p[0]), float(p[1])) for p in anel])
    return aneis


def _simplificar(pontos: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    """Douglas-Peucker iterativo (sem recursão profunda)."""

    if len(pontos) < 3 or eps <= 0:
        return pontos
    manter = [False] * len(pontos)
    manter[0] = manter[-1] = True
    pilha = [(0, len(pontos) - 1)]
    while pilha:
        inicio, fim = pilha.pop()
        if fim <= inicio + 1:
            continue
        ax, ay = pontos[inicio]
        bx, by = pontos[fim]
        dx, dy = bx - ax, by - ay
        norma = math.hypot(dx, dy)
        dist_max = -1.0
        idx = -1
        for i in range(inicio + 1, fim):
            px, py = pontos[i]
            if norma == 0:
                dist = math.hypot(px - ax, py - ay)
            else:
                dist = abs(dy * px - dx * py + bx * ay - by * ax) / norma
            if dist > dist_max:
                dist_max, idx = dist, i
        if dist_max > eps and idx > 0:
            manter[idx] = True
            pilha.append((inicio, idx))
            pilha.append((idx, fim))
    return [p for p, ok in zip(pontos, manter) if ok]


def _area_centroide(pontos: list[tuple[float, float]]) -> tuple[float, float, float]:
    area = cx = cy = 0.0
    n = len(pontos)
    for i in range(n):
        x0, y0 = pontos[i]
        x1, y1 = pontos[(i + 1) % n]
        cruz = x0 * y1 - x1 * y0
        area += cruz
        cx += (x0 + x1) * cruz
        cy += (y0 + y1) * cruz
    area *= 0.5
    if abs(area) < 1e-9:
        media_x = sum(p[0] for p in pontos) / n
        media_y = sum(p[1] for p in pontos) / n
        return 0.0, media_x, media_y
    return abs(area), cx / (6.0 * area), cy / (6.0 * area)


def _fmt(valor: float, precisao: int) -> str:
    texto = f"{valor:.{precisao}f}"
    return texto.rstrip("0").rstrip(".") if "." in texto else texto


def _contar_pontos(coordenadas: Any) -> int:
    if not coordenadas:
        return 0
    if isinstance(coordenadas[0], (int, float)):
        return 1
    return sum(_contar_pontos(item) for item in coordenadas)


def _mollweide(lon: float, lat: float) -> tuple[float, float]:
    """Projeção de Mollweide (área igual, mundo em ~2:1)."""

    lam = math.radians(lon)
    phi = math.radians(lat)
    theta = phi
    for _ in range(8):
        den = 2.0 + 2.0 * math.cos(2.0 * theta)
        if abs(den) < 1e-12:
            break
        theta -= (2.0 * theta + math.sin(2.0 * theta) - math.pi * math.sin(phi)) / den
    x = (2.0 * math.sqrt(2.0) / math.pi) * lam * math.cos(theta)
    y = math.sqrt(2.0) * math.sin(theta)
    return x, y


def geo_para_paths(
    malha: dict[str, Any],
    largura: int = 1000,
    altura: int = 1000,
    margem: float = 12.0,
    eps: float = 0.35,
    precisao: int = 1,
    projetar: Callable[[float, float], tuple[float, float]] | None = None,
    campo: str = "codarea",
) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
    """Projeta a malha e devolve ``({codarea: {p, bb, cx, cy}}, transformação)``."""

    if projetar is None:
        projetar = _albers(PHI0, LAM0, PHI1, PHI2)
    # Várias feições podem compartilhar o mesmo código (ex.: Portugal
    # continental + Madeira + Açores, ou Cisjordânia + Gaza). Somamos os anéis
    # em vez de deixar a última feição sobrescrever as anteriores.
    por_codigo: dict[str, list[list[tuple[float, float]]]] = {}
    xs: list[float] = []
    ys: list[float] = []

    for feicao in malha.get("features", []):
        codigo = str((feicao.get("properties") or {}).get(campo) or "")
        aneis = _anel_externo(feicao.get("geometry") or {})
        aneis_proj: list[list[tuple[float, float]]] = []
        for anel in aneis:
            pontos = [projetar(lon, lat) for lon, lat in anel]
            if len(pontos) < 3:
                continue
            aneis_proj.append(pontos)
            xs.extend(p[0] for p in pontos)
            ys.extend(p[1] for p in pontos)
        if aneis_proj and codigo:
            por_codigo.setdefault(codigo, []).extend(aneis_proj)

    if not por_codigo:
        raise GeoError("malha sem coordenadas utilizáveis")

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    escala = min(
        (largura - 2 * margem) / max(1e-9, max_x - min_x),
        (altura - 2 * margem) / max(1e-9, max_y - min_y),
    )
    off_x = (largura - (max_x - min_x) * escala) / 2.0 - min_x * escala
    off_y = (altura + (max_y - min_y) * escala) / 2.0 + min_y * escala

    def pixel(x: float, y: float) -> tuple[float, float]:
        return off_x + x * escala, off_y - y * escala

    itens: dict[str, dict[str, Any]] = {}
    for codigo, aneis in por_codigo.items():
        partes: list[str] = []
        melhor_area = -1.0
        melhor_centro = (0.0, 0.0)
        pmin_x = pmin_y = float("inf")
        pmax_x = pmax_y = float("-inf")
        for anel in aneis:
            pix = [pixel(x, y) for x, y in anel]
            pix = _simplificar(pix, eps)
            if len(pix) < 3:
                continue
            pontos = [(round(x, precisao), round(y, precisao)) for x, y in pix]
            partes.append("M" + " ".join(f"{_fmt(x, precisao)},{_fmt(y, precisao)}" for x, y in pontos) + "Z")
            for x, y in pontos:
                pmin_x, pmax_x = min(pmin_x, x), max(pmax_x, x)
                pmin_y, pmax_y = min(pmin_y, y), max(pmax_y, y)
            area, cx, cy = _area_centroide(pontos)
            if area > melhor_area:
                melhor_area, melhor_centro = area, (cx, cy)

        if not partes:
            continue
        itens[codigo] = {
            "p": "".join(partes),
            "bb": [
                round(pmin_x, precisao),
                round(pmin_y, precisao),
                round(max(0.0, pmax_x - pmin_x), precisao),
                round(max(0.0, pmax_y - pmin_y), precisao),
            ],
            "cx": round(melhor_centro[0], precisao),
            "cy": round(melhor_centro[1], precisao),
        }

    transformacao = {
        "largura": float(largura),
        "altura": float(altura),
        "escala": escala,
        "off_x": off_x,
        "off_y": off_y,
    }
    return itens, transformacao


def mundo_para_paths(
    malha: dict[str, Any],
    largura: int = 1000,
    altura: int = 1000,
    eps: float = 0.7,
    precisao: int = 1,
) -> dict[str, Any]:
    """Paths dos países do mundo em Mollweide, já recortados no desenho.

    Devolve ``{"itens": {ISO2: {p, bb, cx, cy, nome}}, "vb": [x, y, w, h]}``.
    Feições com o mesmo ISO são somadas (ex.: Cisjordânia + Faixa de Gaza).
    """

    nomes: dict[str, str] = {}
    nomes_pontos: dict[str, int] = {}
    feicoes: list[dict[str, Any]] = []
    for feicao in malha.get("features", []):
        props = feicao.get("properties") or {}
        iso = str(props.get("ISO_A2_EH") or "").strip()
        if not iso or iso == "-99":
            iso = str(props.get("ISO_A2") or "").strip()
        if not iso or iso == "-99" or iso in MUNDO_EXCLUIR:
            continue
        nome = str(props.get("NAME_PT") or props.get("NAME") or iso)
        pontos = _contar_pontos((feicao.get("geometry") or {}).get("coordinates") or [])
        if pontos > nomes_pontos.get(iso, -1):
            nomes[iso] = nome
            nomes_pontos[iso] = pontos
        feicoes.append(
            {
                "type": "Feature",
                "properties": {"codarea": iso},
                "geometry": feicao.get("geometry") or {},
            }
        )

    if not feicoes:
        raise GeoError("malha do mundo sem feições utilizáveis")

    itens, _ = geo_para_paths(
        {"type": "FeatureCollection", "features": feicoes},
        largura=largura,
        altura=altura,
        eps=eps,
        precisao=precisao,
        projetar=_mollweide,
    )
    if not itens:
        raise GeoError("malha do mundo sem coordenadas utilizáveis")

    for iso, info in itens.items():
        info["nome"] = nomes.get(iso, iso)

    margem = 6.0
    x0 = min(info["bb"][0] for info in itens.values())
    y0 = min(info["bb"][1] for info in itens.values())
    x1 = max(info["bb"][0] + info["bb"][2] for info in itens.values())
    y1 = max(info["bb"][1] + info["bb"][3] for info in itens.values())
    vb = [
        round(x0 - margem, precisao),
        round(y0 - margem, precisao),
        round((x1 - x0) + 2 * margem, precisao),
        round((y1 - y0) + 2 * margem, precisao),
    ]
    return {"itens": itens, "vb": vb}
