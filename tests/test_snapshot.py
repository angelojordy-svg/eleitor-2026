import json

from eleitor.models import Candidato, ResultadoCargo, Totalizacao, TotaisVotos
from eleitor.render.html import render_html
from eleitor.services.snapshot import _cand_dict, _res_dict, _secoes_dict


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
                "cargos": {"3": _res_dict(_resultado_exemplo())},
            }
        ],
        "municipios": [
            {
                "uf": "pa",
                "codigo": "04154",
                "nome": "ANANINDEUA",
                "cargos": {},
                "secoes_por_zona": {},
            }
        ],
        "catalogo": [["pa", "04154", "ANANINDEUA"]],
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
    payload = html.split("const DADOS = ", 1)[1].split(";\n", 1)[0]
    decodificado = json.loads(payload)
    assert decodificado["gerado_em"] == "04/10/2026 18:00"
    assert decodificado["catalogo"][0][2] == "ANANINDEUA"


def test_render_html_candidatos_ordenados_por_votos():
    res = _resultado_exemplo()
    votos = [c.votos for c in res.candidatos]
    assert votos == sorted(votos, reverse=True)
