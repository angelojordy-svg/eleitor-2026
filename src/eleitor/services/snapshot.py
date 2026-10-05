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

CARGOS_MUNICIPIO = (1, 3, 5, 6, 7)
CARGOS_COM_FOTO = (1, 3, 5)

SENADORES_2022 = {
    "PL": 8,
    "UNIÃO": 4,
    "PSD": 3,
    "MDB": 2,
    "PT": 3,
    "REPUBLICANOS": 4,
    "PP": 2,
    "PSB": 1,
}


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
        "vagas": res.vagas,
        "cands": [_cand_dict(c, (fotos or {}).get(c.sqcand)) for c in res.candidatos],
    }


def _resumo_proporcional(res: ResultadoCargo, top: int = 150) -> dict[str, Any]:
    partidos: dict[str, int] = {}
    eleitos: list[dict[str, Any]] = []
    anulados_sub_judice = 0
    for cand in res.candidatos:
        if cand.destinacao and cand.destinacao.lower() != "válido":
            anulados_sub_judice += 1
        if cand.eleito:
            partidos[cand.partido] = partidos.get(cand.partido, 0) + 1
            eleitos.append(
                {
                    "n": cand.numero,
                    "nome": cand.nome_urna or cand.nome,
                    "p": cand.partido,
                    "v": cand.votos,
                    "pct": cand.percentual,
                    "st": cand.situacao,
                    "dvt": cand.destinacao,
                }
            )
    ranking: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for cand in res.candidatos[:top]:
        ranking.append(
            {
                "n": cand.numero,
                "nome": cand.nome_urna or cand.nome,
                "p": cand.partido,
                "v": cand.votos,
                "pct": cand.percentual,
                "e": cand.eleito,
                "st": cand.situacao,
                "dvt": cand.destinacao,
            }
        )
        vistos.add(cand.numero)
    for cand in res.candidatos:
        if cand.eleito and cand.numero not in vistos:
            ranking.append(
                {
                    "n": cand.numero,
                    "nome": cand.nome_urna or cand.nome,
                    "p": cand.partido,
                    "v": cand.votos,
                    "pct": cand.percentual,
                    "e": True,
                    "st": cand.situacao,
                    "dvt": cand.destinacao,
                }
            )
    t = res.totalizacao
    v = res.votos
    return {
        "cargo_nome": res.cargo_nome,
        "vagas": res.vagas,
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
        "partidos": partidos,
        "eleitos": eleitos,
        "ranking": ranking,
        "anulados_sub_judice": anulados_sub_judice,
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
    from eleitor.sources.resultados import parse_resultado

    ufs = [u.lower() for u in UF_SIGLAS if u != "ZZ"]
    tarefas: list[tuple[str, str, str, int]] = []
    for uf in ufs:
        tarefas.append(("1", uf, url_resultado(ELEICAO_FEDERAL, 1, uf=uf), ELEICAO_FEDERAL))
        for cargo in (3, 5, 6, 7):
            tarefas.append((str(cargo), uf, url_resultado(ELEICAO_ESTADUAL, cargo, uf=uf), ELEICAO_ESTADUAL))
    tarefas.append(("8", "df", url_resultado(ELEICAO_ESTADUAL, 8, uf="df"), ELEICAO_ESTADUAL))

    corpos = client.get_urls([t[2] for t in tarefas], ttl=TTL_LIVE, allow_404=True)

    por_uf: dict[str, dict[str, Any]] = {uf: {} for uf in ufs}
    for chave, uf, url, eleicao in tarefas:
        body = corpos.get(url)
        if not body:
            continue
        res = parse_resultado(body)
        if chave in ("1", "3", "5"):
            fotos = _baixar_fotos(client, res.candidatos, eleicao, uf) if com_fotos else {}
            por_uf[uf][chave] = _res_dict(res, fotos)
        else:
            por_uf[uf][chave] = _resumo_proporcional(res)

    return [
        {"uf": uf, "nome": UF_NOMES.get(uf.upper(), uf.upper()), "cargos": por_uf[uf]}
        for uf in ufs
    ]


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


def _partidos_do_cargo(cargo_obj: dict[str, Any] | None) -> tuple[dict[str, int], int, int]:
    if not cargo_obj:
        return {}, 0, 0
    if "partidos" in cargo_obj:
        partidos = dict(cargo_obj.get("partidos") or {})
        return partidos, sum(partidos.values()), int(cargo_obj.get("vagas", 0) or 0)
    partidos: dict[str, int] = {}
    for cand in cargo_obj.get("cands", []):
        if cand.get("e"):
            partidos[cand["p"]] = partidos.get(cand["p"], 0) + 1
    return partidos, sum(partidos.values()), int(cargo_obj.get("vagas", 0) or 0)


def _coletar_congresso(
    estados: list[dict[str, Any]], progresso: Callable[[str], None] | None = None
) -> dict[str, Any]:
    def montar(cargo: str) -> tuple[dict[str, Any], dict[str, Any]]:
        por_uf: dict[str, Any] = {}
        partidos: dict[str, int] = {}
        total = 0
        vagas = 0
        for estado in estados:
            p, t, vg = _partidos_do_cargo(estado["cargos"].get(cargo))
            por_uf[estado["uf"]] = {"total": t, "vagas": vg, "partidos": p}
            total += t
            vagas += vg
            for sg, n in p.items():
                partidos[sg] = partidos.get(sg, 0) + n
        return {"total": total, "vagas": vagas, "partidos": partidos}, por_uf

    casas: dict[str, Any] = {}
    for nome, cargo in (
        ("camara", "6"),
        ("senado_novos", "5"),
        ("estaduais", "7"),
        ("distrital", "8"),
    ):
        if progresso:
            progresso(f"Congresso — {nome}...")
        agregado, por_uf = montar(cargo)
        casas[nome] = agregado
        casas[nome + "_por_uf"] = por_uf
    casas["senado_antigos"] = {
        "total": sum(SENADORES_2022.values()),
        "vagas": 27,
        "partidos": dict(SENADORES_2022),
    }
    return casas


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

    aviso("Estados — Presidente, Governador, Senador e Deputados...")
    estados = _coletar_estados(client, com_fotos)

    aviso("Congresso — agregando Câmara, Senado e assembleias...")
    congresso = _coletar_congresso(estados, progresso)

    municipios_dados: list[dict[str, Any]] = []
    for municipio in municipios:
        aviso(f"{municipio.nome}/{municipio.uf.upper()} — resultados e zonas...")
        municipios_dados.append(
            _coletar_municipio(client, municipio, com_fotos, com_secoes, progresso)
        )

    catalogo = [
        [m.uf, m.codigo, m.nome, m.zonas]
        for m in sorted(loc.municipios, key=lambda x: (x.uf, x.nome))
    ]

    return {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "cargos": {str(k): v for k, v in CARGO_NOMES.items()},
        "brasil": brasil,
        "estados": estados,
        "congresso": congresso,
        "municipios": municipios_dados,
        "catalogo": catalogo,
    }
