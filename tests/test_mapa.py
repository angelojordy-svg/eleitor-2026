from __future__ import annotations

from typing import Any

import pytest

from eleitor.services import mapa as svc_mapa
from eleitor.sources import geo


# --------------------------------------------------------------------------
# Projeção e montagem do path do SVG
# --------------------------------------------------------------------------


def _malha_quadrados() -> dict[str, Any]:
    """Duas "UFs" quadradas, uma a oeste (15 = PA) e uma a leste (35 = SP)."""

    def quadrado(lon0: float, lon1: float, lat0: float, lat1: float) -> dict[str, Any]:
        return {
            "type": "Polygon",
            "coordinates": [
                [
                    [lon0, lat0],
                    [lon1, lat0],
                    [lon1, lat1],
                    [lon0, lat1],
                    [lon0, lat0],
                ]
            ],
        }

    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"codarea": "15"}, "geometry": quadrado(-60.0, -50.0, -10.0, 0.0)},
            {"type": "Feature", "properties": {"codarea": "35"}, "geometry": quadrado(-50.0, -40.0, -25.0, -15.0)},
        ],
    }


def test_geo_para_paths_gera_path_bb_e_centroide() -> None:
    itens, transformacao = geo.geo_para_paths(_malha_quadrados(), largura=1000, altura=1000)

    assert set(itens) == {"15", "35"}
    for codigo, info in itens.items():
        assert info["p"].startswith("M") and info["p"].endswith("Z")
        assert info["bb"][2] > 0 and info["bb"][3] > 0, f"{codigo} sem caixa envolvente"
        assert 0 <= info["cx"] <= 1000 and 0 <= info["cy"] <= 1000
    assert transformacao["escala"] > 0

    # O quadrado oeste tem que ficar à esquerda do leste.
    assert itens["15"]["cx"] < itens["35"]["cx"]


def test_geo_para_paths_nao_estoura_com_geometria_vazia() -> None:
    with pytest.raises(geo.GeoError):
        geo.geo_para_paths({"type": "FeatureCollection", "features": []})


def test_multi_polygon_e_simplificacao() -> None:
    malha = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"codarea": "99"},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
                        [[[3.0, 3.0], [4.0, 3.0], [4.0, 4.0], [3.0, 4.0], [3.0, 3.0]]],
                    ],
                },
            }
        ],
    }
    itens, _ = geo.geo_para_paths(malha)
    assert "99" in itens
    assert itens["99"]["p"].count("M") == 2  # dois anéis => dois subpaths


def test_urls_do_ibge() -> None:
    assert "intrarregiao=UF" in geo.url_malha_ufs()
    assert "/estados/PA" in geo.url_malha_municipios("pa")


# --------------------------------------------------------------------------
# Resumo por UF (líder + força da maioria)
# --------------------------------------------------------------------------


def test_top2_calcula_percentual_sobre_os_validos() -> None:
    resultado = {
        "cands": [
            {"n": "20", "nome": "A", "p": "PODE", "v": 600, "pct": 60.0, "e": True},
            {"n": "15", "nome": "B", "p": "MDB", "v": 400, "pct": 40.0, "e": False},
            {"n": "50", "nome": "C", "p": "PSOL", "v": 0, "pct": 0.0, "e": False},
        ],
        "votos": {"validos": 1000},
        "tot": {"st": 80, "ts": 100, "pct": 80.0},
    }
    topo = svc_mapa._top2(resultado)
    assert topo == [["PODE", 60.0, 600, "A", 80], ["MDB", 40.0, 400, "B", 80]]


def test_top2_sem_dados() -> None:
    assert svc_mapa._top2(None) is None
    assert svc_mapa._top2({"cands": []}) is None


# --------------------------------------------------------------------------
# coletar_mapa (sem rede)
# --------------------------------------------------------------------------


