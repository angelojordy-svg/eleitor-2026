from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pytest

from eleitor.services import financas
from eleitor.sources import contas


# --------------------------------------------------------------------------
# Helpers: monta ZIPs com CSVs mínimos em latin-1
# --------------------------------------------------------------------------


def _zip(caminho: Path, arquivos: dict[str, str]) -> Path:
    with zipfile.ZipFile(caminho, "w") as zf:
        for nome, conteudo in arquivos.items():
            zf.writestr(nome, conteudo.encode("latin-1"))
    return caminho


CADASTRO = (
    "SQ_CANDIDATO;NR_TURNO;NR_CANDIDATO;NM_CANDIDATO;NM_URNA_CANDIDATO;SG_PARTIDO;CD_CARGO;SG_UF;DS_SITUACAO_CANDIDATURA;DS_SIT_TOT_TURNO\n"
    "100;1;20;JOSE DA SILVA;JOSE;PODE;3;PA;#NE;ELEITO\n"
    "200;1;15;MARIA SOUZA;MARIA;MDB;3;PA;#NE;SUPLENTE\n"
    "300;1;10;ANA LIMA;ANA;PT;6;PA;#NE;NÃO ELEITO\n"
    "100;2;20;JOSE DA SILVA;JOSE;PODE;3;PA;#NE;2º TURNO\n"
)

BENS = (
    "SQ_CANDIDATO;VR_BEM_CANDIDATO\n"
    "100;20000,00\n"
    "100;5000,00\n"
    "200;100000,00\n"
)

RECEITAS = (
    "SQ_CANDIDATO;SQ_PRESTADOR_CONTAS;VR_RECEITA;DS_FONTE_RECEITA;DT_GERACAO;HH_GERACAO\n"
    "100;9001;1000,00;FUNDO PARTIDARIO;17/10/2026;07:00:00\n"
    "100;9001;500,00;FUNDO ESPECIAL;17/10/2026;07:00:00\n"
    "100;9001;250,50;OUTROS RECURSOS;17/10/2026;07:00:00\n"
    "200;9002;3000,00;OUTROS RECURSOS;17/10/2026;07:00:00\n"
)

DESPESAS = (
    "SQ_PRESTADOR_CONTAS;VR_PAGTO_DESPESA\n"
    "9001;1200,00\n"
    "9001;300,00\n"
    "9002;2500,00\n"
    "9999;999,00\n"
)


def _fontes(tmp_path: Path) -> dict[str, Path]:
    contas_dir = tmp_path / "contas"
    contas_dir.mkdir()
    return {
        "contas": _zip(
            contas_dir / "contas.zip",
            {"receitas_candidatos_2026_BRASIL.csv": RECEITAS, "despesas_pagas_candidatos_2026_BRASIL.csv": DESPESAS},
        ),
        "cadastro": _zip(contas_dir / "cand.zip", {"consulta_cand_2026_BRASIL.csv": CADASTRO}),
        "bens": _zip(contas_dir / "bens.zip", {"bem_candidato_2026_BRASIL.csv": BENS}),
    }


# --------------------------------------------------------------------------
# Conversão de valores
# --------------------------------------------------------------------------


def test_valor_aceita_virgula_decimal() -> None:
    assert contas._valor("1.234,56") == pytest.approx(1234.56)
    assert contas._valor("30000,00") == pytest.approx(30000.0)
    assert contas._valor("1234.56") == pytest.approx(1234.56)
    assert contas._valor("") == 0.0
    assert contas._valor("abc") == 0.0


# --------------------------------------------------------------------------
# Parsers
# --------------------------------------------------------------------------


def test_parse_cadastro_deduplica_e_prefere_2_turno(tmp_path: Path) -> None:
    caminho = _zip(tmp_path / "cand.zip", {"consulta_cand_2026_BRASIL.csv": CADASTRO})
    registros = contas.parse_cadastro(caminho)

    assert set(registros) == {"100", "200", "300"}
    assert registros["100"]["sit_tot"] == "2º TURNO"  # linha do 2º turno vence
    assert registros["100"]["cargo"] == 3
    assert registros["100"]["nome"] == "JOSE"
    assert registros["200"]["partido"] == "MDB"
    assert "_turno" not in registros["100"]


def test_parse_bens_soma_por_candidato(tmp_path: Path) -> None:
    caminho = _zip(tmp_path / "bens.zip", {"bem_candidato_2026_BRASIL.csv": BENS})
    assert contas.parse_bens(caminho) == {"100": pytest.approx(25000.0), "200": pytest.approx(100000.0)}


def test_parse_bens_prefere_o_arquivo_brasil(tmp_path: Path) -> None:
    conteudo = "SQ_CANDIDATO;VR_BEM_CANDIDATO\n100;20000,00\n"
    outro = "SQ_CANDIDATO;VR_BEM_CANDIDATO\n100;99999,00\n"
    caminho = _zip(
        tmp_path / "bens.zip",
        {"bem_candidato_2026_BRASIL.csv": conteudo, "bem_candidato_2026_PA.csv": outro},
    )
    assert contas.parse_bens(caminho) == {"100": pytest.approx(20000.0)}


