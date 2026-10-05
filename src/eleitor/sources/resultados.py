from __future__ import annotations

from typing import Any

from eleitor.config import (
    BASE_URL,
    CARGO_NOMES,
    CICLO,
    ELEICAO_CONFIG_MUNICIPIOS,
    PLEITO,
)
from eleitor.models import (
    Candidato,
    Municipio,
    ResultadoCargo,
    Secao,
    Totalizacao,
    TotaisVotos,
    ZonaSecoes,
)


def url_ele_c() -> str:
    return f"{BASE_URL}/comum/config/ele-c.json"


def url_municipios_config() -> str:
    eleicao = ELEICAO_CONFIG_MUNICIPIOS
    return f"{BASE_URL}/{CICLO}/{eleicao}/config/mun-e{eleicao:06d}-cm.json"


def url_resultado(
    eleicao: int,
    cargo: int,
    uf: str | None = None,
    municipio: str | None = None,
    zona: str | None = None,
) -> str:
    if uf is None:
        abr = "br"
        prefixo = "br"
    else:
        uf = uf.lower()
        abr = uf
        if municipio is None:
            prefixo = uf
        elif zona is None:
            prefixo = f"{uf}{int(municipio):05d}"
        else:
            prefixo = f"{uf}{int(municipio):05d}-z{int(zona):04d}"
    return f"{BASE_URL}/{CICLO}/{eleicao}/dados/{abr}/{prefixo}-c{cargo:04d}-e{eleicao:06d}-u.json"


def url_acompanhamento(eleicao: int, uf: str | None = None) -> str:
    abr = (uf or "br").lower()
    return f"{BASE_URL}/{CICLO}/{eleicao}/dados/{abr}/{abr}-e{eleicao:06d}-ab.json"


def url_foto(eleicao: int, uf: str | None, sqcand: str) -> str:
    abr = (uf or "br").lower()
    return f"{BASE_URL}/{CICLO}/{eleicao}/fotos/{abr}/{sqcand}.jpeg"


def url_secoes_config(uf: str) -> str:
    uf = uf.lower()
    return f"{BASE_URL}/{CICLO}/arquivo-urna/{PLEITO}/config/{uf}/{uf}-p{PLEITO:06d}-cs.json"


def url_secao_aux(uf: str, municipio: str, zona: str, secao: str) -> str:
    uf = uf.lower()
    mun = f"{int(municipio):05d}"
    zon = f"{int(zona):04d}"
    sec = f"{int(secao):04d}"
    nome = f"p{PLEITO:06d}-{uf}-m{mun}-z{zon}-s{sec}-aux.json"
    return f"{BASE_URL}/{CICLO}/arquivo-urna/{PLEITO}/dados/{uf}/{mun}/{zon}/{sec}/{nome}"


def _to_int(valor: Any) -> int:
    if valor in (None, ""):
        return 0
    return int(valor)


def _to_float(valor: Any) -> float:
    if valor in (None, ""):
        return 0.0
    return float(str(valor).replace(".", "").replace(",", "."))


def parse_resultado(data: dict[str, Any]) -> ResultadoCargo:
    cargos = data.get("carg") or []
    cargo_data = cargos[0] if cargos else {}
    cargo_codigo = int(cargo_data.get("cd", 0))
    cargo_nome = cargo_data.get("nmn") or CARGO_NOMES.get(cargo_codigo, str(cargo_codigo))

    candidatos: list[Candidato] = []
    for agremiacao in cargo_data.get("agr", []):
        for partido in agremiacao.get("par", []):
            sigla = partido.get("sg") or agremiacao.get("com") or ""
            for cand in partido.get("cand", []):
                candidatos.append(
                    Candidato(
                        numero=str(cand.get("n", "")),
                        nome=cand.get("nm", ""),
                        nome_urna=cand.get("nmu", "") or cand.get("nm", ""),
                        partido=sigla,
                        votos=_to_int(cand.get("vap")),
                        percentual=_to_float(cand.get("pvap")),
                        situacao=cand.get("st", "") or "",
                        eleito=cand.get("e") == "s",
                        sqcand=str(cand.get("sqcand", "")),
                    )
                )
    candidatos.sort(key=lambda c: c.votos, reverse=True)

    votos_data = data.get("v") or {}
    votos = TotaisVotos(
        total=_to_int(votos_data.get("tv")),
        validos=_to_int(votos_data.get("vv")),
        brancos=_to_int(votos_data.get("vb")),
        nulos=_to_int(votos_data.get("vn")),
        anulados=_to_int(votos_data.get("van")),
    )

    secoes = data.get("s") or {}
    eleitorado = data.get("e") or {}
    totalizacao = Totalizacao(
        secoes_total=_to_int(secoes.get("ts")),
        secoes_totalizadas=_to_int(secoes.get("st")),
        percentual_secoes=_to_float(secoes.get("pst")),
        eleitores_total=_to_int(eleitorado.get("te")),
        eleitores_secoes_totalizadas=_to_int(eleitorado.get("est")),
        gerado_em=f"{data.get('dg', '')} {data.get('hg', '')}".strip(),
    )

    return ResultadoCargo(
        eleicao=int(data.get("ele", 0)),
        cargo=cargo_codigo,
        cargo_nome=cargo_nome,
        abrangencia=str(data.get("cdabr", "")),
        candidatos=candidatos,
        votos=votos,
        totalizacao=totalizacao,
        vagas=_to_int(cargo_data.get("nv")),
    )


def parse_municipios(data: dict[str, Any]) -> list[Municipio]:
    municipios: list[Municipio] = []
    for abr in data.get("abr", []):
        uf = str(abr.get("cd", "")).lower()
        for mu in abr.get("mu", []):
            municipios.append(
                Municipio(
                    uf=uf,
                    codigo=str(mu.get("cd", "")),
                    ibge=str(mu.get("cdi", "")),
                    nome=mu.get("nm", ""),
                    zonas=[str(z) for z in mu.get("z", [])],
                    capital=mu.get("c") == "s",
                )
            )
    return municipios


def parse_secoes(data: dict[str, Any], uf: str, codigo_municipio: str) -> list[ZonaSecoes]:
    uf = uf.lower()
    codigo = f"{int(codigo_municipio):05d}"
    zonas: list[ZonaSecoes] = []
    for abr in data.get("abr", []):
        if str(abr.get("cd", "")).lower() != uf:
            continue
        for mu in abr.get("mu", []):
            if str(mu.get("cd", "")) != codigo:
                continue
            for zon in mu.get("zon", []):
                secoes: list[Secao] = []
                for sec in zon.get("sec", []):
                    secoes.append(
                        Secao(
                            numero=str(sec.get("ns", "")),
                            principal=str(sec.get("nsp")) if sec.get("nsp") else None,
                            agregadas=[str(s) for s in sec.get("nsa", [])],
                            data_aux=sec.get("da"),
                            hora_aux=sec.get("ha"),
                        )
                    )
                zonas.append(ZonaSecoes(zona=str(zon.get("cd", "")), secoes=secoes))
    return zonas


def parse_aux(data: dict[str, Any]) -> tuple[str, int]:
    status = str(data.get("st", "") or "")
    urnas = len(data.get("hashes", []) or [])
    return status, urnas
