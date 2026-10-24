from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from eleitor.render.focado import render_focado
from eleitor.render.html import render_correlacao
from eleitor.services.correlacao import (
    _correlacao_ponderada,
    _goodman_ols,
    _residuos_local,
    _residuos_sobre_z,
    analisar_correlacoes,
    analisar_covotacao,
    analisar_pares_focados,
    bh_fdr,
    construir_dados,
    escrever_correlacao_csv,
    escrever_covotacao_csv,
    escrever_focado_benchmark_csv,
    escrever_focado_csv,
    escrever_focado_locais_csv,
    escrever_matriz_csv,
    ler_pares_arquivo,
    limites_covotacao,
    montar_payload_focado,
    montar_relatorio,
    parse_par,
    parse_pares_texto,
    resolver_pares,
    resumo_covotacao,
    selecionar,
    texto_template_pares,
)
from eleitor.services.mapa_urnas import conferir_planilha
from eleitor.sources.planilha import (
    LocalVotacao,
    PlanilhaBU,
    ResumoUrna,
    Urna,
    Voto,
    ler_planilha,
)

XLSX = Path("In Put") / "boletim_urna_parauapebas_2026_z75_z106_com_locais.xlsx"


def _planilha() -> PlanilhaBU:
    locais: list[LocalVotacao] = []
    urnas: list[Urna] = []
    resumos: list[ResumoUrna] = []
    votos: list[Voto] = []

    bases_gov = [40, 55, 70]
    bases_sen = [35, 55, 75]
    desvios = [-10, -6, -2, 2, 6, 10]
    ruido_sen = [1, -1, 1, -1, 1, -1]

    secao = 0
    for local_pos, codigo in enumerate(("1015", "1016", "1017")):
        locais.append(
            LocalVotacao(
                zona="75",
                codigo=codigo,
                nome=f"LOCAL {codigo}",
                endereco="RUA",
                bairro="BAIRRO",
                cep="00000-000",
                latitude=-6.0,
                longitude=-49.0,
                secoes=6,
                aptos=600,
                comparecimento=600,
                abstencoes=0,
            )
        )
        for posicao in range(6):
            secao += 1
            numero_secao = str(secao)
            urnas.append(
                Urna(
                    zona="75",
                    secao=numero_secao,
                    codigo=codigo,
                    local=f"LOCAL {codigo}",
                    bairro="BAIRRO",
                    agrega="—",
                    identificacao=f"75{secao:04d}",
                    aptos=100,
                    comparecimento=100,
                    abstencoes=0,
                    validos_gov=90,
                )
            )
            gov_a = bases_gov[local_pos] + desvios[posicao]
            gov_b = 90 - gov_a
            sen_a = bases_sen[local_pos] + desvios[posicao] + ruido_sen[posicao]
            sen_b = 90 - sen_a

            for cargo in ("Governador", "Senador"):
                resumos.append(
                    ResumoUrna(
                        zona="75",
                        secao=numero_secao,
                        codigo=codigo,
                        local=f"LOCAL {codigo}",
                        agrega="—",
                        cargo=cargo,
                        aptos=100,
                        comparecimento=100,
                        abstencoes=0,
                        nominais=90,
                        legenda=0,
                        validos=90,
                        brancos=5,
                        nulos=5,
                        total=100,
                    )
                )
                for numero, nome, partido, quantidade, tipo in (
                    ("20", "GOV A", "P", gov_a, "Nominal"),
                    ("30", "GOV B", "Q", gov_b, "Nominal"),
                    ("200", "SEN A", "R", sen_a, "Nominal"),
                    ("300", "SEN B", "S", sen_b, "Nominal"),
                    ("BRANCO", "BRANCO", "", 5, "Branco"),
                    ("NULO", "NULO", "", 5, "Nulo"),
                ):
                    if cargo == "Senador" and numero in {"20", "30"}:
                        continue
                    if cargo == "Governador" and numero in {"200", "300"}:
                        continue
                    votos.append(
                        Voto(
                            zona="75",
                            secao=numero_secao,
                            codigo=codigo,
                            local=f"LOCAL {codigo}",
                            agrega="—",
                            cargo=cargo,
                            tipo=tipo,
                            numero=numero,
                            votavel=nome,
                            partido=partido,
                            votos=quantidade,
                            aptos=100,
                            comparecimento=100,
                            abstencoes=0,
                        )
                    )

    return PlanilhaBU(
        caminho=Path("memoria.xlsx"),
        meta={"municipio": "Município Teste/PA", "ano": 2026, "turno": 1},
        locais=locais,
        urnas=urnas,
        resumos=resumos,
        votos=votos,
    )


