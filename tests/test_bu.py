from pathlib import Path

from eleitor.sources.bu import parse_bu
from eleitor.sources.urna import arquivo_bu, arquivos_urna, url_arquivo_urna

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_bu_v1_exemplo_real():
    raw = (FIXTURES / "exemplo_v1.bu").read_bytes()
    dados = parse_bu(raw)
    assert dados["municipio"] == 1392
    assert dados["zona"] == 9
    assert dados["secao"] == 33
    cargos = dados["cargos"]
    assert 3 in cargos
    governador = cargos[3]
    assert governador["aptos"] == 502
    assert governador["comparecimento"] == 2
    nomes = {v["tipo"] for v in governador["votos"]}
    assert "nominal" in nomes
    nominal = [v for v in governador["votos"] if v["tipo"] == "nominal"]
    assert sum(v["votos"] for v in nominal) == 2


def test_arquivos_urna_formatos_v1_e_v2():
    aux_v1 = {
        "hashes": [
            {
                "hash": "abc",
                "st": "Totalizado",
                "nmarq": ["o003220-05835000750001.logjez", "o003220-05835000750001.bu", "o003220-05835000750001.vscmr"],
            }
        ]
    }
    itens = arquivos_urna(aux_v1)
    assert itens[0]["hash"] == "abc"
    assert arquivo_bu(itens[0]["arquivos"]) == "o003220-05835000750001.bu"

    aux_v2 = {
        "hashes": [
            {
                "hash": "def",
                "st": "Totalizado",
                "arq": [
                    {"nm": "o003220-05835000750001-imgbu.dat", "tp": "imgbu"},
                    {"nm": "o003220-05835000750001-bu.dat", "tp": "bu"},
                ],
            }
        ]
    }
    itens = arquivos_urna(aux_v2)
    assert arquivo_bu(itens[0]["arquivos"]) == "o003220-05835000750001-bu.dat"


def test_url_arquivo_urna():
    url = url_arquivo_urna("pa", "5835", "75", "1", "abc123", "o003220-05835000750001.bu")
    assert url == (
        "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3220/"
        "dados/pa/05835/0075/0001/abc123/o003220-05835000750001.bu"
    )
