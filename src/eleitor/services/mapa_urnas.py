"""Agrega a planilha de BUs no payload do mapa eleitoral por local.

O mapa mostra um círculo por **local de votação** (as urnas do mesmo local são
somadas). A comparação é sempre entre dois candidatos do mesmo cargo, então o
payload guarda a matriz ``votos[local][candidato]`` de cada cargo.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from eleitor.sources.planilha import PlanilhaBU

CARGOS_ORDEM = (
    "Presidente",
    "Governador",
    "Senador",
    "Deputado Federal",
    "Deputado Estadual",
    "Deputado Distrital",
    "Conselheiro Distrital",
)


def _slug(texto: Any) -> str:
    bruto = unicodedata.normalize("NFKD", str(texto or ""))
    sem_acento = "".join(c for c in bruto if not unicodedata.combining(c))
    return "".join(c if c.isalnum() else "-" for c in sem_acento.lower()).strip("-")


def _chave_local(zona: str, codigo: str) -> tuple[str, str]:
    return (zona.zfill(2), codigo.zfill(4))


def _ordenar_cargos(nomes: list[str]) -> list[str]:
    indice = {_slug(nome): posicao for posicao, nome in enumerate(CARGOS_ORDEM)}
    return sorted(
        nomes,
        key=lambda nome: (indice.get(_slug(nome), len(CARGOS_ORDEM)), nome.lower()),
    )


def _votos_por_eleitor(cargo: str) -> int:
    return 2 if _slug(cargo) == "senador" else 1


def construir_payload(
    planilha: PlanilhaBU, gerado_em: datetime | None = None
) -> dict[str, Any]:
    """Monta o dicionário embutido no HTML (JSON compacto)."""

    locais = sorted(
        planilha.locais, key=lambda l: (int(l.zona or 0), int(l.codigo or 0), l.nome)
    )
    indice = {_chave_local(l.zona, l.codigo): i for i, l in enumerate(locais)}

    urnas_por_local: dict[int, list[Any]] = defaultdict(list)
    for urna in planilha.urnas:
        posicao = indice.get(_chave_local(urna.zona, urna.codigo))
        if posicao is not None:
            urnas_por_local[posicao].append(urna)

    locais_payload: list[dict[str, Any]] = []
    for posicao, local in enumerate(locais):
        urnas = sorted(
            urnas_por_local.get(posicao, []),
            key=lambda u: (int(u.secao or 0), u.identificacao),
        )
        locais_payload.append(
            {
                "zona": local.zona,
                "codigo": local.codigo,
                "nome": local.nome,
                "endereco": local.endereco,
                "bairro": local.bairro,
                "cep": local.cep,
                "lat": round(local.latitude, 7),
                "lon": round(local.longitude, 7),
                "secoes": local.secoes,
                "aptos": local.aptos,
                "comp": local.comparecimento,
                "abst": local.abstencoes,
                "urnas": [
                    {
                        "secao": urna.secao,
                        "urna": urna.identificacao,
                        "agrega": urna.agrega,
                        "aptos": urna.aptos,
                        "comp": urna.comparecimento,
                        "abst": urna.abstencoes,
                    }
                    for urna in urnas
                ],
            }
        )

    cargos_presentes = _ordenar_cargos(
        list({resumo.cargo for resumo in planilha.resumos if resumo.cargo})
    )

    cargos_payload: list[dict[str, Any]] = []
    for cargo in cargos_presentes:
        resumos = [r for r in planilha.resumos if r.cargo == cargo]
        if not resumos:
            continue

        n_locais = len(locais)
        aptos = [0] * n_locais
        comp = [0] * n_locais
        abst = [0] * n_locais
        validos = [0] * n_locais
        brancos = [0] * n_locais
        nulos = [0] * n_locais
        total = [0] * n_locais
        nominais = [0] * n_locais
        legenda = [0] * n_locais

        for resumo in resumos:
            posicao = indice.get(_chave_local(resumo.zona, resumo.codigo))
            if posicao is None:
                continue
            aptos[posicao] += resumo.aptos
            comp[posicao] += resumo.comparecimento
            abst[posicao] += resumo.abstencoes
            validos[posicao] += resumo.validos
            brancos[posicao] += resumo.brancos
            nulos[posicao] += resumo.nulos
            total[posicao] += resumo.total
            nominais[posicao] += resumo.nominais
            legenda[posicao] += resumo.legenda

        # Candidato -> votos por local. Só nominal: legenda é voto de partido.
        votos_por_cand: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        dados_cand: dict[str, dict[str, str]] = {}
        for voto in planilha.votos:
            if voto.cargo != cargo or _slug(voto.tipo) != "nominal" or voto.votos <= 0:
                continue
            posicao = indice.get(_chave_local(voto.zona, voto.codigo))
            if posicao is None:
                continue
            chave = voto.numero or voto.votavel
            votos_por_cand[chave][posicao] += voto.votos
            dados_cand.setdefault(
                chave,
                {"n": voto.numero, "nome": voto.votavel, "p": voto.partido},
            )

        candidatos = sorted(
            (
                {
                    "n": dados_cand[chave].get("n", ""),
                    "nome": dados_cand[chave].get("nome", ""),
                    "p": dados_cand[chave].get("p", ""),
                    "total": sum(por_local.values()),
                }
                for chave, por_local in votos_por_cand.items()
            ),
            key=lambda c: (-c["total"], c["nome"].lower()),
        )
        chaves_ordenadas = sorted(
            votos_por_cand,
            key=lambda chave: (
                -sum(votos_por_cand[chave].values()),
                dados_cand[chave].get("nome", "").lower(),
            ),
        )
        matriz = [
            [votos_por_cand[chave].get(posicao, 0) for chave in chaves_ordenadas]
            for posicao in range(n_locais)
        ]

        cargos_payload.append(
            {
                "id": _slug(cargo),
                "nome": cargo,
                "votos_por_eleitor": _votos_por_eleitor(cargo),
                "cands": candidatos,
                "votos": matriz,
                "aptos": aptos,
                "comp": comp,
                "abst": abst,
                "validos": validos,
                "brancos": brancos,
                "nulos": nulos,
                "total": total,
                "nominais": nominais,
                "legenda": legenda,
                "totais": {
                    "aptos": sum(aptos),
                    "comp": sum(comp),
                    "abst": sum(abst),
                    "validos": sum(validos),
                    "brancos": sum(brancos),
                    "nulos": sum(nulos),
                    "total": sum(total),
                    "nominais": sum(nominais),
                    "legenda": sum(legenda),
                    "candidatos": len(candidatos),
                },
            }
        )

    momento = gerado_em or datetime.now(timezone.utc)
    meta = dict(planilha.meta)
    meta.update(
        {
            "gerado_em": momento.isoformat(timespec="seconds"),
            "total_locais": len(locais_payload),
            "total_urnas": sum(len(local["urnas"]) for local in locais_payload),
            "total_aptos": sum(local["aptos"] for local in locais_payload),
            "total_cargos": len(cargos_payload),
        }
    )
    return {"meta": meta, "locais": locais_payload, "cargos": cargos_payload}


def conferir_planilha(planilha: PlanilhaBU) -> list[str]:
    """Confere os totais do resumo contra as linhas de votos (BU).

    Devolve avisos legíveis; lista vazia = tudo bateu. É a rede de segurança
    contra dupla contagem (seção agregada) e contra leitura de coluna errada.
    """

    avisos: list[str] = []
    chaves = [_chave_local(local.zona, local.codigo) for local in planilha.locais]
    chaves_locais = set(chaves)
    if len(chaves_locais) != len(chaves):
        avisos.append("Há locais duplicados (mesma zona + código) na aba de locais.")
    sem_cadastro = [
        urna for urna in planilha.urnas
        if _chave_local(urna.zona, urna.codigo) not in chaves_locais
    ]
    if sem_cadastro:
        urna = sem_cadastro[0]
        avisos.append(
            f"{len(sem_cadastro)} urna(s) apontam para local fora do cadastro "
            f"(ex.: zona {urna.zona}, local {urna.codigo})."
        )

    cargos = _ordenar_cargos(list({r.cargo for r in planilha.resumos if r.cargo}))
    for cargo in cargos:
        resumos = [r for r in planilha.resumos if r.cargo == cargo]
        votos = [v for v in planilha.votos if v.cargo == cargo]

        r_nom = sum(r.nominais for r in resumos)
        r_leg = sum(r.legenda for r in resumos)
        r_val = sum(r.validos for r in resumos)
        r_bran = sum(r.brancos for r in resumos)
        r_nul = sum(r.nulos for r in resumos)
        r_total = sum(r.total for r in resumos)

        v_nom = sum(v.votos for v in votos if _slug(v.tipo) == "nominal")
        v_leg = sum(v.votos for v in votos if _slug(v.tipo) == "legenda")
        v_bran = sum(v.votos for v in votos if _slug(v.tipo) == "branco")
        v_nul = sum(v.votos for v in votos if _slug(v.tipo) == "nulo")
        v_nom_local = sum(
            v.votos
            for v in votos
            if _slug(v.tipo) == "nominal"
            and _chave_local(v.zona, v.codigo) in chaves_locais
        )
        if v_nom != v_nom_local:
            avisos.append(
                f"{cargo}: {v_nom - v_nom_local} voto(s) nominal(is) em local "
                "fora do cadastro de locais."
            )

        if r_nom != v_nom:
            avisos.append(
                f"{cargo}: nominais do resumo ({r_nom}) != votos nominais ({v_nom})."
            )
        if r_leg != v_leg:
            avisos.append(
                f"{cargo}: legenda do resumo ({r_leg}) != votos de legenda ({v_leg})."
            )
        if r_val != r_nom + r_leg:
            avisos.append(
                f"{cargo}: válidos ({r_val}) != nominais + legenda ({r_nom + r_leg})."
            )
        if r_total != r_val + r_bran + r_nul:
            avisos.append(
                f"{cargo}: total ({r_total}) != válidos + brancos + nulos "
                f"({r_val + r_bran + r_nul})."
            )
        if r_bran != v_bran:
            avisos.append(f"{cargo}: brancos do resumo ({r_bran}) != BU ({v_bran}).")
        if r_nul != v_nul:
            avisos.append(f"{cargo}: nulos do resumo ({r_nul}) != BU ({v_nul}).")

    aptos_check = sum(local.aptos for local in planilha.locais)
    if planilha.urnas:
        urnas_check = sum(urna.aptos for urna in planilha.urnas)
        if urnas_check and urnas_check != aptos_check:
            avisos.append(
                f"Aptos dos locais ({aptos_check}) != soma das urnas ({urnas_check})."
            )
    return avisos


def nome_arquivo(meta: dict[str, Any]) -> str:
    """Nome padrão do HTML: mapa_eleitoral_<municipio>_<ano>.html."""

    municipio = str(meta.get("municipio") or "municipio").split("/")[0].strip()
    ano = meta.get("ano") or 2026
    return f"mapa_eleitoral_{_slug(municipio)}_{ano}.html"