def _par(pares, cargo_a, numero_a, cargo_b, numero_b):
    for par in pares:
        if (
            par.a.cargo == cargo_a
            and par.a.numero == numero_a
            and par.b.cargo == cargo_b
            and par.b.numero == numero_b
        ):
            return par
        if (
            par.a.cargo == cargo_b
            and par.a.numero == numero_b
            and par.b.cargo == cargo_a
            and par.b.numero == numero_a
        ):
            return par
    raise AssertionError(f"par não encontrado: {cargo_a} {numero_a} x {cargo_b} {numero_b}")


def test_construir_dados_e_conferencia():
    planilha = _planilha()
    assert conferir_planilha(planilha) == []

    dados = construir_dados(planilha)
    assert dados.n_urnas == 18
    assert dados.n_locais == 3
    assert len(dados.candidatos) == 4
    assert int(dados.comparecimento.sum()) == 1800
    assert dados.votos.shape == (18, 4)
    assert all(cand.total > 0 for cand in dados.candidatos)
    assert dados.agregadas == []


def test_selecionar_por_massa_e_cobertura():
    dados = construir_dados(_planilha())
    todos = selecionar(dados, min_votos=0, min_cobertura=0)
    assert len(todos) == 4

    so_maiores = selecionar(dados, min_votos=0.5, min_cobertura=0)
    assert len(so_maiores) == 2

    dados.candidatos[1] = replace(dados.candidatos[1], cobertura=0.5)
    filtrados = selecionar(dados, min_votos=0, min_cobertura=0.9)
    assert len(filtrados) == 3


def test_correlacao_pipeline_e_fechamento_composicional():
    dados = construir_dados(_planilha())
    indices = selecionar(dados, min_votos=0, min_cobertura=0)
    resultado = analisar_correlacoes(
        dados, indices, metodo_bloco="none", bootstrap_top=0
    )

    assert resultado.r_bruto.shape == (4, 4)
    assert resultado.r_dentro.shape == (4, 4)
    assert len(resultado.pares) == 6
    for k in range(4):
        assert resultado.r_dentro[k, k] == pytest.approx(1.0)

    par_cruzado = _par(resultado.pares, "Governador", "20", "Senador", "200")
    assert par_cruzado.r_dentro > 0.8
    assert par_cruzado.r_bruto > 0.8

    par_mesmo_cargo = _par(resultado.pares, "Governador", "20", "Governador", "30")
    assert par_mesmo_cargo.tipo_par == "mesmo_cargo"
    assert par_mesmo_cargo.r_bruto == pytest.approx(-1.0, abs=1e-6)
    assert par_mesmo_cargo.flag == "substituto"


def test_within_local_remove_confundidor_territorial():
    locais = np.repeat(np.arange(3), 6)
    pesos = np.ones(18)
    base = np.repeat([0.0, 10.0, 20.0], 6)
    dentro_x = np.tile([-1.0, 0.0, 1.0, -1.0, 0.0, 1.0], 3)
    dentro_y = np.tile([1.0, -1.0, 0.0, -1.0, 1.0, 0.0], 3)
    X = np.column_stack([base + dentro_x, base + dentro_y])

    bruto = _correlacao_ponderada(X, pesos)
    residuos = _residuos_local(X, pesos, locais)
    dentro = _correlacao_ponderada(residuos, pesos)

    assert bruto[0, 1] > 0.9
    assert abs(dentro[0, 1]) < 0.1


