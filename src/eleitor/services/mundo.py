"""Mapa da apuração mundial: votos para presidente no exterior (UF ``ZZ``).

A votação fora do Brasil é organizada pela Zona Eleitoral do Exterior (ZZ) em
186 cidades de 134 países/territórios. O TSE não publica o total por país: o
recorte é montado somando as cidades (``zz{mun:05d}``) que pertencem a cada
país. O vínculo cidade -> país está em :mod:`eleitor.paises`.

O 1º turno já está totalizado; o 2º turno (eleição 6258) só é baixado quando o
agregado ``zz`` tem votos, para não gerar 186 requisições (e 404s) à toa.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from eleitor.config import MAPA_ALTURA, MAPA_ESCALA, MAPA_LARGURA, TTL_MAPA_RES, TTL_MAPA_RES_2T
from eleitor.http import CachedClient
from eleitor.models import Candidato, Municipio
from eleitor.paises import CIDADE_PAIS, PAISES
from eleitor.services.localidades import Localidades
from eleitor.services.mapa import _top2_de_body
from eleitor.sources.geo import GeoError, malha_mundo, mundo_para_paths
from eleitor.sources.resultados import parse_resultado, url_resultado

# Eleição do 1º/2º turno para presidente.
ELEICAO_MUNDO = {"1": 6257, "2": 6258}
EPS_MUNDO = 0.35


def _codigo(municipio: Municipio) -> str:
    return str(municipio.codigo).strip().zfill(5)


def _somar(acc: dict[str, dict[str, Any]], cand: Candidato) -> None:
    item = acc.setdefault(
        cand.numero,
        {
            "p": cand.partido,
            "nome": cand.nome_urna or cand.nome,
            "v": 0,
        },
    )
    item["v"] += cand.votos


def _topo(
    cands: dict[str, dict[str, Any]],
    validos: int,
    st: int,
    ts: int,
) -> list[list[Any]] | None:
    if validos <= 0 or not cands:
        return None
    pst = int(round(st * 100.0 / ts)) if ts > 0 else 0
    ordenados = sorted(cands.values(), key=lambda c: c["v"], reverse=True)[:2]
    return [
        [
            item["p"],
            round(item["v"] * 100.0 / validos, 2),
            item["v"],
            item["nome"],
            pst,
        ]
        for item in ordenados
    ]


def _agregar(
    corpos: dict[str, Any],
    cidades: list[Municipio],
) -> tuple[dict[str, list[list[Any]]], dict[str, int], list[list[Any]] | None]:
    """Soma os votos das cidades por país e devolve também o total exterior."""

    por_pais: dict[str, dict[str, Any]] = {}
    total_cands: dict[str, dict[str, Any]] = {}
    total_validos = total_st = total_ts = 0

    for municipio in cidades:
        codigo = _codigo(municipio)
        body = corpos.get(codigo)
        if not body:
            continue
        try:
            res = parse_resultado(body)
        except Exception:
            continue
        total_validos += res.votos.validos
        total_st += res.totalizacao.secoes_totalizadas
        total_ts += res.totalizacao.secoes_total
        for cand in res.candidatos:
            _somar(total_cands, cand)

        iso = CIDADE_PAIS.get(codigo)
        if not iso:
            continue
        acc = por_pais.setdefault(
            iso,
            {"cands": {}, "validos": 0, "st": 0, "ts": 0},
        )
        acc["validos"] += res.votos.validos
        acc["st"] += res.totalizacao.secoes_totalizadas
        acc["ts"] += res.totalizacao.secoes_total
        for cand in res.candidatos:
            _somar(acc["cands"], cand)

    res_paises: dict[str, list[list[Any]]] = {}
    validos_paises: dict[str, int] = {}
    for iso, acc in por_pais.items():
        topo = _topo(acc["cands"], acc["validos"], acc["st"], acc["ts"])
        if topo:
            res_paises[iso] = topo
            validos_paises[iso] = acc["validos"]

    total_topo = _topo(total_cands, total_validos, total_st, total_ts)
    return res_paises, validos_paises, total_topo


def _baixar_cidades(
    client: CachedClient,
    eleicao: int,
    cidades: list[Municipio],
    ttl: float,
    aviso: Callable[[str], None],
) -> dict[str, Any]:
    """Baixa as cidades tolerando falhas individuais (o mapa fica parcial)."""

    def fetch(municipio: Municipio) -> tuple[str, Any | None]:
        codigo = _codigo(municipio)
        url = url_resultado(eleicao, 1, uf="zz", municipio=codigo)
        try:
            return codigo, client.get_json(url, ttl=ttl, allow_404=True)
        except Exception:
            return codigo, None

    corpos: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=max(1, client.workers)) as pool:
        for feitos, (codigo, body) in enumerate(pool.map(fetch, cidades), 1):
            if body:
                corpos[codigo] = body
            if feitos % 30 == 0 or feitos == len(cidades):
                aviso(f"Mundo — {feitos}/{len(cidades)} cidades...")
    return corpos


def bake_mundo(
    client: CachedClient,
    loc: Localidades,
    turno: str,
    progresso: Callable[[str], None] | None = None,
    refazer: bool = False,
) -> dict[str, Any]:
    """Resultado por país em um turno (``res``/``validos``/``total``)."""

    def aviso(msg: str) -> None:
        if progresso:
            progresso(msg)

    eleicao = ELEICAO_MUNDO[str(turno)]
    ttl = 0.0 if refazer else (TTL_MAPA_RES_2T if str(turno) == "2" else TTL_MAPA_RES)

    try:
        todas = loc.exterior
        cidades = [m for m in todas if _codigo(m) in CIDADE_PAIS]
        sem_pais = [m.nome for m in todas if _codigo(m) not in CIDADE_PAIS]
        if sem_pais:
            aviso(
                "Mundo — cidade(s) sem país na tabela (ignoradas): "
                + ", ".join(sem_pais[:8])
                + ("..." if len(sem_pais) > 8 else "")
            )
    except Exception as exc:
        aviso(f"Mundo — lista de cidades do exterior indisponível: {exc}")
        cidades = []

    if not cidades:
        # Sem o config ainda é possível desenhar o mapa, mas não há votos.
        return {"res": {}, "validos": {}, "total": None, "paises": 0, "cidades": 0}

    aviso(f"Mundo — {turno}º turno: {len(cidades)} cidades em {len({CIDADE_PAIS[_codigo(m)] for m in cidades})} países...")

    # Agregado oficial do exterior: usado para o total e, no 2º turno, para
    # evitar baixar as cidades antes de a apuração começar.
    try:
        total_body = client.get_json(
            url_resultado(eleicao, 1, uf="zz"),
            ttl=ttl,
            allow_404=True,
        )
    except Exception:
        total_body = None

    if str(turno) == "2":
        total_res = None
        if total_body:
            try:
                total_res = parse_resultado(total_body)
            except Exception:
                total_res = None
        if not total_res or total_res.votos.validos <= 0:
            aviso("Mundo — 2º turno ainda sem votos; nada a baixar por cidade.")
            return {
                "res": {},
                "validos": {},
                "total": None,
                "paises": 0,
                "cidades": len(cidades),
            }

    corpos = _baixar_cidades(client, eleicao, cidades, ttl, aviso)
    res_paises, validos_paises, total_soma = _agregar(corpos, cidades)

    total_topo = _top2_de_body(total_body) if total_body else None
    if total_topo is None:
        total_topo = total_soma

    return {
        "res": res_paises,
        "validos": validos_paises,
        "total": total_topo,
        "paises": len(res_paises),
        "cidades": len(cidades),
    }


def coletar_mundo(
    client: CachedClient,
    loc: Localidades,
    progresso: Callable[[str], None] | None = None,
    refazer: bool = False,
) -> dict[str, Any] | None:
    """Geometria do mundo + resultados por país do 1º e do 2º turno."""

    def aviso(msg: str) -> None:
        if progresso:
            progresso(msg)

    try:
        aviso("Mundo — geometria dos países (Natural Earth)...")
        malha = malha_mundo(forcar=refazer)
        dados = mundo_para_paths(
            malha,
            largura=MAPA_LARGURA,
            altura=MAPA_ALTURA,
            eps=EPS_MUNDO,
            precisao=1,
        )
    except GeoError as exc:
        aviso(f"Mapa mundial indisponível: {exc}")
        return None

    try:
        cidades = loc.exterior
    except Exception as exc:
        aviso(f"Mundo — config das cidades do exterior indisponível: {exc}")
        cidades = []

    codigos_tse = {_codigo(m) for m in cidades}
    if not codigos_tse:
        # Sem o config, usa a lista estática para o hover continuar útil.
        codigos_tse = {
            c
            for info in PAISES.values()
            for c in info["cidades"]  # type: ignore[union-attr]
            if c != "99252"  # Vaticano não tem seção em 2026
        }
        meta_paises = len(PAISES) - 1
        meta_cidades = len(codigos_tse)
    else:
        meta_paises = len({CIDADE_PAIS[c] for c in codigos_tse if c in CIDADE_PAIS})
        meta_cidades = len(codigos_tse)

    paises: dict[str, dict[str, Any]] = {}
    for iso, geo in dados["itens"].items():
        info = PAISES.get(iso)
        cidades_pais = []
        if info:
            cidades_pais = [c for c in info["cidades"] if c in codigos_tse]  # type: ignore[union-attr]
        paises[iso] = {
            "p": geo["p"],
            "bb": geo["bb"],
            "cx": geo["cx"],
            "cy": geo["cy"],
            "nome": (info or {}).get("nome") or geo.get("nome") or iso,
            "cidades": cidades_pais,
        }

    res: dict[str, dict[str, list[list[Any]]]] = {}
    validos: dict[str, dict[str, int]] = {}
    total: dict[str, list[list[Any]] | None] = {}
    for turno in ("1", "2"):
        dados_turno = bake_mundo(client, loc, turno, progresso=progresso, refazer=refazer)
        res[turno] = dados_turno["res"]
        validos[turno] = dados_turno["validos"]
        total[turno] = dados_turno["total"]

    return {
        "proj": {
            "nome": "mollweide",
            "largura": MAPA_LARGURA,
            "altura": MAPA_ALTURA,
            "viewBox": dados["vb"],
        },
        "escala": {"min": MAPA_ESCALA[0], "max": MAPA_ESCALA[1]},
        "paises": paises,
        "res": res,
        "validos": validos,
        "total": total,
        "meta": {"paises": meta_paises, "cidades": meta_cidades},
    }
