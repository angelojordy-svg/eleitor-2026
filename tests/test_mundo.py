from __future__ import annotations

from typing import Any

import pytest

from eleitor.models import Municipio
from eleitor.paises import CIDADE_PAIS, PAISES
from eleitor.services import mundo as svc_mundo
from eleitor.sources.geo import mundo_para_paths
from eleitor.sources.resultados import url_resultado


def _municipio(codigo: str, nome: str = "") -> Municipio:
    return Municipio(uf="zz", codigo=codigo, ibge="", nome=nome or codigo, zonas=[])


class LocalidadesFake:
    def __init__(self, cidades: list[Municipio]) -> None:
        self._cidades = cidades

    @property
    def exterior(self) -> list[Municipio]:
        return self._cidades


class ClienteFake:
    workers = 2

    def __init__(self, corpos: dict[str, Any]) -> None:
        self.corpos = corpos
        self.pedidos: list[str] = []

    def get_json(self, url: str, ttl: float = 0.0, allow_404: bool = False) -> Any:
        self.pedidos.append(url)
        return self.corpos.get(url)


def _corpo(cands: list[tuple[str, str, str, int]], st: int = 10, ts: int = 10) -> dict[str, Any]:
    """EA20 mínimo: [(sigla, número, nome, votos)]."""

    return {
        "ele": 6257,
        "carg": [
            {
                "cd": "1",
                "nmn": "Presidente",
                "nv": "1",
                "agr": [
                    {
                        "par": [
                            {
                                "sg": sigla,
                                "cand": [
                                    {
                                        "n": numero,
                                        "nm": nome,
                                        "nmu": nome,
                                        "vap": str(votos),
                                    }
                                ],
                            }
                            for sigla, numero, nome, votos in cands
                        ]
                    }
                ],
            }
        ],
        "v": {"vv": str(sum(votos for _, _, _, votos in cands))},
        "s": {"st": str(st), "ts": str(ts), "pst": "100,00" if st == ts else "0,00"},
        "dg": "04/10/2026",
        "hg": "17:00:00",
    }


def _geometria_mundo() -> dict[str, Any]:
    def quadrado(
        lon0: float,
        lon1: float,
        lat0: float,
        lat1: float,
        iso: str,
        nome: str,
        iso_eh: str | None = None,
    ) -> dict[str, Any]:
        props: dict[str, Any] = {"ISO_A2": iso, "NAME_PT": nome}
        props["ISO_A2_EH"] = iso if iso_eh is None else iso_eh
        return {
            "type": "Feature",
            "properties": props,
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]
                ],
            },
        }

    return {
        "type": "FeatureCollection",
        "features": [
            quadrado(-10.0, -5.0, 37.0, 42.0, "PT", "Portugal"),
            quadrado(130.0, 140.0, 32.0, 38.0, "JP", "Japão"),
            quadrado(-60.0, -45.0, -20.0, 0.0, "BR", "Brasil"),
            quadrado(-30.0, -25.0, 36.0, 39.0, "PT", "Açores", iso_eh="-99"),
        ],
    }


# --------------------------------------------------------------------------
# Base cidade -> país
# --------------------------------------------------------------------------


def test_base_cidade_pais_cobre_as_localidades_do_exterior() -> None:
    assert len(PAISES) == 135  # 134 países com seção + Vaticano (0 eleitores)
    assert len(CIDADE_PAIS) == 187
    assert len(set(CIDADE_PAIS)) == len(CIDADE_PAIS)

    # Casos que o nome da cidade sozinho não resolve.
    assert CIDADE_PAIS["29580"] == "PY"  # Concepción (Paraguai, não Chile)
    assert CIDADE_PAIS["30430"] == "UY"  # Rio Branco (Uruguai)
    assert CIDADE_PAIS["30511"] == "CR"  # São José (Costa Rica)
    assert CIDADE_PAIS["30520"] == "SV"  # São Salvador (El Salvador)
    assert CIDADE_PAIS["30490"] == "DO"  # São Domingos (Rep. Dominicana)
    assert CIDADE_PAIS["99155"] == "AR"  # Puerto Iguazú (Argentina)
    assert CIDADE_PAIS["99236"] == "BO"  # Puerto Quijarro (Bolívia)
    assert CIDADE_PAIS["99279"] == "VE"  # Santa Elena de Uairén (Venezuela)
    assert CIDADE_PAIS["99333"] == "GF"  # St Georges de Loyapock (Guiana Francesa)


def test_cada_pais_tem_nome_e_ao_menos_uma_cidade() -> None:
    for iso, info in PAISES.items():
        assert len(iso) == 2
        assert info["nome"]
        assert info["cidades"]


# --------------------------------------------------------------------------
# Agregação por país
# --------------------------------------------------------------------------


def test_agregar_soma_cidades_e_monta_top2_por_pais() -> None:
    cidades = [
        _municipio("29955", "Lisboa"),
        _municipio("30341", "Porto"),
        _municipio("30198", "Nagoya"),
    ]
    corpos = {
        "29955": _corpo([("PT", "13", "LULA", 60), ("PL", "22", "FLAVIO", 40)]),
        "30341": _corpo([("PT", "13", "LULA", 30), ("PL", "22", "FLAVIO", 70)]),
        "30198": _corpo([("PL", "22", "FLAVIO", 100), ("PT", "13", "LULA", 20)]),
    }

    res, validos, total = svc_mundo._agregar(corpos, cidades)

    assert validos["PT"] == 200
    assert res["PT"] == [["PL", 55.0, 110, "FLAVIO", 100], ["PT", 45.0, 90, "LULA", 100]]
    assert validos["JP"] == 120
    assert res["JP"][0][:3] == ["PL", 83.33, 100]
    assert total is not None
    assert total[0][:3] == ["PL", 65.62, 210]
    assert total[1][:3] == ["PT", 34.38, 110]