class ClienteFake:
    def __init__(self, corpos: dict[str, Any]) -> None:
        self.corpos = corpos
        self.pedidos: list[str] = []

    def get_json(self, url: str, ttl: float = 0.0, allow_404: bool = False) -> Any:
        self.pedidos.append(url)
        return self.corpos.get(url)

    def get_urls(self, urls: list[str], ttl: float = 0.0, allow_404: bool = True) -> dict[str, Any]:
        return {url: self.get_json(url) for url in urls}


def _corpo(cands: list[tuple[str, int, str]]) -> dict[str, Any]:
    """Monta um EA20 mínimo: [(sigla, votos, nome)]."""

    return {
        "ele": 6259,
        "carg": [
            {
                "cd": "3",
                "nmn": "Governador",
                "nv": "1",
                "agr": [
                    {
                        "par": [
                            {"sg": sigla, "cand": [{"n": str(i + 10), "nm": nome, "nmu": nome, "vap": str(votos)}]}
                            for i, (sigla, votos, nome) in enumerate(cands)
                        ]
                    }
                ],
            }
        ],
        "v": {"vv": str(sum(v for _, v, _ in cands))},
        "s": {"ts": "100", "st": "100", "pst": "100,00"},
        "dg": "05/10/2026",
        "hg": "11:00:00",
    }


def test_coletar_mapa_monta_geometria_e_resumo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc_mapa, "malha_ufs", lambda *a, **k: _malha_quadrados())

    url_pa = svc_mapa.url_resultado(6259, 3, uf="pa")
    url_sp = svc_mapa.url_resultado(6259, 3, uf="sp")
    cliente = ClienteFake(
        {
            url_pa: _corpo([("PODE", 600, "DR. DANIEL"), ("MDB", 400, "HANA GHASSAN")]),
            url_sp: _corpo([("PT", 700, "FERNANDO HADDAD"), ("REPUBLICANOS", 300, "TARCÍSIO")]),
        }
    )
    estados = [
        {
            "uf": "pa",
            "nome": "Pará",
            "cargos": {
                "3": {
                    "tot": {"st": 100, "ts": 100, "pct": 100.0},
                    "cands": [
                        {"n": "20", "nome": "DR. DANIEL", "p": "PODE", "v": 600, "pct": 60.0, "e": True},
                        {"n": "15", "nome": "HANA GHASSAN", "p": "MDB", "v": 400, "pct": 40.0, "e": False},
                    ],
                    "votos": {"validos": 1000},
                }
            },
        },
        {"uf": "sp", "nome": "São Paulo", "cargos": {}},
    ]

    mapa = svc_mapa.coletar_mapa(cliente, estados, com_turno2=False)

    assert mapa is not None
    assert set(mapa["uf"]) == {"PA", "SP"}  # códigos IBGE 15/35 mapeados para siglas
    assert mapa["escala"] == {"min": 30.0, "max": 70.0}
    assert mapa["res"]["3"]["1"]["PA"] == [
        ["PODE", 60.0, 600, "DR. DANIEL", 100],
        ["MDB", 40.0, 400, "HANA GHASSAN", 100],
    ]
    assert "SP" not in mapa["res"]["3"]["1"]  # sem cargos no snapshot => fora do recorte
    assert mapa["brasil"]["1"]["1"] is None
    # viewBox cobre os dois quadrados
    x, y, w, h = mapa["proj"]["viewBox"]
    assert w > 0 and h > 0


def test_coletar_mapa_sem_geometria_devolve_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*a: Any, **k: Any) -> dict[str, Any]:
        raise geo.GeoError("sem internet")

    monkeypatch.setattr(svc_mapa, "malha_ufs", explode)
    assert svc_mapa.coletar_mapa(ClienteFake({}), [], com_turno2=False) is None


# --------------------------------------------------------------------------
# Líder por município (bake)
# --------------------------------------------------------------------------


class LocalidadesFake:
    def __init__(self, municipios: list[Any]) -> None:
        self.municipios = municipios


