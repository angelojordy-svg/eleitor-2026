import json

from eleitor.models import Candidato, ResultadoCargo, Totalizacao, TotaisVotos
from eleitor.render.html import render_html
from eleitor.services.snapshot import (
    _cand_dict,
    _financas_dict,
    _res_dict,
    _resumo_proporcional,
    _secoes_dict,
)


def _resultado_exemplo() -> ResultadoCargo:
    return ResultadoCargo(
        eleicao=6257,
        cargo=1,
        cargo_nome="Presidente",
        abrangencia="br",
        candidatos=[
            Candidato(
                numero="13",
                nome="FULANO DE TAL",
                nome_urna="FULANO",
                partido="PT",
                votos=1200,
                percentual=54.55,
                situacao="",
                eleito=True,
                sqcand="280002542548",
            ),
            Candidato(
                numero="22",
                nome="BELTRANO DA SILVA",
                nome_urna="BELTRANO",
                partido="PL",
                votos=1000,
                percentual=45.45,
                situacao="",
                eleito=False,
                sqcand="280002551544",
            ),
        ],
        votos=TotaisVotos(total=2300, validos=2200, brancos=60, nulos=40, anulados=0),
        totalizacao=Totalizacao(
            secoes_total=100,
            secoes_totalizadas=40,
            percentual_secoes=40.0,
            eleitores_total=2000,
            eleitores_secoes_totalizadas=800,
            gerado_em="04/10/2026 17:30:00",
        ),
    )


def test_res_dict_compacto():
    res = _resultado_exemplo()
    dados = _res_dict(res, {"280002542548": "data:image/jpeg;base64,AAAA"})
    assert dados["cargo"] == 1
    assert dados["tot"]["st"] == 40
    assert dados["votos"]["validos"] == 2200
    assert dados["cands"][0]["nome"] == "FULANO"
    assert dados["cands"][0]["e"] is True
    assert dados["cands"][0]["foto"].startswith("data:image/jpeg")
    assert "foto" not in dados["cands"][1]


def test_cand_dict_sem_foto():
    cand = Candidato(
        numero="13",
        nome="FULANO",
        nome_urna="",
        partido="PT",
        votos=10,
        percentual=1.0,
        situacao="",
        eleito=False,
    )
    dados = _cand_dict(cand)
    assert dados["nome"] == "FULANO"
    assert "foto" not in dados


def test_resumo_proporcional_marca_primeiro_suplente_por_agremiacao():
    res = ResultadoCargo(
        eleicao=6259,
        cargo=6,
        cargo_nome="Deputado Federal",
        abrangencia="pa",
        candidatos=[
            Candidato("4001", "ELEITO A", "ELEITO A", "PT", 90000, 30.0, "Eleito por QP", True, agremiacao="PT / PV"),
            Candidato("4002", "SUPLENTE A", "SUPLENTE A", "PV", 9000, 3.0, "Suplente", False, agremiacao="PT / PV"),
            Candidato("4003", "SUPLENTE B", "SUPLENTE B", "PL", 8000, 2.5, "Suplente", False, agremiacao="PL"),
            Candidato("4004", "SUPLENTE C", "SUPLENTE C", "PT", 7000, 2.0, "Suplente", False, agremiacao="PT / PV"),
        ],
        votos=TotaisVotos(),
        totalizacao=Totalizacao(),
        vagas=2,
    )
    resumo = _resumo_proporcional(res)
    sup = {item["n"]: item["sup"] for item in resumo["ranking"]}
    assert sup["4002"] is True      # mais votado suplente da federação PT / PV
    assert sup["4004"] is False     # segundo suplente da mesma federação
    assert sup["4003"] is True      # único suplente do PL
    assert sup["4001"] is False     # eleito, não é suplente


def test_secoes_dict_agrega_votos():
    secoes = {
        "0001": {
            "cargos": {
                1: {
                    "aptos": 340,
                    "comparecimento": 293,
                    "votos": [
                        {"tipo": "nominal", "votos": 188, "codigo": 13, "partido": 13},
                        {"tipo": "nominal", "votos": 71, "codigo": 22, "partido": 22},
                        {"tipo": "branco", "votos": 9},
                        {"tipo": "nulo", "votos": 12},
                        {"tipo": "legenda", "votos": 3},
                    ],
                }
            }
        }
    }
    itens = _secoes_dict(secoes)
    assert len(itens) == 1
    info = itens[0]["cargos"]["1"]
    assert info["aptos"] == 340
    assert info["votos"]["13"] == 188
    assert info["votos"]["22"] == 71
    assert info["b"] == 9
    assert info["nu"] == 12
    assert info["lg"] == 3