def test_bake_mundo_1_turno_usa_agregado_e_cidades() -> None:
    cidades = [
        _municipio("29955", "Lisboa"),
        _municipio("30198", "Nagoya"),
    ]
    loc = LocalidadesFake(cidades)
    url_total = url_resultado(6257, 1, uf="zz")
    cliente = ClienteFake(
        {
            url_total: _corpo([("PT", "13", "LULA", 90), ("PL", "22", "FLAVIO", 110)]),
            url_resultado(6257, 1, uf="zz", municipio="29955"): _corpo(
                [("PT", "13", "LULA", 60), ("PL", "22", "FLAVIO", 40)]
            ),
            url_resultado(6257, 1, uf="zz", municipio="30198"): _corpo(
                [("PL", "22", "FLAVIO", 100), ("PT", "13", "LULA", 20)]
            ),
        }
    )

    dados = svc_mundo.bake_mundo(cliente, loc, "1")

    assert set(dados["res"]) == {"PT", "JP"}
    assert dados["res"]["PT"][0][0] == "PT"
    assert dados["res"]["JP"][0][0] == "PL"
    assert dados["total"][0][:3] == ["PL", 55.0, 110]
    assert dados["paises"] == 2
    assert dados["cidades"] == 2


def test_bake_mundo_2_turno_sem_votos_nao_baixa_cidades() -> None:
    loc = LocalidadesFake([_municipio("29955", "Lisboa"), _municipio("30198", "Nagoya")])
    url_total = url_resultado(6258, 1, uf="zz")
    cliente = ClienteFake({url_total: _corpo([], st=0, ts=10)})

    dados = svc_mundo.bake_mundo(cliente, loc, "2")

    assert dados["res"] == {}
    assert dados["validos"] == {}
    assert dados["total"] is None
    assert cliente.pedidos == [url_total]


# --------------------------------------------------------------------------
# Geometria do mundo
# --------------------------------------------------------------------------


def test_mundo_para_paths_soma_mesmo_iso_e_usa_fallback() -> None:
    dados = mundo_para_paths(_geometria_mundo(), largura=1000, altura=1000, eps=0.0)

    assert set(dados["itens"]) == {"PT", "JP", "BR"}
    pt = dados["itens"]["PT"]
    assert pt["p"].count("M") == 2  # Portugal + Açores (ISO_A2_EH=-99 -> ISO_A2)
    assert pt["nome"] == "Portugal"
    assert pt["bb"][2] > 0 and pt["bb"][3] > 0
    assert dados["vb"][2] > 0 and dados["vb"][3] > 0


def test_mundo_para_paths_ignora_iso_invalido_e_antartida() -> None:
    malha = _geometria_mundo()
    malha["features"].append(
        {
            "type": "Feature",
            "properties": {"ISO_A2_EH": "-99", "ISO_A2": "-99", "NAME_PT": "Sem ISO"},
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        }
    )
    malha["features"].append(
        {
            "type": "Feature",
            "properties": {"ISO_A2_EH": "AQ", "ISO_A2": "AQ", "NAME_PT": "Antártida"},
            "geometry": {"type": "Polygon", "coordinates": [[[0, -80], [1, -80], [1, -70], [0, -80]]]},
        }
    )
    dados = mundo_para_paths(malha)
    assert "AQ" not in dados["itens"]


# --------------------------------------------------------------------------
# Payload do snapshot
# --------------------------------------------------------------------------


def test_coletar_mundo_monta_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc_mundo, "malha_mundo", lambda *a, **k: _geometria_mundo())

    cidades = [
        _municipio("29955", "Lisboa"),
        _municipio("30341", "Porto"),
        _municipio("30198", "Nagoya"),
    ]
    loc = LocalidadesFake(cidades)
    cliente = ClienteFake(
        {
            url_resultado(6257, 1, uf="zz"): _corpo(
                [("PT", "13", "LULA", 90), ("PL", "22", "FLAVIO", 110)]
            ),
            url_resultado(6257, 1, uf="zz", municipio="29955"): _corpo(
                [("PT", "13", "LULA", 60), ("PL", "22", "FLAVIO", 40)]
            ),
            url_resultado(6257, 1, uf="zz", municipio="30341"): _corpo(
                [("PT", "13", "LULA", 30), ("PL", "22", "FLAVIO", 70)]
            ),
            url_resultado(6257, 1, uf="zz", municipio="30198"): _corpo(
                [("PL", "22", "FLAVIO", 100), ("PT", "13", "LULA", 20)]
            ),
            url_resultado(6258, 1, uf="zz"): _corpo([], st=0, ts=10),
        }
    )

    dados = svc_mundo.coletar_mundo(cliente, loc)

    assert dados is not None
    assert dados["proj"]["nome"] == "mollweide"
    assert set(dados["paises"]) == {"PT", "JP", "BR"}
    assert dados["paises"]["PT"]["cidades"] == ["29955", "30341"]
    assert dados["paises"]["BR"]["cidades"] == []
    assert dados["meta"] == {"paises": 2, "cidades": 3}
    assert dados["res"]["1"]["PT"][0][0] == "PL"
    assert dados["res"]["2"] == {}
    assert dados["total"]["1"][0][0] == "PL"
    assert dados["total"]["2"] is None
