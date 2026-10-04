from __future__ import annotations

import base64
from datetime import datetime
from typing import Any, Callable

from eleitor.config import (
    CARGO_NOMES,
    ELEICAO_ESTADUAL,
    ELEICAO_FEDERAL,
    TTL_LIVE,
    UF_NOMES,
    UF_SIGLAS,
)
from eleitor.http import CachedClient
from eleitor.models import Candidato, Municipio, ResultadoCargo
from eleitor.services.localidades import Localidades
from eleitor.services.votos import resultado, votos_secoes_zona
from eleitor.sources.resultados import url_foto, url_resultado

CARGOS_ESTADO = (3, 5)
CARGOS_MUNICIPIO = (1, 3, 5, 6, 7)
CARGOS_COM_FOTO = (1, 3, 5)


def _cand_dict(cand: Candidato, foto: str | None = None) -> dict[str, Any]:
    item = {
        "n": cand.numero,
        "nome": cand.nome_urna or cand.nome,
        "p": cand.partido,
        "v": cand.votos,
        "pct": cand.percentual,
        "e": cand.eleito,
    }
    if foto:
        item["foto"] = foto
    return item


def _res_dict(res: ResultadoCargo, fotos: dict[str, str] | None = None) -> dict[str, Any]:
    t = res.totalizacao
    v = res.votos
    return {
        "cargo": res.cargo,
        "cargo_nome": res.cargo_nome,
        "tot": {
            "st": t.secoes_totalizadas,
            "ts": t.secoes_total,
            "pct": t.percentual_secoes,
            "gerado": t.gerado_em,
        },
        "votos": {
            "validos": v.validos,
            "brancos": v.brancos,
            "nulos": v.nulos,
            "anulados": v.anulados,
        },
        "cands": [_cand_dict(c, (fotos or {}).get(c.sqcand)) for c in res.candidatos],
    }


def _secoes_dict(secoes: dict[str, dict]) -> list[dict[str, Any]]:
    itens: list[dict[str, Any]] = []
    for numero in sorted(secoes):
        dados = secoes[numero]
        cargos: dict[str, Any] = {}
        for cargo, info in dados.get("cargos", {}).items():
            votos: dict[str, int] = {}
            brancos = nulos = legenda = 0
            for voto in info.get("votos", []):
                tipo = voto.get("tipo")
                if tipo == "nominal":
                    codigo = str(voto.get("codigo", ""))
                    votos[codigo] = votos.get(codigo, 0) + voto["votos"]
                elif tipo == "branco":
                    brancos += voto["votos"]
                elif tipo == "nulo":
                    nulos += voto["votos"]
                elif tipo == "legenda":
                    legenda += voto["votos"]
            cargos[str(cargo)] = {
                "aptos": info.get("aptos", 0),
                "comp": info.get("comparecimento", 0),
                "votos": votos,
                "b": brancos,
                "nu": nulos,
                "lg": legenda,
            }
        itens.append({"sec": numero, "cargos": cargos})
    return itens


def _baixar_fotos(
    client: CachedClient,
    candidatos: list[Candidato],
    eleicao: int,
    uf: str | None,
) -> dict[str, str]:
    fotos: dict[str, str] = {}
    for cand in candidatos:
        if not cand.sqcand:
            continue
        try:
            raw = client.get_bytes(url_foto(eleicao, uf, cand.sqcand), allow_404=True)
        except Exception:
            raw = None
        if raw:
            fotos[cand.sqcand] = "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")
    return fotos


def _coletar_brasil(client: CachedClient, com_fotos: bool) -> dict[str, Any]:
    res = resultado(client, ELEICAO_FEDERAL, 1, ttl=TTL_LIVE)
    fotos = _baixar_fotos(client, res.candidatos, ELEICAO_FEDERAL, None) if com_fotos else {}
    return _res_dict(res, fotos)


