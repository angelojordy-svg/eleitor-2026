from __future__ import annotations

from typing import Any

import pytest

from eleitor.services import mundo_bu as svc_bu
from eleitor.sources.resultados import url_resultado, url_secao_aux, url_secoes_config
from eleitor.sources.urna import url_arquivo_urna


def _config(secoes_extra: bool = False) -> dict[str, Any]:
    wellington = [
        {"ns": "1689", "da": "25/10/2026", "ha": "01:51:38"},
        {"ns": "1690", "da": "25/10/2026", "ha": "01:51:38"},
        {"ns": "1691"},
        {"ns": "1692", "nsp": "1691"},
    ]
    toquio = [{"ns": "1700", "da": "25/10/2026", "ha": "06:32:52"}]
    if secoes_extra:
        toquio.append({"ns": "1701", "da": "25/10/2026", "ha": "06:33:10"})
    return {
        "dg": "25/10/2026",
        "hg": "13:59:28",
        "abr": [
            {
                "cd": "zz",
                "mu": [
                    {
                        "cd": "30805",
                        "nm": "WELLINGTON",
                        "zon": [{"cd": "0001", "sec": wellington}],
                    },
                    {
                        "cd": "30627",
                        "nm": "TÓQUIO",
                        "zon": [{"cd": "0001", "sec": toquio}],
                    },
                ],
            }
        ],
    }


def _corpo_6258() -> dict[str, Any]:
    return {
        "ele": 6258,
        "carg": [
            {
                "cd": "1",
                "nmn": "Presidente",
                "nv": "1",
                "agr": [
                    {
                        "par": [
                            {
                                "sg": "PL",
                                "cand": [
                                    {
                                        "n": "22",
                                        "nm": "FLAVIO BOLSONARO",
                                        "nmu": "FLAVIO BOLSONARO",
                                        "vap": "0",
                                    }
                                ],
                            },
                            {
                                "sg": "PT",
                                "cand": [
                                    {"n": "13", "nm": "LULA", "nmu": "LULA", "vap": "0"}
                                ],
                            },
                        ]
                    }
                ],
            }
        ],
        "v": {"vv": "0"},
        "s": {"ts": "10", "st": "0", "pst": "0,00"},
    }


def _bu(codigo: str, secao: str, pt: int, pl: int) -> dict[str, Any]:
    return {
        "municipio": int(codigo),
        "zona": 1,
        "secao": int(secao),
        "cargos": {
            1: {
                "aptos": 100,
                "comparecimento": pt + pl,
                "votos": [
                    {"tipo": "nominal", "codigo": 13, "partido": 13, "votos": pt},
                    {"tipo": "nominal", "codigo": 22, "partido": 22, "votos": pl},
                ],
            }
        },
    }


class ClienteFake:
    workers = 1

    def __init__(self) -> None:
        self.chamadas: list[str] = []
        self.corpos: dict[str, Any] = {}
        self.bytes: dict[str, bytes] = {}

    def get_json(self, url: str, ttl: float = 0.0, allow_404: bool = False) -> Any:
        self.chamadas.append(url)
        return self.corpos.get(url)

    def get_bytes(self, url: str, ttl: float = 0.0, allow_404: bool = False) -> bytes | None:
        self.chamadas.append(url)
        return self.bytes.get(url)


def _preparar_cliente(secoes_extra: bool = False) -> ClienteFake:
    cliente = ClienteFake()
    config = _config(secoes_extra)
    cliente.corpos[url_secoes_config("zz", pleito=svc_bu.PLEITO_SEGUNDO)] = config
    cliente.corpos[url_resultado(6258, 1, uf="zz")] = _corpo_6258()

    votos = {
        ("30805", "1689"): (71, 15),
        ("30805", "1690"): (30, 20),
        ("30627", "1700"): (10, 100),
    }
    if secoes_extra:
        votos[("30627", "1701")] = (5, 7)

    for (codigo, secao), (pt, pl) in votos.items():
        aux_url = url_secao_aux("zz", codigo, "0001", secao, pleito=svc_bu.PLEITO_SEGUNDO)
        hash_urna = f"hash-{codigo}-{secao}"
        nome = f"o03221zz{codigo}0001{secao.zfill(4)}-bu.dat"
        cliente.corpos[aux_url] = {
            "hashes": [{"hash": hash_urna, "arq": [{"nm": nome}]}]
        }
        cliente.bytes[
            url_arquivo_urna(
                "zz",
                codigo,
                "0001",
                secao,
                hash_urna,
                nome,
                pleito=svc_bu.PLEITO_SEGUNDO,
            )
        ] = f"{codigo}-{secao}".encode()
    return cliente


def test_ler_cidades_conta_principais_e_secoes_com_bu() -> None:
    cidades = svc_bu._ler_cidades(_config())

    assert set(cidades) == {"30805", "30627"}
    assert cidades["30805"]["iso"] == "NZ"
    assert cidades["30805"]["secoes_total"] == 3  # 1689, 1690 e 1692 (1691 é agregada)
    assert [s["secao"] for s in cidades["30805"]["secoes"]] == ["1689", "1690"]
    assert cidades["30627"]["secoes_total"] == 1


