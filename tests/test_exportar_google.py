from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET

import pytest

from eleitor.services.exportar_google import (
    CABECALHO_CSV,
    ExportError,
    comparar,
    exportar_google,
    gerar_csv,
    gerar_kml,
)
from eleitor.services.mapa_urnas import construir_payload
from fixtures_planilha import planilha_exemplo

NS = {"k": "http://www.opengis.net/kml/2.2"}


def _payload() -> dict:
    return construir_payload(planilha_exemplo())


def _placemarks(kml: str) -> list[ET.Element]:
    return ET.fromstring(kml).findall(".//k:Placemark", NS)


def test_comparar_resolve_candidatos_e_percentuais():
    comp = comparar(_payload(), "Presidente")

    assert comp.cand_a["nome"] == "CANDIDATO A"
    assert comp.cand_b["nome"] == "CANDIDATO B"
    assert comp.total_a == 70
    assert comp.total_b == 35
    assert comp.pct_a == pytest.approx(70 * 100 / 105)
    assert comp.pct_b == pytest.approx(35 * 100 / 105)
    assert comp.locais_a == 2
    assert comp.locais_b == 0
    assert comp.empates == 0

    primeiro = comp.linhas[0]
    assert primeiro.pct_a == pytest.approx(60 * 100 / 90)
    assert primeiro.pct_b == pytest.approx(30 * 100 / 90)
    assert primeiro.vencedor == "A"
    assert primeiro.faixa == "A forte"
    assert primeiro.top[0]["nome"] == "CANDIDATO A"


def test_comparar_aceita_numeros_e_rejeita_inexistente():
    payload = _payload()
    comp = comparar(payload, "governador", a="45", b="12")
    assert comp.cand_a["nome"] == "GOVERNADOR B"
    assert comp.cand_b["nome"] == "GOVERNADOR A"

    with pytest.raises(ExportError):
        comparar(payload, "Presidente", a="999")


def test_kml_unico_tem_placemarks_estilos_e_baloes():
    kml = gerar_kml(_payload(), ["Presidente"])
    root = ET.fromstring(kml)

    assert len(root.findall(".//k:Placemark", NS)) == 2
    assert len(root.findall(".//k:Folder", NS)) == 0

    cores = [no.text for no in root.findall(".//k:IconStyle/k:color", NS)]
    assert len(cores) == 2
    assert all(len(cor) == 8 and all(ch in "0123456789abcdef" for ch in cor) for cor in cores)

    escalas = [float(no.text) for no in root.findall(".//k:IconStyle/k:scale", NS)]
    assert escalas and all(escala > 0 for escala in escalas)

    descricoes = " ".join(no.text or "" for no in root.findall(".//k:description", NS))
    assert "CANDIDATO A" in descricoes
    assert "CANDIDATO B" in descricoes
    assert "Top 5 no local" in descricoes

    hrefs = [no.text for no in root.findall(".//k:Icon/k:href", NS)]
    assert hrefs and all("placemark_circle.png" in href for href in hrefs)

    dados = {
        no.attrib.get("name"): no.findtext("k:value", default="", namespaces=NS)
        for no in root.findall(".//k:ExtendedData/k:Data", NS)
    }
    assert dados["CandidatoA"] == "CANDIDATO A"
    assert dados["CandidatoB"] == "CANDIDATO B"
    assert dados["Vencedor"] == "A"


def test_kml_todos_tem_pastas_e_so_governador_visivel():
    kml = gerar_kml(_payload())
    root = ET.fromstring(kml)
    folders = root.findall(".//k:Folder", NS)

    assert len(folders) == 2
    assert len(root.findall(".//k:Placemark", NS)) == 4

    visibilidade = {}
    for folder in folders:
        nome = folder.findtext("k:name", default="", namespaces=NS)
        visibilidade[nome] = folder.findtext("k:visibility", default="0", namespaces=NS)

    governador = next(nome for nome in visibilidade if nome.startswith("Governador"))
    presidente = next(nome for nome in visibilidade if nome.startswith("Presidente"))
    assert visibilidade[governador] == "1"
    assert visibilidade[presidente] == "0"


def test_csv_google_my_maps_tem_colunas_e_valores():
    texto = gerar_csv(_payload(), "Presidente")
    linhas = list(csv.reader(io.StringIO(texto)))

    assert linhas[0] == CABECALHO_CSV
    assert len(linhas) == 3

    cabecalho = linhas[0]
    primeira = dict(zip(cabecalho, linhas[1]))
    assert primeira["Local"] == "ESCOLA A"
    assert primeira["Zona"] == "75"
    assert primeira["Codigo"] == "1015"
    assert primeira["Aptos"] == "150"
    assert primeira["Candidato A"] == "CANDIDATO A"
    assert primeira["Votos A"] == "60"
    assert primeira["Percentual A"] == "66.67"
    assert primeira["Votos B"] == "30"
    assert primeira["Vencedor"] == "A"
    assert primeira["Candidato vencedor"] == "CANDIDATO A"
    assert primeira["Faixa"] == "A forte"
    assert primeira["Urnas"] == "2"
    assert "google.com/maps" in primeira["Link Google Maps"]

    segunda = dict(zip(cabecalho, linhas[2]))
    assert segunda["Local"] == "ESCOLA B"
    assert segunda["Votos A"] == "10"
    assert segunda["Votos B"] == "5"


def test_exportar_google_grava_todos_os_arquivos(tmp_path):
    arquivos = exportar_google(_payload(), tmp_path)
    nomes = {arquivo.name for arquivo in arquivos}

    assert len(arquivos) == 5
    assert "mapa_eleitoral_municipio-teste_2026_todos.kml" in nomes
    assert "mapa_eleitoral_municipio-teste_2026_presidente.kml" in nomes
    assert "mapa_eleitoral_municipio-teste_2026_governador.kml" in nomes
    assert "mapa_eleitoral_municipio-teste_2026_presidente_my_maps.csv" in nomes
    assert "mapa_eleitoral_municipio-teste_2026_governador_my_maps.csv" in nomes

    for arquivo in arquivos:
        assert arquivo.stat().st_size > 0
        if arquivo.suffix == ".kml":
            ET.fromstring(arquivo.read_text(encoding="utf-8"))
        else:
            with arquivo.open(encoding="utf-8-sig", newline="") as fh:
                assert next(csv.reader(fh)) == CABECALHO_CSV


def test_exportar_google_cargo_unico_e_validacoes(tmp_path):
    arquivos = exportar_google(
        _payload(), tmp_path / "um", cargo="governador", a="12", b="45"
    )
    assert len(arquivos) == 2
    assert all("governador" in arquivo.name for arquivo in arquivos)

    kml = next(arquivo for arquivo in arquivos if arquivo.suffix == ".kml")
    assert len(_placemarks(kml.read_text(encoding="utf-8"))) == 2

    with pytest.raises(ExportError):
        exportar_google(_payload(), tmp_path / "erro", a="12")
