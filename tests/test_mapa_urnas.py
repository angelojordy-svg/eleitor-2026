from __future__ import annotations

from dataclasses import replace

import pytest

from eleitor.render.html import render_mapa_urnas
from eleitor.services.mapa_urnas import (
    conferir_planilha,
    construir_payload,
    nome_arquivo,
)
from eleitor.sources.planilha import (
    LocalVotacao,
    PlanilhaBU,
    PlanilhaError,
    ResumoUrna,
    Urna,
    Voto,
    ler_planilha,
)


def _locais() -> list[LocalVotacao]:
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


def _urnas() -> list[Urna]:
    return [
        Urna("75", "1", "1015", "ESCOLA A", "CENTRO", "—", "111", 100, 80, 20, 75),
        Urna("75", "637", "1015", "ESCOLA A", "CENTRO", "723", "222", 50, 40, 10, 37),
        Urna("106", "1", "1015", "ESCOLA B", "RIO VERDE", "—", "333", 60, 48, 12, 15),
    ]


def _resumos() -> list[ResumoUrna]:
    # (zona, seção, aptos, comp, nominal, brancos, nulos) por cargo
    pres = [
        (80, 5, 15),   # urna 1: 60 nominais + 5 + 15 = 80
        (40, 2, 8),    # urna 2: 30 + 2 + 8 = 40
        (48, 5, 28),   # urna 3: 15 + 5 + 28 = 48
    ]
    gov = [(80, 0, 20), (40, 0, 10), (48, 0, 33)]
    base = _urnas()
    resumos: list[ResumoUrna] = []
    for cargo, valores in (("Presidente", pres), ("Governador", gov)):
        for urna, (comp, brancos, nulos) in zip(base, valores):
            resumos.append(
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
    return resumos


def _votos() -> list[Voto]:
    # (zona, seção, cargo, votável, partido, votos)
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

    base = {(u.zona, u.secao): u for u in _urnas()}
    votos: list[Voto] = []
    for zona, secao, cargo, numero, partido, nome, quantidade in dados:
        urna = base[(zona, secao)]
        votos.append(
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
    for lista, tipo in ((brancos, "Branco"), (nulos, "Nulo")):
        for zona, secao, cargo, numero, partido, nome, quantidade in lista:
            urna = base[(zona, secao)]
            votos.append(
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
    return votos


def _meta() -> dict:
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


def _planilha() -> PlanilhaBU:
    return PlanilhaBU(
        caminho="memoria.xlsx",
        meta=_meta(),
        locais=_locais(),
        urnas=_urnas(),
        resumos=_resumos(),
        votos=_votos(),
    )


def test_agrega_por_local_e_mantem_zonas_separadas():
    payload = construir_payload(_planilha())

    assert [l["zona"] for l in payload["locais"]] == ["75", "106"]
    assert [l["codigo"] for l in payload["locais"]] == ["1015", "1015"]
    assert len(payload["locais"][0]["urnas"]) == 2
    assert len(payload["locais"][1]["urnas"]) == 1
    assert payload["meta"]["total_locais"] == 2
    assert payload["meta"]["total_urnas"] == 3
    assert payload["meta"]["total_aptos"] == 210


def test_matriz_de_votos_e_ordenacao_dos_candidatos():
    payload = construir_payload(_planilha())
    presidente = payload["cargos"][0]

    assert presidente["nome"] == "Presidente"
    assert [c["nome"] for c in presidente["cands"]] == ["CANDIDATO A", "CANDIDATO B"]
    assert [c["total"] for c in presidente["cands"]] == [70, 35]
    assert presidente["votos"][0] == [60, 30]
    assert presidente["votos"][1] == [10, 5]
    assert presidente["validos"] == [90, 15]
    assert presidente["brancos"] == [7, 5]
    assert presidente["nulos"] == [23, 28]
    assert presidente["totais"]["validos"] == 105
    assert presidente["totais"]["brancos"] == 12
    assert presidente["totais"]["nulos"] == 51


def test_conferencia_nao_acusa_erro_nos_totais():
    assert conferir_planilha(_planilha()) == []


def test_conferencia_acusa_divergencia():
    planilha = _planilha()
    planilha.resumos[0] = replace(planilha.resumos[0], nominais=999)
    avisos = conferir_planilha(planilha)
    assert any("nominais" in aviso for aviso in avisos)


def test_conferencia_acusa_voto_fora_do_cadastro():
    planilha = _planilha()
    planilha.votos.append(replace(planilha.votos[0], codigo="9999", votos=7))
    avisos = conferir_planilha(planilha)
    assert any("fora do cadastro" in aviso for aviso in avisos)


def test_html_escapa_payload_e_inclui_mapa():
    planilha = _planilha()
    planilha.locais[0] = replace(planilha.locais[0], nome="</script><b>escola</b>")
    payload = construir_payload(planilha)
    html = render_mapa_urnas(payload)

    assert "\\u003c/script>" in html
    assert "</script><b>escola</b>" not in html
    assert "leaflet" in html
    assert "DADOS" in html
    assert "unpkg.com/leaflet" not in html
    assert "basemaps.cartocdn.com" not in html
    assert "tile.openstreetmap.org" not in html
    assert "World_Street_Map" in html
    assert "const FUNDO = null;" in html
    assert 'id="sel-base"' in html


def test_html_com_fundo_offline():
    payload = construir_payload(_planilha())
    fundo = {
        "baixo": {
            "url": "data:image/jpeg;base64,AAAA",
            "bounds": [[-6.2, -50.9], [-5.9, -49.8]],
        },
        "alto": None,
        "attr": "© OpenStreetMap contributors",
    }
    html = render_mapa_urnas(payload, fundo=fundo)

    assert "const FUNDO = {" in html
    assert "data:image/jpeg;base64,AAAA" in html
    assert 'value="offline"' in html


def test_nome_arquivo_sem_acento():
    assert (
        nome_arquivo({"municipio": "São Félix do Xingu/PA", "ano": 2026})
        == "mapa_eleitoral_sao-felix-do-xingu_2026.html"
    )


def test_le_planilha_xlsx_completa(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from openpyxl import Workbook

    wb = Workbook()
    leia = wb.active
    leia.title = "Leia-me"
    for chave, valor in (
        ("Município", "Município Teste/PA"),
        ("Código TSE / IBGE", "05835 / 1505536"),
        ("Eleição", "2026 · Eleições Gerais Estaduais · 1º turno · 04/10/2026"),
        ("Fonte", "TSE — Boletim de Urna"),
        ("Geração do arquivo do TSE", "05/10/2026 14:03:43"),
        ("Data desta planilha", "23/10/2026"),
    ):
        leia.append([chave, valor])

    locais = wb.create_sheet("Locais de votação")
    locais.append(["LOCAIS"])
    locais.append(["Zona", "Código", "Local de votação", "Endereço", "Bairro", "CEP",
                   "Latitude", "Longitude", "Seções", "Aptos", "Comparecimento", "Abstenções"])
    for local in _locais():
        locais.append([
            local.zona, local.codigo, local.nome, local.endereco, local.bairro, local.cep,
            local.latitude, local.longitude, local.secoes, local.aptos,
            local.comparecimento, local.abstencoes,
        ])

    urnas = wb.create_sheet("Índice das urnas")
    urnas.append(["URNAS"])
    urnas.append(["Zona", "Seção", "Cód. local", "Local de votação", "Bairro", "Agrega",
                  "Urna", "Aptos", "Comparecimento", "Abstenções", "Válidos (Gov.)"])
    for urna in _urnas():
        urnas.append([
            urna.zona, urna.secao, urna.codigo, urna.local, urna.bairro, urna.agrega,
            urna.identificacao, urna.aptos, urna.comparecimento, urna.abstencoes,
            urna.validos_gov,
        ])

    resumos = wb.create_sheet("Resumo por urna")
    resumos.append(["RESUMO"])
    resumos.append(["Zona", "Seção", "Cód. local", "Local de votação", "Agrega", "Cargo",
                    "Aptos", "Comparecimento", "Abstenções", "% Comp.", "Nominais",
                    "Legenda", "Válidos", "Brancos", "Nulos", "Total de votos"])
    for resumo in _resumos():
        resumos.append([
            resumo.zona, resumo.secao, resumo.codigo, resumo.local, resumo.agrega,
            resumo.cargo, resumo.aptos, resumo.comparecimento, resumo.abstencoes,
            0.0, resumo.nominais, resumo.legenda, resumo.validos, resumo.brancos,
            resumo.nulos, resumo.total,
        ])

    dados = wb.create_sheet("Dados completos")
    dados.append(["DADOS"])
    dados.append(["Zona", "Seção", "Cód. local", "Local de votação", "Agrega", "Cargo",
                  "Tipo", "Nº", "Votável", "Partido", "Votos", "Aptos",
                  "Comparecimento", "Abstenções"])
    for voto in _votos():
        dados.append([
            voto.zona, voto.secao, voto.codigo, voto.local, voto.agrega, voto.cargo,
            voto.tipo, voto.numero, voto.votavel, voto.partido, voto.votos,
            voto.aptos, voto.comparecimento, voto.abstencoes,
        ])

    destino = tmp_path / "planilha.xlsx"
    wb.save(destino)

    planilha = ler_planilha(destino)
    assert len(planilha.locais) == 2
    assert len(planilha.urnas) == 3
    assert len(planilha.resumos) == 6
    assert len(planilha.votos) == 24
    assert planilha.meta["municipio"] == "Município Teste/PA"
    assert planilha.meta["uf"] == "PA"
    assert planilha.meta["codigo_tse"] == "05835"
    assert planilha.meta["ibge"] == "1505536"
    assert planilha.meta["turno"] == 1
    assert planilha.locais[0].latitude == pytest.approx(-6.06)
    assert conferir_planilha(planilha) == []


def test_planilha_inexistente():
    with pytest.raises(PlanilhaError):
        ler_planilha("nao-existe.xlsx")
