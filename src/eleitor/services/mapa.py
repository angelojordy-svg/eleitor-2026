"""Monta o recorte do mapa: geometria das UFs + força da maioria por estado.

A cor sai das regras: partido do mais votado (matiz) e tamanho da maioria
(percentual do líder sobre os votos válidos) na intensidade.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from eleitor.config import (
    CARGOS_MAPA,
    IBGE_UF_CODIGO,
    MAPA_ALTURA,
    MAPA_ESCALA,
    MAPA_LARGURA,
    SEGUNDO_TURNO,
    TTL_LIVE,
    TTL_MAPA_RES,
    TTL_MAPA_RES_2T,
    UF_SIGLAS,
)
from eleitor.http import CachedClient
from eleitor.models import Municipio
from eleitor.services.localidades import Localidades
from eleitor.sources import geo as geo_src
from eleitor.sources.geo import GeoError, geo_para_paths, malha_ufs
from eleitor.sources.resultados import parse_resultado, url_resultado

ELEICAO_DO_CARGO_TURNO = {(1, 1): 6257, (3, 1): 6259, (1, 2): 6258, (3, 2): 6260}

# Versão do bake gravado em disco: mudar aqui força recalcular (o formato da
# entrada mudou, ex.: passou a guardar o percentual de apuração).
VERSAO_BAKE = 2


def _apuracao(resumo: dict[str, Any] | None) -> int:
    """Percentual de seções totalizadas (0-100) arredondado."""

    if not resumo:
        return 0
    tot = resumo.get("tot") or {}
    pct = tot.get("pct")
    if pct is None:
        total = float(tot.get("ts") or 0)
        pct = (float(tot.get("st") or 0) * 100.0 / total) if total else 0.0
    return int(round(float(pct or 0)))


def _top2(resultado_uf: dict[str, Any] | None) -> list[list[Any]] | None:
    """[[partido, share, votos, nome, apuracao%], ...] do top 2."""

    if not resultado_uf:
        return None
    cands = resultado_uf.get("cands") or []
    if not cands:
        return None
    validos = int(((resultado_uf.get("votos") or {}).get("validos") or 0))
    apuracao = _apuracao(resultado_uf)
    itens: list[list[Any]] = []
    for cand in cands[:2]:
        itens.append(
            [
                cand.get("p") or "",
                _share(cand, validos),
                int(cand.get("v") or 0),
                cand.get("nome") or "",
                apuracao,
            ]
        )
    return itens


def _share(cand: dict[str, Any], validos: int) -> float:
    votos = int(cand.get("v") or 0)
    if validos > 0:
        return round(votos * 100.0 / validos, 2)
    return round(float(cand.get("pct") or 0.0), 2)


def _top2_de_body(body: dict[str, Any] | None) -> list[list[Any]] | None:
    """Resume um corpo EA20 (JSON cru do TSE) no top 2 para o mapa."""

    if not body:
        return None
    res = parse_resultado(body)
    cands = [
        {"p": c.partido, "v": c.votos, "pct": c.percentual, "nome": c.nome_urna or c.nome}
        for c in res.candidatos
    ]
    if not cands:
        return None
    t = res.totalizacao
    return _top2(
        {
            "cands": cands,
            "votos": {"validos": res.votos.validos},
            "tot": {
                "st": t.secoes_totalizadas,
                "ts": t.secoes_total,
                "pct": t.percentual_secoes,
            },
        }
    )


def coletar_mapa(
    client: CachedClient,
    estados: list[dict[str, Any]],
    brasil: dict[str, Any] | None = None,
    com_turno2: bool = True,
    progresso: Callable[[str], None] | None = None,
) -> dict[str, Any] | None:
    """Geometria + líder por UF (1º turno do snapshot e 2º turno ao vivo)."""

    def aviso(msg: str) -> None:
        if progresso:
            progresso(msg)

    try:
        aviso("Mapa — geometria dos estados (IBGE)...")
        malha = malha_ufs()
        itens, _ = geo_para_paths(malha, largura=MAPA_LARGURA, altura=MAPA_ALTURA, eps=0.5)
    except GeoError as exc:
        aviso(f"Mapa indisponível: {exc}")
        return None

    ufs_geo: dict[str, dict[str, Any]] = {}
    for codigo, info in itens.items():
        sigla = IBGE_UF_CODIGO.get(codigo)
        if sigla:
            ufs_geo[sigla] = info
    if not ufs_geo:
        return None

    # viewBox justo em volta do desenho (o encaixe da projeção deixa sobra).
    margem = 6.0
    x0 = min(info["bb"][0] for info in ufs_geo.values())
    y0 = min(info["bb"][1] for info in ufs_geo.values())
    x1 = max(info["bb"][0] + info["bb"][2] for info in ufs_geo.values())
    y1 = max(info["bb"][1] + info["bb"][3] for info in ufs_geo.values())
    viewbox = [
        round(x0 - margem, 1),
        round(y0 - margem, 1),
        round((x1 - x0) + 2 * margem, 1),
        round((y1 - y0) + 2 * margem, 1),
    ]

    res: dict[str, dict[str, dict[str, Any]]] = {str(c): {"1": {}} for c in CARGOS_MAPA}
    for estado in estados:
        sigla = str(estado.get("uf", "")).upper()
        if not sigla:
            continue
        for cargo in CARGOS_MAPA:
            topo = _top2((estado.get("cargos") or {}).get(str(cargo)))
            if topo:
                res[str(cargo)]["1"][sigla] = topo

    nacional: dict[str, dict[str, Any]] = {"1": {"1": _top2(brasil) if brasil else None}}

    if com_turno2:
        siglas = [u.lower() for u in UF_SIGLAS if u != "ZZ"]
        for cargo in CARGOS_MAPA:
            res[str(cargo)].setdefault("2", {})

        aviso("Mapa — 2º turno de Presidente (por estado)...")
        eleicao_pres2 = SEGUNDO_TURNO[6257]
        urls = [url_resultado(eleicao_pres2, 1, uf=uf) for uf in siglas]
        corpos = client.get_urls(urls, ttl=TTL_LIVE, allow_404=True)
        for uf, url in zip(siglas, urls):
            topo = _top2_de_body(corpos.get(url))
            if topo:
                res["1"]["2"][uf.upper()] = topo
        nacional["1"]["2"] = _top2_de_body(
            client.get_json(url_resultado(eleicao_pres2, 1), ttl=TTL_LIVE, allow_404=True)
        )

        if 6259 in SEGUNDO_TURNO:
            aviso("Mapa — 2º turno de Governador (por estado)...")
            eleicao_gov2 = SEGUNDO_TURNO[6259]
            urls = [url_resultado(eleicao_gov2, 3, uf=uf) for uf in siglas]
            corpos = client.get_urls(urls, ttl=TTL_LIVE, allow_404=True)
            for uf, url in zip(siglas, urls):
                topo = _top2_de_body(corpos.get(url))
                if topo:
                    res["3"]["2"][uf.upper()] = topo

    return {
        "proj": {"nome": "albers", "largura": MAPA_LARGURA, "altura": MAPA_ALTURA, "viewBox": viewbox},
        "escala": {"min": MAPA_ESCALA[0], "max": MAPA_ESCALA[1]},
        "uf": ufs_geo,
        "res": res,
        "brasil": nacional,
    }


# --------------------------------------------------------------------------
# Municípios: geometria por UF + líder por município
# --------------------------------------------------------------------------


def dir_dados() -> Path:
    """Cache dos bakes do mapa (resultado por município)."""

    override = os.environ.get("ELEITOR_MAPA_DIR")
    if override:
        return Path(override)
    raiz = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if raiz:
        return Path(raiz) / "eleitor" / "mapa"
    return Path.home() / ".cache" / "eleitor" / "mapa"


def _arquivo_bake(cargo: str, turno: str) -> Path:
    destino = dir_dados()
    destino.mkdir(parents=True, exist_ok=True)
    return destino / f"res-{cargo}-t{turno}.json"


def _ler_bake(
    cargo: str, turno: str, refazer: bool, ufs: list[str]
) -> tuple[dict[str, dict[str, list]], bool]:
    """Devolve (parcial, esta_completo) do bake em disco.

    Um bake interrompido é retomado de onde parou (as UFs já feitas são
    puladas). Só é reaproveitado inteiro quando cobre todas as UFs pedidas,
    está marcado como ``completo`` e dentro do TTL — assim um bake parcial
    (ex.: só PA) não engana um bake do Brasil inteiro.
    """

    if refazer:
        return {}, False
    caminho = _arquivo_bake(cargo, turno)
    if not caminho.exists():
        return {}, False
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, False
    if dados.get("versao") != VERSAO_BAKE:
        return {}, False
    ttl = TTL_MAPA_RES if turno == "1" else TTL_MAPA_RES_2T
    if time.time() - float(dados.get("gerado_em", 0.0)) > ttl:
        return {}, False
    cobertas = {str(u).upper() for u in (dados.get("ufs") or [])}
    pedidas = {str(u).upper() for u in ufs}
    return dados.get("por_uf") or {}, bool(dados.get("completo")) and pedidas <= cobertas


def _gravar_bake(
    cargo: str, turno: str, por_uf: dict[str, dict[str, list]], completo: bool
) -> None:
    caminho = _arquivo_bake(cargo, turno)
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            {
                "versao": VERSAO_BAKE,
                "gerado_em": time.time(),
                "completo": completo,
                "ufs": sorted(por_uf),
                "por_uf": por_uf,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    tmp.replace(caminho)


def _topo(body: dict[str, Any] | None, quantidade: int) -> list[list[Any]] | None:
    """Top N do corpo EA20: [partido, % válidos, votos, nome, apuração%]."""

    if not body:
        return None
    res = parse_resultado(body)
    if not res.candidatos:
        return None
    validos = res.votos.validos
    apuracao = int(round(res.totalizacao.percentual_secoes or 0))
    itens = [
        [
            candidato.partido,
            _share({"v": candidato.votos, "pct": candidato.percentual}, validos),
            candidato.votos,
            candidato.nome_urna or candidato.nome,
            apuracao,
        ]
        for candidato in res.candidatos[:quantidade]
    ]
    return itens or None


def _municipios_por_uf(loc: Localidades) -> dict[str, list[Municipio]]:
    agrupado: dict[str, list[Municipio]] = {}
    for municipio in loc.municipios:
        agrupado.setdefault(municipio.uf, []).append(municipio)
    return agrupado


def bake_resultado_municipios(
    client: CachedClient,
    loc: Localidades,
    cargo: str,
    turno: str,
    ufs: list[str],
    progresso: Callable[[str], None] | None = None,
    refazer: bool = False,
    bloco: int = 300,
) -> dict[str, dict[str, list]]:
    """Líder (1º turno) ou top 2 (2º turno) de cada município: {uf: {ibge: topo}}."""

    def aviso(msg: str) -> None:
        if progresso:
            progresso(msg)

    cache, completo = _ler_bake(cargo, turno, refazer, ufs)
    if completo and cache:
        aviso(f"Mapa — líder por município ({cargo}º/{turno}º) reaproveitado do cache.")
        return cache
    if cache:
        aviso(
            f"Mapa — retomando o bake ({cargo}º/{turno}º): "
            f"{len(cache)} estado(s) já calculado(s)."
        )
    por_uf: dict[str, dict[str, list]] = dict(cache)

    eleicao = ELEICAO_DO_CARGO_TURNO[(int(cargo), int(turno))]
    quantidade = 1 if turno == "1" else 2
    por_uf_municipios = _municipios_por_uf(loc)
    pendentes = [uf for uf in ufs if uf.upper() not in por_uf]
    total = sum(len(por_uf_municipios.get(uf, [])) for uf in pendentes)
    aviso(f"Mapa — líder por município ({cargo}º turno): {total} municípios pendentes...")

    feitos = 0
    for uf in pendentes:
        municipios = por_uf_municipios.get(uf, [])
        if not municipios:
            por_uf[uf.upper()] = {}
            continue
        entradas: dict[str, list] = {}
        for inicio in range(0, len(municipios), bloco):
            parte = municipios[inicio : inicio + bloco]
            urls = [url_resultado(eleicao, int(cargo), uf=uf, municipio=m.codigo) for m in parte]
            corpos = client.get_urls(urls, ttl=TTL_LIVE, allow_404=True)
            for municipio, url in zip(parte, urls):
                topo = _topo(corpos.get(url), quantidade)
                if topo and topo[0][2] > 0:
                    entradas[municipio.ibge] = topo
            feitos += len(parte)
            aviso(f"Mapa — {uf.upper()}: {min(feitos, total)}/{total} municípios...")
        por_uf[uf.upper()] = entradas
        _gravar_bake(cargo, turno, por_uf, completo=False)  # progresso sobrevive a falhas

    _gravar_bake(cargo, turno, por_uf, completo=True)
    return por_uf


def coletar_mapa_municipios(
    client: CachedClient,
    loc: Localidades,
    combos: list[tuple[str, str]],
    ufs: list[str] | None = None,
    qualidade: str = geo_src.QUALIDADE_PADRAO,
    eps: float = 0.5,
    progresso: Callable[[str], None] | None = None,
    refazer: bool = False,
) -> dict[str, Any]:
    """Geometria municipal (IBGE) + líder por município para os combos pedidos.

    Os resultados saem como vetores alinhados por índice com
    ``mun[uf]["itens"]`` (código IBGE crescente), o que evita repetir a
    chave do município no payload.
    """

    def aviso(msg: str) -> None:
        if progresso:
            progresso(msg)

    ufs = [uf.lower() for uf in (ufs or [u for u in UF_SIGLAS if u != "ZZ"])]
    cd_por_ibge = {m.ibge: m.codigo for m in loc.municipios}
    mun: dict[str, Any] = {}
    for uf in ufs:
        try:
            aviso(f"Mapa — geometria dos municípios: {uf.upper()}...")
            dados = geo_src.paths_municipios(uf, qualidade=qualidade, eps=eps)
        except GeoError as exc:
            aviso(f"Mapa — {uf.upper()} sem geometria ({exc}).")
            continue
        if dados["itens"]:
            # [código IBGE, código TSE (rota), path]
            dados["itens"] = [
                [ibge, cd_por_ibge.get(ibge, ""), path] for ibge, path in dados["itens"]
            ]
            mun[uf.upper()] = dados

    munres: dict[str, dict[str, dict[str, list]]] = {}
    for cargo, turno in combos:
        por_uf = bake_resultado_municipios(client, loc, cargo, turno, ufs, progresso, refazer)
        combinado: dict[str, list] = {}
        for uf, dados_geo in mun.items():
            entradas = por_uf.get(uf, {})
            combinado[uf] = [entradas.get(item[0]) for item in dados_geo["itens"]]
        munres.setdefault(str(cargo), {})[str(turno)] = combinado

    return {"mun": mun, "munres": munres}


def combos_com_dados(mapa: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Combos cargo/turno que já têm votos no recorte por estado.

    O 1º turno entra sempre (já está totalizado); o 2º turno só entra quando
    a apuração começa, para não baixar 5.571 arquivos zerados.
    """

    if not mapa:
        return [("1", "1"), ("3", "1")]
    combos: list[tuple[str, str]] = []
    for cargo in CARGOS_MAPA:
        for turno in ("1", "2"):
            por_turno = (mapa.get("res") or {}).get(str(cargo), {}).get(turno) or {}
            tem_votos = any(
                isinstance(topo, list) and topo and isinstance(topo[0], list) and topo[0][2] > 0
                for topo in por_turno.values()
            )
            if tem_votos or turno == "1":
                combos.append((str(cargo), turno))
    return combos