def test_residuos_sobre_z_remove_componente_comum():
    rng = np.random.default_rng(7)
    z = rng.normal(size=200)
    z = z - z.mean()
    X = np.column_stack([2.0 * z + rng.normal(scale=0.1, size=200), -z + rng.normal(scale=0.1, size=200)])
    residuos = _residuos_sobre_z(X, z, np.ones(200))
    resto = _correlacao_ponderada(residuos, np.ones(200))
    assert abs(resto[0, 1]) < 0.2
    assert abs(np.corrcoef(residuos[:, 0], z)[0, 1]) < 1e-10


def test_limites_covotacao():
    assert limites_covotacao(100, 100, 1000) == (0, 100)
    assert limites_covotacao(900, 900, 1000) == (800, 900)
    assert limites_covotacao(1700, 1700, 1800) == (1600, 1700)
    assert limites_covotacao(0, 100, 1000) == (0, 0)
    assert limites_covotacao(100, 100, 0) == (0, 0)


def test_covotacao_pipeline_e_pares_permitidos():
    dados = construir_dados(_planilha())
    indices = selecionar(dados, min_votos=0, min_cobertura=0)
    pares = analisar_covotacao(dados, indices, goodman_top=0)

    assert resumo_covotacao(pares)["total"] > 0
    for par in pares:
        assert not (
            par.a.cargo == par.b.cargo and par.a.cargo != "Senador"
        ), "voto único no mesmo cargo não admite co-votação"
        assert 0 <= par.limite_inf <= par.limite_sup <= min(par.a_votos, par.b_votos)
        assert 0 <= par.p_b_dado_a_inf <= par.p_b_dado_a_sup <= 1
        assert 0 <= par.p_a_dado_b_inf <= par.p_a_dado_b_sup <= 1

    assert any(par.a.cargo == par.b.cargo == "Senador" for par in pares)
    par = _par(pares, "Governador", "20", "Senador", "200")
    a_votos = sum(
        v.votos
        for v in _planilha().votos
        if v.cargo == "Governador" and v.numero == "20" and v.tipo == "Nominal"
    )
    b_votos = sum(
        v.votos
        for v in _planilha().votos
        if v.cargo == "Senador" and v.numero == "200" and v.tipo == "Nominal"
    )
    esperado = limites_covotacao(a_votos, b_votos, 1800)
    assert (par.limite_inf, par.limite_sup) == esperado


def test_goodman_recupera_reta():
    x = np.linspace(0.05, 0.9, 20)
    y = 0.2 + 0.5 * x
    ajuste = _goodman_ols(x, y, np.ones_like(x))
    assert ajuste is not None
    alpha, beta = ajuste
    assert alpha == pytest.approx(0.2)
    assert beta == pytest.approx(0.5)


def test_bh_fdr():
    q = bh_fdr([0.01, 0.04, 0.03, 0.5])
    assert q[0] == pytest.approx(0.04)
    assert q[1] == pytest.approx(0.04 * 4 / 3, abs=1e-4)
    assert q[2] == pytest.approx(0.04 * 4 / 3, abs=1e-4)
    assert q[3] == pytest.approx(0.5)

    q_nan = bh_fdr([0.01, float("nan"), 0.5])
    assert np.isfinite(q_nan[0])
    assert q_nan[1] == 1.0
    assert np.isfinite(q_nan[2])