def test_agregar_bu_por_pais_e_cobertura() -> None:
    cidades = svc_bu._ler_cidades(_config())
    secoes = {
        "30805/0001/1689": {
            "municipio": 30805,
            "votos": {"13": 71, "22": 15},
        },
        "30805/0001/1690": {
            "municipio": 30805,
            "votos": {"13": 30, "22": 20},
        },
        "30627/0001/1700": {
            "municipio": 30627,
            "votos": {"13": 10, "22": 100},
        },
    }
    candidatos = {
        "13": {"p": "PT", "nome": "LULA"},
        "22": {"p": "PL", "nome": "FLAVIO BOLSONARO"},
    }
    res, validos, total, cobertura = svc_bu._agregar(cidades, secoes, candidatos)

    assert res["NZ"] == [["PT", 74.26, 101, "LULA", 0], ["PL", 25.74, 35, "FLAVIO BOLSONARO", 0]]
    assert validos["NZ"] == 136
    assert res["JP"][0][0] == "PL"
    assert total is not None and total[0][0] == "PL"
    assert cobertura["paises"]["NZ"] == {"lidas": 2, "secoes": 3}
    assert cobertura["paises"]["JP"] == {"lidas": 1, "secoes": 1}
    assert cobertura["total"] == {"lidas": 3, "secoes": 4, "eletronicas": 1282}


def test_bake_bu_incremental_por_secao(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("ELEITOR_MAPA_DIR", str(tmp_path))
    cliente = _preparar_cliente()

    def fake_parse(raw: bytes) -> dict[str, Any]:
        codigo, secao = raw.decode().split("-")
        return _bu(codigo, secao, 10, 5)

    monkeypatch.setattr(svc_bu, "parse_bu", fake_parse)

    dados = svc_bu.bake_mundo_bu(cliente)
    assert dados is not None
    assert dados["meta"]["secoes_lidas"] == 3
    assert dados["cobertura"]["paises"]["NZ"]["lidas"] == 2
    assert dados["cobertura"]["paises"]["JP"]["lidas"] == 1

    # Segunda chamada: tudo veio do cache incremental (nenhum aux/BU novo).
    antes = len([u for u in cliente.chamadas if "-aux.json" in u or "-bu.dat" in u])
    svc_bu.bake_mundo_bu(cliente)
    depois = len([u for u in cliente.chamadas if "-aux.json" in u or "-bu.dat" in u])
    assert depois == antes

    # Uma seção nova no config: baixa só ela.
    cliente.corpos[url_secoes_config("zz", pleito=svc_bu.PLEITO_SEGUNDO)] = _config(secoes_extra=True)
    aux_novo = url_secao_aux("zz", "30627", "0001", "1701", pleito=svc_bu.PLEITO_SEGUNDO)
    cliente.corpos[aux_novo] = {
        "hashes": [{"hash": "h1701", "arq": [{"nm": "o03221zz3062700011701-bu.dat"}]}]
    }
    cliente.bytes[
        url_arquivo_urna(
            "zz",
            "30627",
            "0001",
            "1701",
            "h1701",
            "o03221zz3062700011701-bu.dat",
            pleito=svc_bu.PLEITO_SEGUNDO,
        )
    ] = b"30627-1701"
    svc_bu.bake_mundo_bu(cliente)
    novos = [
        u
        for u in cliente.chamadas
        if ("-aux.json" in u or "-bu.dat" in u) and "1701" in u
    ]
    assert len(novos) == 2


def test_comparar_mundo_bu_com_oficial() -> None:
    bu = {
        "total": [["PL", 55.0, 110, "FLAVIO BOLSONARO", 0]],
        "res": {"PT": [["PL", 55.0, 110, "FLAVIO BOLSONARO", 0]]},
        "cobertura": {"paises": {"PT": {"lidas": 2, "secoes": 3}}},
        "meta": {"secoes_lidas": 2},
    }
    oficial = {
        "total": [["PL", 54.0, 108, "FLAVIO BOLSONARO", 100]],
        "res": {"PT": [["PL", 54.0, 108, "FLAVIO BOLSONARO", 100]]},
    }
    cmp = svc_bu.comparar_mundo(bu, oficial)
    assert cmp["oficial_disponivel"] is True
    assert cmp["total"]["dif_lider"] == 2
    assert cmp["paises"][0]["cobertura"]["lidas"] == 2
    assert cmp["paises"][0]["oficial"][0][2] == 108


def test_urls_do_segundo_turno() -> None:
    assert (
        url_secoes_config("zz", pleito=3221)
        == "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221/config/zz/zz-p003221-cs.json"
    )
    assert (
        url_secao_aux("zz", "30805", "1", "1689", pleito=3221)
        == "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221/"
        "dados/zz/30805/0001/1689/p003221-zz-m30805-z0001-s1689-aux.json"
    )
    assert (
        url_arquivo_urna(
            "zz", "30805", "1", "1689", "abc", "o03221zz3080500011689-bu.dat", pleito=3221
        )
        == "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221/"
        "dados/zz/30805/0001/1689/abc/o03221zz3080500011689-bu.dat"
    )