def test_parse_receitas_separa_fundos_e_monta_ponte(tmp_path: Path) -> None:
    caminho = _zip(tmp_path / "contas.zip", {"receitas_candidatos_2026_BRASIL.csv": RECEITAS})
    por_cand, ponte, gerado_em = contas.parse_receitas(caminho)

    assert por_cand["100"]["receita"] == pytest.approx(1750.50)
    assert por_cand["100"]["fp"] == pytest.approx(1000.0)
    assert por_cand["100"]["fefc"] == pytest.approx(500.0)
    assert por_cand["200"]["receita"] == pytest.approx(3000.0)
    assert ponte == {"9001": "100", "9002": "200"}
    assert gerado_em == "17/10/2026 07:00:00"


def test_parse_despesas_pagas_usa_ponte_e_ignora_desconhecido(tmp_path: Path) -> None:
    caminho = _zip(tmp_path / "contas.zip", {"despesas_pagas_candidatos_2026_BRASIL.csv": DESPESAS})
    total = contas.parse_despesas_pagas(caminho, {"9001": "100", "9002": "200"})
    assert total == {"100": pytest.approx(1500.0), "200": pytest.approx(2500.0)}
    assert "9999" not in total


# --------------------------------------------------------------------------
# Bake
# --------------------------------------------------------------------------


def test_bake_financas_junta_fontes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ELEITOR_FINANCAS_DIR", str(tmp_path / "fin"))
    dados = financas.bake_financas(caminhos=_fontes(tmp_path))

    assert dados["gerado_em"] == "17/10/2026 07:00:00"
    por_sq = {item["sq"]: item for item in dados["itens"]}
    assert set(por_sq) == {"100", "200"}  # 300 não tem movimento de campanha
    assert dados["total"] == 2

    jose = por_sq["100"]
    assert jose["receita"] == pytest.approx(1750.50)
    assert jose["fundos"] == pytest.approx(1500.0)
    assert jose["fp"] == pytest.approx(1000.0)
    assert jose["fefc"] == pytest.approx(500.0)
    assert jose["gasto"] == pytest.approx(1500.0)
    assert jose["bens"] == pytest.approx(25000.0)
    assert jose["cargo"] == 3
    assert jose["uf"] == "PA"

    # ordenado por gasto desc: MARIA (2500) antes de JOSE (1500)
    assert [item["sq"] for item in dados["itens"]] == ["200", "100"]


def test_bake_reaproveita_cache_das_contas(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ELEITOR_FINANCAS_DIR", str(tmp_path / "fin"))
    fontes = _fontes(tmp_path)

    chamadas = {"n": 0}
    original = contas.parse_receitas
    original_desp = contas.parse_despesas_pagas

    def conta(*a: Any, **k: Any) -> Any:
        chamadas["n"] += 1
        return original(*a, **k)

    monkeypatch.setattr(contas, "parse_receitas", conta)

    financas.bake_financas(caminhos=fontes)
    financas.bake_financas(caminhos=fontes)  # 2ª vez: cache das contas

    assert chamadas["n"] == 1
    assert original_desp is contas.parse_despesas_pagas


def test_bake_recalcula_quando_zip_muda(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ELEITOR_FINANCAS_DIR", str(tmp_path / "fin"))
    fontes = _fontes(tmp_path)
    financas.bake_financas(caminhos=fontes)

    # Reescreve o ZIP de contas (novo tamanho/mtime) e confere que o cache cai.
    novo = RECEITAS + "300;9003;77,00;OUTROS RECURSOS;18/10/2026;00:00:00\n"
    _zip(fontes["contas"], {"receitas_candidatos_2026_BRASIL.csv": novo, "despesas_pagas_candidatos_2026_BRASIL.csv": DESPESAS})

    dados = financas.bake_financas(caminhos=fontes)
    por_sq = {item["sq"]: item for item in dados["itens"]}
    assert "300" in por_sq  # só aparece se o cache das contas foi descartado
    assert por_sq["300"]["receita"] == pytest.approx(77.0)


def test_bake_refazer_ignora_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ELEITOR_FINANCAS_DIR", str(tmp_path / "fin"))
    fontes = _fontes(tmp_path)

    chamadas = {"n": 0}
    original = contas.parse_receitas

    def conta(*a: Any, **k: Any) -> Any:
        chamadas["n"] += 1
        return original(*a, **k)

    monkeypatch.setattr(contas, "parse_receitas", conta)

    financas.bake_financas(caminhos=fontes)
    financas.bake_financas(caminhos=fontes, forcar=True)
    assert chamadas["n"] == 2