def test_csvs(tmp_path):
    dados = construir_dados(_planilha())
    indices = selecionar(dados, min_votos=0, min_cobertura=0)
    resultado = analisar_correlacoes(
        dados, indices, metodo_bloco="none", bootstrap_top=0
    )
    pares = analisar_covotacao(dados, indices, goodman_top=0)

    corr = tmp_path / "corr.csv"
    matriz = tmp_path / "matriz.csv"
    covot = tmp_path / "covot.csv"
    escrever_correlacao_csv(resultado, corr)
    escrever_matriz_csv(resultado, matriz)
    escrever_covotacao_csv(pares, covot)

    with corr.open(encoding="utf-8-sig", newline="") as arquivo:
        linhas = list(csv.DictReader(arquivo, delimiter=";"))
    assert len(linhas) == 6
    assert "r_dentro" in linhas[0]
    assert "q_bloco" in linhas[0]

    with matriz.open(encoding="utf-8-sig", newline="") as arquivo:
        grade = list(csv.reader(arquivo, delimiter=";"))
    assert len(grade) == 5
    assert len(grade[0]) == 5

    with covot.open(encoding="utf-8-sig", newline="") as arquivo:
        linhas_cov = list(csv.DictReader(arquivo, delimiter=";"))
    assert linhas_cov
    assert "limite_inf" in linhas_cov[0]


def test_relatorio_html_escapa_payload():
    dados = construir_dados(_planilha())
    indices = selecionar(dados, min_votos=0, min_cobertura=0)
    resultado = analisar_correlacoes(
        dados, indices, metodo_bloco="none", bootstrap_top=0
    )
    pares = analisar_covotacao(dados, indices, goodman_top=0)
    payload = montar_relatorio(dados, resultado, pares)
    payload["meta"]["municipio"] = "</script><b>município</b>"

    html = render_correlacao(payload)
    assert "Correlação ecológica" in html
    assert "matriz_bloco" in html
    assert "\\u003c/script>" in html
    assert "</script><b>município</b>" not in html


def test_parse_e_leitura_de_pares(tmp_path):
    assert parse_par(
        "Deputado Federal:2200 ; Deputado Estadual:22100"
    ) == (
        ("Deputado Federal", "2200"),
        ("Deputado Estadual", "22100"),
    )
    pares = parse_pares_texto("A:1;B:2|C:3;D:4")
    assert len(pares) == 2
    with pytest.raises(ValueError):
        parse_par("só um lado")
    with pytest.raises(ValueError):
        parse_par("A:1;B:2;C:3")

    arquivo = tmp_path / "pares.txt"
    arquivo.write_text(
        "# comentário\n\nGovernador:20 ; Senador:200\n# outra linha\n",
        encoding="utf-8",
    )
    lidos = ler_pares_arquivo(arquivo)
    assert lidos == [(("Governador", "20"), ("Senador", "200"))]

    template = texto_template_pares()
    assert "Cargo:numero" in template
    assert "Deputado Federal:2200" in template


def test_resolver_pares_e_validacoes():
    dados = construir_dados(_planilha())
    pares = resolver_pares(
        dados, [(("Governador", "20"), ("Senador", "200"))]
    )
    assert len(pares) == 1
    i, j = pares[0]
    assert dados.candidatos[i].cargo == "Governador"
    assert dados.candidatos[j].cargo == "Senador"

    assert (
        resolver_pares(
            dados,
            [
                (("Governador", "20"), ("Senador", "200")),
                (("Senador", "200"), ("Governador", "20")),
            ],
        )
        == pares
    )

    with pytest.raises(ValueError):
        resolver_pares(
            dados, [(("Governador", "20"), ("Governador", "30"))]
        )
    with pytest.raises(ValueError):
        resolver_pares(
            dados, [(("Governador", "999"), ("Senador", "200"))]
        )