def _municipio(uf: str, codigo: str, ibge: str, nome: str) -> Any:
    from eleitor.models import Municipio

    return Municipio(uf=uf, codigo=codigo, ibge=ibge, nome=nome, zonas=["0001"])


def test_bake_resultado_municipios(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("ELEITOR_MAPA_DIR", str(tmp_path))
    loc = LocalidadesFake(
        [
            _municipio("pa", "04154", "1505502", "PARAUAPEBAS"),
            _municipio("pa", "05835", "1500800", "ANANINDEUA"),
            _municipio("mt", "98930", "5107925", "SORRISO"),
        ]
    )
    url_pa = svc_mapa.url_resultado(6259, 3, uf="pa", municipio="04154")
    url_an = svc_mapa.url_resultado(6259, 3, uf="pa", municipio="05835")
    url_mt = svc_mapa.url_resultado(6259, 3, uf="mt", municipio="98930")
    cliente = ClienteFake(
        {
            url_pa: _corpo([("PODE", 600, "DR. DANIEL"), ("MDB", 400, "HANA GHASSAN")]),
            url_an: _corpo([("PODE", 700, "DR. DANIEL"), ("MDB", 300, "HANA GHASSAN")]),
            url_mt: _corpo([("PL", 500, "WELLINGTON"), ("REPUBLICANOS", 500, "OTAVIANO")]),
        }
    )

    por_uf = svc_mapa.bake_resultado_municipios(cliente, loc, "3", "1", ["pa", "mt"])
    assert set(por_uf) == {"PA", "MT"}
    assert por_uf["PA"]["1505502"] == [["PODE", 60.0, 600, "DR. DANIEL", 100]]
    assert por_uf["PA"]["1500800"][0] == ["PODE", 70.0, 700, "DR. DANIEL", 100]
    assert por_uf["MT"]["5107925"] == [["PL", 50.0, 500, "WELLINGTON", 100]]

    # segunda chamada usa o cache do bake (nenhuma requisição nova)
    antes = len(cliente.pedidos)
    svc_mapa.bake_resultado_municipios(cliente, loc, "3", "1", ["pa", "mt"])
    assert len(cliente.pedidos) == antes


def test_bake_2_turno_guarda_os_dois_candidatos(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("ELEITOR_MAPA_DIR", str(tmp_path))
    loc = LocalidadesFake([_municipio("pa", "04154", "1505502", "PARAUAPEBAS")])
    url = svc_mapa.url_resultado(6258, 1, uf="pa", municipio="04154")
    cliente = ClienteFake({url: _corpo([("PL", 5200, "FLAVIO BOLSONARO"), ("PT", 4800, "LULA")])})

    por_uf = svc_mapa.bake_resultado_municipios(cliente, loc, "1", "2", ["pa"])
    topo = por_uf["PA"]["1505502"]
    assert [linha[0] for linha in topo] == ["PL", "PT"]
    assert topo[0][1] == 52.0 and topo[1][1] == 48.0


def test_combo_sem_votos_fica_fora_do_bake() -> None:
    mapa = {
        "res": {
            "1": {"1": {"PA": [["PL", 0.0, 0, "X"]]}, "2": {"PA": [["PL", 0.0, 0, "FLAVIO"]]}},
            "3": {"1": {}},
        }
    }
    combos = svc_mapa.combos_com_dados(mapa)
    assert ("1", "1") in combos
    assert ("3", "1") in combos
    assert ("1", "2") not in combos  # 2º turno ainda sem votos
    assert ("3", "2") not in combos



def test_apuracao_derivada_de_secoes_quando_falta_pct() -> None:
    assert svc_mapa._apuracao({'tot': {'st': 25, 'ts': 100}}) == 25
    assert svc_mapa._apuracao({'tot': {'st': 100, 'ts': 100, 'pct': 100.0}}) == 100
    assert svc_mapa._apuracao(None) == 0
    assert svc_mapa._apuracao({'tot': {'st': 0, 'ts': 0}}) == 0
