from eleitor.sources.resultados import (
    parse_aux,
    parse_municipios,
    parse_resultado,
    parse_secoes,
)

RESULTADO_PRESIDENTE = {
    "ele": "6257",
    "t": "1",
    "f": "o",
    "cdabr": "br",
    "dg": "04/10/2026",
    "hg": "17:30:00",
    "carg": [
        {
            "cd": "1",
            "nmn": "Presidente",
            "agr": [
                {
                    "n": "1",
                    "nm": "COLIGAÇÃO A",
                    "tp": "c",
                    "com": "PT / PC do B",
                    "par": [
                        {
                            "n": "13",
                            "sg": "PT",
                            "nm": "PARTIDO DOS TRABALHADORES",
                            "cand": [
                                {
                                    "n": "13",
                                    "sqcand": "280002542548",
                                    "nm": "FULANO DE TAL",
                                    "nmu": "FULANO",
                                    "vap": "1200",
                                    "pvap": "54,55",
                                    "st": "",
                                    "e": "s",
                                }
                            ],
                        }
                    ],
                },
                {
                    "n": "2",
                    "nm": "PARTIDO ISOLADO",
                    "tp": "i",
                    "com": "PL",
                    "par": [
                        {
                            "n": "22",
                            "sg": "PL",
                            "nm": "PARTIDO LIBERAL",
                            "cand": [
                                {
                                    "n": "22",
                                    "sqcand": "280002551544",
                                    "nm": "BELTRANO DA SILVA",
                                    "nmu": "BELTRANO",
                                    "vap": "1000",
                                    "pvap": "45,45",
                                    "st": "",
                                    "e": "n",
                                }
                            ],
                        }
                    ],
                },
            ],
        }
    ],
    "s": {"ts": "100", "st": "40", "pst": "40,00"},
    "e": {"te": "2000", "est": "800"},
    "v": {"tv": "2300", "vv": "2200", "vb": "60", "vn": "40", "van": "0"},
}

MUNICIPIOS = {
    "abr": [
        {
            "cd": "pa",
            "ds": "PARÁ",
            "mu": [
                {"cd": "05835", "cdi": "1505502", "nm": "PARAUAPEBAS", "c": "n", "z": ["0075", "0106"]},
                {"cd": "04839", "cdi": "1504208", "nm": "MARABÁ", "c": "n", "z": ["0013"]},
            ],
        }
    ]
}

SECOES = {
    "cdp": "3220",
    "abr": [
        {
            "cd": "pa",
            "ds": "PARÁ",
            "mu": [
                {
                    "cd": "05835",
                    "nm": "PARAUAPEBAS",
                    "zon": [
                        {
                            "cd": "0075",
                            "sec": [
                                {"ns": "0001"},
                                {"ns": "0637", "nsa": ["0723"]},
                                {"ns": "0723", "nsp": "0637", "da": "04/10/2026", "ha": "17:01:02"},
                            ],
                        }
                    ],
                }
            ],
        }
    ]
}


def test_parse_resultado_ordena_por_votos():
    res = parse_resultado(RESULTADO_PRESIDENTE)
    assert res.cargo == 1
    assert res.cargo_nome == "Presidente"
    assert [c.numero for c in res.candidatos] == ["13", "22"]
    assert res.candidatos[0].eleito is True
    assert res.candidatos[0].votos == 1200
    assert abs(res.candidatos[0].percentual - 54.55) < 0.001
    assert res.candidatos[1].partido == "PL"
    assert res.votos.validos == 2200
    assert res.votos.brancos == 60
    assert res.totalizacao.secoes_totalizadas == 40
    assert res.totalizacao.percentual_secoes == 40.0
    assert res.totalizacao.gerado_em == "04/10/2026 17:30:00"


def test_parse_municipios():
    municipios = parse_municipios(MUNICIPIOS)
    assert len(municipios) == 2
    parauapebas = municipios[0]
    assert parauapebas.nome == "PARAUAPEBAS"
    assert parauapebas.codigo == "05835"
    assert parauapebas.zonas == ["0075", "0106"]


def test_parse_secoes_com_agregadas():
    zonas = parse_secoes(SECOES, "pa", "5835")
    assert len(zonas) == 1
    assert zonas[0].zona == "0075"
    secoes = zonas[0].secoes
    assert [s.numero for s in secoes] == ["0001", "0637", "0723"]
    agregada = secoes[1]
    assert agregada.agregadas == ["0723"]
    principal = secoes[2]
    assert principal.principal == "0637"
    assert principal.data_aux == "04/10/2026"


def test_parse_aux():
    status, urnas = parse_aux(
        {
            "st": "Totalizada",
            "hashes": [
                {"hash": "abc", "st": "Totalizado"},
                {"hash": "def", "st": "Totalizado"},
            ],
        }
    )
    assert status == "Totalizada"
    assert urnas == 2