def test_focado_pipeline_sintetico():
    dados = construir_dados(_planilha())
    indices = selecionar(dados, min_votos=0, min_cobertura=0)
    resultado = analisar_correlacoes(
        dados, indices, metodo_bloco="none", bootstrap_top=0
    )
    pares = resolver_pares(
        dados, [(("Governador", "20"), ("Senador", "200"))]
    )
    focados = analisar_pares_focados(
        dados,
        pares,
        resultado,
        benchmark_tipo="none",
        bootstrap_repeticoes=50,
        permutacoes=100,
        goodman_repeticoes=20,
        seed=3,
    )
    assert len(focados) == 1
    par = focados[0]
    assert par.r_dentro > 0.8
    assert par.ic_boot_inf is not None and par.ic_boot_sup is not None
    assert 0.0 <= par.p_perm <= 1.0
    assert par.q_focado == pytest.approx(par.p_perm)
    assert len(par.locais) == 3
    assert len(par.pontos) == 18
    assert par.benchmark_n == 0
    assert par.a_votos > 0 and par.b_votos > 0
    assert par.n_eleitores == 1800
    assert par.flag_covotacao in {"informativo", "parcial", "indeterminado"}


def test_focado_multiplos_pares_aplica_bh():
    dados = construir_dados(_planilha())
    indices = selecionar(dados, min_votos=0, min_cobertura=0)
    resultado = analisar_correlacoes(
        dados, indices, metodo_bloco="none", bootstrap_top=0
    )
    pares = resolver_pares(
        dados,
        [
            (("Governador", "20"), ("Senador", "200")),
            (("Governador", "30"), ("Senador", "300")),
        ],
    )
    focados = analisar_pares_focados(
        dados,
        pares,
        resultado,
        benchmark_tipo="none",
        bootstrap_repeticoes=10,
        permutacoes=50,
        goodman_repeticoes=5,
        seed=4,
    )
    assert len(focados) == 2
    p_valores = [par.p_perm for par in focados]
    q_esperados = bh_fdr(p_valores)
    for par, q in zip(focados, q_esperados):
        assert par.q_focado == pytest.approx(float(q))
        assert par.q_focado >= par.p_perm

    html = render_focado(montar_payload_focado(dados, focados))
    assert html.count('<section class="par">') == 2


def test_focado_benchmark_fed_est_cai_para_todos():
    dados = construir_dados(_planilha())
    indices = selecionar(dados, min_votos=0, min_cobertura=0)
    resultado = analisar_correlacoes(
        dados, indices, metodo_bloco="none", bootstrap_top=0
    )
    pares = resolver_pares(
        dados, [(("Governador", "20"), ("Senador", "200"))]
    )
    focados = analisar_pares_focados(
        dados,
        pares,
        resultado,
        benchmark_tipo="fed-est",
        bootstrap_repeticoes=10,
        permutacoes=10,
        goodman_repeticoes=5,
        seed=3,
    )
    par = focados[0]
    assert par.benchmark_tipo.startswith("todos")
    assert par.benchmark_n == 4
    assert par.benchmark_percentil is None