def _coletar_estados(client: CachedClient, com_fotos: bool) -> list[dict[str, Any]]:
    ufs = [u for u in UF_SIGLAS if u != "ZZ"]
    urls: list[str] = []
    for uf in ufs:
        for cargo in CARGOS_ESTADO:
            urls.append(url_resultado(ELEICAO_ESTADUAL, cargo, uf=uf))
    corpos = client.get_urls(urls, ttl=TTL_LIVE, allow_404=True)

    estados: list[dict[str, Any]] = []
    pos = 0
    for uf in ufs:
        cargos: dict[str, Any] = {}
        for cargo in CARGOS_ESTADO:
            body = corpos.get(urls[pos])
            pos += 1
            if not body:
                continue
            from eleitor.sources.resultados import parse_resultado

            res = parse_resultado(body)
            fotos = _baixar_fotos(client, res.candidatos, ELEICAO_ESTADUAL, uf) if com_fotos else {}
            cargos[str(cargo)] = _res_dict(res, fotos)
        estados.append(
            {
                "uf": uf,
                "nome": UF_NOMES.get(uf.upper(), uf.upper()),
                "cargos": cargos,
            }
        )
    return estados


def _coletar_municipio(
    client: CachedClient,
    municipio: Municipio,
    com_fotos: bool,
    com_secoes: bool,
    progresso: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    from eleitor.sources.resultados import parse_resultado

    def aviso(msg: str) -> None:
        if progresso:
            progresso(msg)

    ufs = municipio.uf
    urls: list[tuple[int, str | None, str]] = []
    for cargo in CARGOS_MUNICIPIO:
        eleicao = ELEICAO_FEDERAL if cargo == 1 else ELEICAO_ESTADUAL
        urls.append((cargo, None, url_resultado(eleicao, cargo, uf=ufs, municipio=municipio.codigo)))
        for zona in municipio.zonas:
            urls.append(
                (cargo, zona, url_resultado(eleicao, cargo, uf=ufs, municipio=municipio.codigo, zona=zona))
            )
    corpos = client.get_urls([u for _, _, u in urls], ttl=TTL_LIVE, allow_404=True)

    cargos: dict[str, Any] = {}
    for (cargo, zona, url) in urls:
        body = corpos.get(url)
        if not body:
            continue
        res = parse_resultado(body)
        eleicao = ELEICAO_FEDERAL if cargo == 1 else ELEICAO_ESTADUAL
        fotos: dict[str, str] = {}
        if com_fotos and cargo in CARGOS_COM_FOTO:
            fotos = _baixar_fotos(client, res.candidatos, eleicao, ufs)
        item = _res_dict(res, fotos)
        chave = str(cargo)
        if chave not in cargos:
            cargos[chave] = {"cargo_nome": res.cargo_nome, "total": item, "zonas": []}
        if zona is None:
            cargos[chave]["total"] = item
        else:
            cargos[chave]["zonas"].append({"zona": zona, **item})

    secoes_por_zona: dict[str, Any] = {}
    if com_secoes:
        for zona in municipio.zonas:
            aviso(f"{municipio.nome}/{municipio.uf.upper()} — baixando urnas da zona {zona}...")
            try:
                votos = votos_secoes_zona(client, municipio.uf, municipio.codigo, zona)
            except Exception:
                votos = {}
            if votos:
                secoes_por_zona[zona] = _secoes_dict(votos)

    return {
        "uf": municipio.uf,
        "codigo": municipio.codigo,
        "nome": municipio.nome,
        "cargos": cargos,
        "secoes_por_zona": secoes_por_zona,
    }


def coletar_snapshot(
    client: CachedClient,
    loc: Localidades,
    municipios: list[Municipio],
    com_fotos: bool = True,
    com_secoes: bool = True,
    progresso: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    def aviso(msg: str) -> None:
        if progresso:
            progresso(msg)

    aviso("Brasil — resultado de Presidente...")
    brasil = _coletar_brasil(client, com_fotos)

    aviso("Estados — Governador e Senador...")
    estados = _coletar_estados(client, com_fotos)

    municipios_dados: list[dict[str, Any]] = []
    for municipio in municipios:
        aviso(f"{municipio.nome}/{municipio.uf.upper()} — resultados e zonas...")
        municipios_dados.append(
            _coletar_municipio(client, municipio, com_fotos, com_secoes, progresso)
        )

    catalogo = [
        [m.uf, m.codigo, m.nome] for m in sorted(loc.municipios, key=lambda x: (x.uf, x.nome))
    ]

    return {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "cargos": {str(k): v for k, v in CARGO_NOMES.items()},
        "brasil": brasil,
        "estados": estados,
        "municipios": municipios_dados,
        "catalogo": catalogo,
    }
