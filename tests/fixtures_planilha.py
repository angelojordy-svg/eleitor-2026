"""Planilha mínima compartilhada pelos testes do mapa/exportação."""

from __future__ import annotations

from eleitor.sources.planilha import (
    LocalVotacao,
    PlanilhaBU,
    ResumoUrna,
    Urna,
    Voto,
)


def locais() -> list[LocalVotacao]:
    return [
        LocalVotacao(
            zona="75",
            codigo="1015",
            nome="ESCOLA A",
            endereco="RUA A",
            bairro="CENTRO",
            cep="68515-000",
            latitude=-6.06,
            longitude=-49.90,
            secoes=2,
            aptos=150,
            comparecimento=120,
            abstencoes=30,
        ),
        LocalVotacao(
            zona="106",
            codigo="1015",
            nome="ESCOLA B",
            endereco="RUA B",
            bairro="RIO VERDE",
            cep="68515-000",
            latitude=-6.08,
            longitude=-49.88,
            secoes=1,
            aptos=60,
            comparecimento=48,
            abstencoes=12,
        ),
    ]


def urnas() -> list[Urna]:
    return [
        Urna("75", "1", "1015", "ESCOLA A", "CENTRO", "—", "111", 100, 80, 20, 75),
        Urna("75", "637", "1015", "ESCOLA A", "CENTRO", "723", "222", 50, 40, 10, 37),
        Urna("106", "1", "1015", "ESCOLA B", "RIO VERDE", "—", "333", 60, 48, 12, 15),
    ]


def resumos() -> list[ResumoUrna]:
    pres = [
        (80, 5, 15),
        (40, 2, 8),
        (48, 5, 28),
    ]
    gov = [(80, 0, 20), (40, 0, 10), (48, 0, 33)]
    base = urnas()
    lista: list[ResumoUrna] = []
    for cargo, valores in (("Presidente", pres), ("Governador", gov)):
        for urna, (comp, brancos, nulos) in zip(base, valores):
            lista.append(
                ResumoUrna(
                    zona=urna.zona,
                    secao=urna.secao,
                    codigo=urna.codigo,
                    local=urna.local,
                    agrega=urna.agrega,
                    cargo=cargo,
                    aptos=urna.aptos,
                    comparecimento=comp,
                    abstencoes=urna.aptos - comp,
                    nominais=comp - brancos - nulos,
                    legenda=0,
                    validos=comp - brancos - nulos,
                    brancos=brancos,
                    nulos=nulos,
                    total=comp,
                )
            )
    return lista


def votos() -> list[Voto]:
    dados = [
        ("75", "1", "Presidente", "22", "PL", "CANDIDATO A", 40),
        ("75", "1", "Presidente", "13", "PT", "CANDIDATO B", 20),
        ("75", "637", "Presidente", "22", "PL", "CANDIDATO A", 20),
        ("75", "637", "Presidente", "13", "PT", "CANDIDATO B", 10),
        ("106", "1", "Presidente", "22", "PL", "CANDIDATO A", 10),
        ("106", "1", "Presidente", "13", "PT", "CANDIDATO B", 5),
        ("75", "1", "Governador", "12", "PODE", "GOVERNADOR A", 50),
        ("75", "1", "Governador", "45", "PSOL", "GOVERNADOR B", 10),
        ("75", "637", "Governador", "12", "PODE", "GOVERNADOR A", 25),
        ("75", "637", "Governador", "45", "PSOL", "GOVERNADOR B", 5),
        ("106", "1", "Governador", "12", "PODE", "GOVERNADOR A", 12),
        ("106", "1", "Governador", "45", "PSOL", "GOVERNADOR B", 3),
    ]
    brancos = [
        ("75", "1", "Presidente", "BRANCO", "", "BRANCO", 5),
        ("75", "637", "Presidente", "BRANCO", "", "BRANCO", 2),
        ("106", "1", "Presidente", "BRANCO", "", "BRANCO", 5),
        ("75", "1", "Governador", "BRANCO", "", "BRANCO", 0),
        ("75", "637", "Governador", "BRANCO", "", "BRANCO", 0),
        ("106", "1", "Governador", "BRANCO", "", "BRANCO", 0),
    ]
    nulos = [
        ("75", "1", "Presidente", "NULO", "", "NULO", 15),
        ("75", "637", "Presidente", "NULO", "", "NULO", 8),
        ("106", "1", "Presidente", "NULO", "", "NULO", 28),
        ("75", "1", "Governador", "NULO", "", "NULO", 20),
        ("75", "637", "Governador", "NULO", "", "NULO", 10),
        ("106", "1", "Governador", "NULO", "", "NULO", 33),
    ]
    base = {(urna.zona, urna.secao): urna for urna in urnas()}
    lista: list[Voto] = []
    for zona, secao, cargo, numero, partido, nome, quantidade in dados:
        urna = base[(zona, secao)]
        lista.append(
            Voto(
                zona=zona,
                secao=secao,
                codigo=urna.codigo,
                local=urna.local,
                agrega=urna.agrega,
                cargo=cargo,
                tipo="Nominal",
                numero=numero,
                votavel=nome,
                partido=partido,
                votos=quantidade,
                aptos=urna.aptos,
                comparecimento=urna.comparecimento,
                abstencoes=urna.abstencoes,
            )
        )
    for grupo, tipo in ((brancos, "Branco"), (nulos, "Nulo")):
        for zona, secao, cargo, numero, partido, nome, quantidade in grupo:
            urna = base[(zona, secao)]
            lista.append(
                Voto(
                    zona=zona,
                    secao=secao,
                    codigo=urna.codigo,
                    local=urna.local,
                    agrega=urna.agrega,
                    cargo=cargo,
                    tipo=tipo,
                    numero=numero,
                    votavel=nome,
                    partido=partido,
                    votos=quantidade,
                    aptos=urna.aptos,
                    comparecimento=urna.comparecimento,
                    abstencoes=urna.abstencoes,
                )
            )
    return lista


def meta() -> dict:
    return {
        "municipio": "Município Teste/PA",
        "uf": "PA",
        "codigo_tse": "05835",
        "ibge": "1505536",
        "eleicao": "2026 · Eleições Gerais Estaduais · 1º turno · 04/10/2026",
        "ano": 2026,
        "turno": 1,
        "fonte": "TSE — Boletim de Urna",
        "gerado_tse": "05/10/2026 14:03:43",
        "data_planilha": "23/10/2026",
    }


def planilha_exemplo() -> PlanilhaBU:
    return PlanilhaBU(
        caminho="memoria.xlsx",
        meta=meta(),
        locais=locais(),
        urnas=urnas(),
        resumos=resumos(),
        votos=votos(),
    )