def test_focado_csvs_e_html(tmp_path):
    dados = construir_dados(_planilha())
    indices = selecionar(dados, min_votos=0, min_cobertura=0)
    resultado = analisar_correlacoes(
        dados, indices, metodo_bloco="none", bootstrap_top=0
    )
    pares = resolver_pares(
        dados, [(("Governador", "20"), ("Senador", "200"))]
    )
    focados = analisar_pares_focados(
        dados,
        pares,
        resultado,
        benchmark_tipo="none",
        bootstrap_repeticoes=20,
        permutacoes=20,
        goodman_repeticoes=5,
        seed=3,
    )

    csv_principal = tmp_path / "focado.csv"
    csv_locais = tmp_path / "focado_locais.csv"
    csv_bench = tmp_path / "focado_benchmark.csv"
    escrever_focado_csv(focados, csv_principal)
    escrever_focado_locais_csv(focados, csv_locais)
    escrever_focado_benchmark_csv(focados, csv_bench)

    with csv_principal.open(encoding="utf-8-sig", newline="") as arquivo:
        linhas = list(csv.DictReader(arquivo, delimiter=";"))
    assert len(linhas) == 1
    assert "r_dentro" in linhas[0]
    assert "q_focado" in linhas[0]
    assert "flag_covotacao" in linhas[0]

    with csv_locais.open(encoding="utf-8-sig", newline="") as arquivo:
        locais = list(csv.DictReader(arquivo, delimiter=";"))
    assert len(locais) == 3
    assert "p_b_a_inf" in locais[0]

    with csv_bench.open(encoding="utf-8-sig", newline="") as arquivo:
        bench = list(csv.DictReader(arquivo, delimiter=";"))
    assert len(bench) == 1
    assert "benchmark_n" in bench[0]

    payload = montar_payload_focado(dados, focados)
    html = render_focado(payload)
    assert "<svg" in html
    assert "__PARES__" not in html
    assert "GOV A" in html
    assert "Limites de co-votação por local" in html

    payload["pares"][0]["a"]["rotulo"] = "</script><b>x</b>"
    html_escapado = render_focado(payload)
    assert "&lt;/script&gt;" in html_escapado
    assert "</script><b>x</b>" not in html_escapado


@pytest.mark.skipif(not XLSX.exists(), reason="planilha real de Parauapebas ausente")
def test_planilha_real_focado_baseline():
    planilha = ler_planilha(XLSX)
    dados = construir_dados(planilha)
    pares = resolver_pares(
        dados,
        [
            (
                ("Deputado Federal", "2200"),
                ("Deputado Estadual", "22100"),
            )
        ],
    )
    indices = selecionar(dados)
    for i, j in pares:
        if i not in indices:
            indices.append(i)
        if j not in indices:
            indices.append(j)
    indices = sorted(set(indices))

    resultado = analisar_correlacoes(
        dados, indices, metodo_bloco="presidente", bootstrap_top=0
    )
    focados = analisar_pares_focados(
        dados,
        pares,
        resultado,
        benchmark_tipo="fed-est",
        bootstrap_repeticoes=100,
        permutacoes=200,
        goodman_repeticoes=100,
        seed=1,
    )
    par = focados[0]

    assert par.r_bruto == pytest.approx(0.7631, abs=0.005)
    assert par.r_dentro == pytest.approx(0.3792, abs=0.005)
    assert par.r_bloco == pytest.approx(0.3438, abs=0.005)
    assert par.r_local == pytest.approx(0.8942, abs=0.005)
    assert par.p_perm < 0.05
    assert par.q_global == pytest.approx(0.0875, abs=0.002)
    assert par.benchmark_n == 194
    assert par.benchmark_percentil == pytest.approx(97.4, abs=0.5)
    assert par.flag_covotacao == "indeterminado"
    assert len(par.locais) == 55
    assert len(par.pontos) == 586
    assert par.goodman_b_a == pytest.approx(1.085, abs=0.01)


@pytest.mark.skipif(not XLSX.exists(), reason="planilha real de Parauapebas ausente")
def test_planilha_real_smoke():
    planilha = ler_planilha(XLSX)
    dados = construir_dados(planilha)
    assert dados.n_urnas == 586
    assert dados.n_locais == 55
    assert int(dados.comparecimento.sum()) == 156_468

    indices = selecionar(dados)
    assert len(indices) >= 20

    resultado = analisar_correlacoes(
        dados, indices, metodo_bloco="presidente", bootstrap_top=0
    )
    assert resultado.r_dentro.shape == (len(indices), len(indices))
    assert np.isfinite(resultado.r_dentro).any()
    assert len(resultado.pares) == len(indices) * (len(indices) - 1) // 2

    pares = analisar_covotacao(dados, indices, goodman_top=0)
    assert resumo_covotacao(pares)["total"] > 0
    for par in pares:
        assert par.limite_inf <= par.limite_sup
        assert 0 <= par.p_b_dado_a_inf <= 1