def test_render_html_embute_dados_e_navegacao():
    dados = {
        "gerado_em": "04/10/2026 18:00",
        "cargos": {"1": "Presidente", "3": "Governador"},
        "brasil": _res_dict(_resultado_exemplo()),
        "estados": [
            {
                "uf": "pa",
                "nome": "Pará",
                "cargos": {
                    "3": _res_dict(_resultado_exemplo()),
                    "6": {
                        "cargo_nome": "Deputado Federal",
                        "vagas": 17,
                        "tot": {"st": 40, "ts": 100, "pct": 40.0, "gerado": "04/10/2026 17:30:00"},
                        "votos": {"validos": 2200, "brancos": 60, "nulos": 40, "anulados": 0},
                        "partidos": {"PT": 1},
                        "eleitos": [{"n": "13", "nome": "FULANO", "p": "PT", "v": 1200, "pct": 54.55}],
                        "ranking": [{"n": "13", "nome": "FULANO", "p": "PT", "v": 1200, "pct": 54.55, "e": True}],
                    },
                },
            }
        ],
        "congresso": {
            "camara": {"total": 1, "vagas": 513, "partidos": {"PT": 1}},
            "camara_por_uf": {"pa": {"total": 1, "vagas": 17, "partidos": {"PT": 1}}},
            "senado_novos": {"total": 1, "vagas": 54, "partidos": {"PL": 1}},
            "senado_antigos": {"total": 1, "vagas": 27, "partidos": {"MDB": 1}},
            "estaduais": {"total": 1, "vagas": 1035, "partidos": {"PSD": 1}},
            "estaduais_por_uf": {"pa": {"total": 1, "vagas": 41, "partidos": {"PSD": 1}}},
            "distrital": {"total": 1, "vagas": 24, "partidos": {"PP": 1}},
        },
        "municipios": [
            {
                "uf": "pa",
                "codigo": "04154",
                "nome": "ANANINDEUA",
                "cargos": {},
                "secoes_por_zona": {},
            }
        ],
        "catalogo": [["pa", "04154", "ANANINDEUA", ["0072", "0107"]]],
    }
    html = render_html(dados)
    assert "/*__DADOS__*/" not in html
    assert "const DADOS =" in html
    assert "ANANINDEUA" in html
    assert "FULANO" in html
    assert "← Voltar" in html
    assert "Limpar pesquisa" in html
    assert "#/brasil" in html
    assert "location.hash" in html
    assert "ver página do candidato" in html
    assert "#/candidato/brasil/" in html
    assert "ELEICAO_DO_CARGO" in html
    assert "Atualizar online" in html
    assert "atualizarOnline" in html
    assert "Filtrar por nome" in html
    assert "filtrarCartoes" in html
    assert "filtrarColunas" in html
    assert "Todos os partidos" in html
    assert "renderHemiciclo" in html
    assert "viewCongresso" in html
    assert "painelProporcional" in html
    assert "carregarMunicipio" in html
    assert "catalogoInfo" in html
    payload = html.split("const DADOS = ", 1)[1].split(";\n", 1)[0]
    decodificado = json.loads(payload)
    assert decodificado["gerado_em"] == "04/10/2026 18:00"
    assert decodificado["catalogo"][0][2] == "ANANINDEUA"
    assert decodificado["catalogo"][0][3] == ["0072", "0107"]
    assert decodificado["congresso"]["camara"]["partidos"]["PT"] == 1


def test_render_html_candidatos_ordenados_por_votos():
    res = _resultado_exemplo()
    votos = [c.votos for c in res.candidatos]
    assert votos == sorted(votos, reverse=True)


def test_financas_dict_compacta_e_anexa_votos():
    bake = {
        "gerado_em": "17/10/2026 04:05:37",
        "itens": [
            {
                "sq": "280002551544",
                "nr": "22",
                "nome": "FLAVIO BOLSONARO",
                "partido": "PL",
                "uf": "BR",
                "cargo": 1,
                "sit": "ELEITO",
                "receita": 88952028.52,
                "fundos": 60701241.0,
                "gasto": 67556449.4,
                "bens": 8186555.83,
            }
        ],
    }
    dados = _financas_dict(bake, {"280002551544": 1234567})
    assert dados["gerado_em"] == "17/10/2026 04:05:37"
    assert dados["parcial"] is True
    assert dados["colunas"] == [
        "nome", "partido", "uf", "cargo", "sit", "nr",
        "receita", "fundos", "gasto", "bens", "votos",
    ]
    linha = dados["itens"][0]
    assert linha[dados["colunas"].index("nome")] == "FLAVIO BOLSONARO"
    assert linha[dados["colunas"].index("votos")] == 1234567
    assert linha[dados["colunas"].index("gasto")] == 67556449.4


def test_render_html_tem_aba_de_gastos():
    dados = {
        "gerado_em": "04/10/2026 18:00",
        "cargos": {"1": "Presidente"},
        "brasil": _res_dict(_resultado_exemplo()),
        "estados": [],
        "congresso": {},
        "financas": _financas_dict(
            {
                "gerado_em": "17/10/2026 04:05:37",
                "itens": [
                    {
                        "sq": "1",
                        "nr": "22",
                        "nome": "FLAVIO BOLSONARO",
                        "partido": "PL",
                        "uf": "BR",
                        "cargo": 1,
                        "sit": "ELEITO",
                        "receita": 1.0,
                        "fundos": 2.0,
                        "gasto": 3.0,
                        "bens": 4.0,
                    }
                ],
            },
            {"1": 500},
        ),
        "municipios": [],
        "catalogo": [],
    }
    html = render_html(dados)
    assert "viewRanking" in html
    assert "atualizarRanking" in html
    assert "Gastos de campanha" in html
    assert "#/ranking" in html
    payload = html.split("const DADOS = ", 1)[1].split(";\n", 1)[0]
    decodificado = json.loads(payload)
    assert decodificado["financas"]["itens"][0][0] == "FLAVIO BOLSONARO"
