from __future__ import annotations

import io
import os

import pytest
from PIL import Image

from eleitor.services import fundo_offline as fo
from fixtures_planilha import planilha_exemplo
from eleitor.services.mapa_urnas import construir_payload


def _tile_png() -> bytes:
    imagem = Image.frombytes("RGB", (256, 256), os.urandom(256 * 256 * 3))
    buffer = io.BytesIO()
    imagem.save(buffer, format="PNG")
    return buffer.getvalue()


_TILE = _tile_png()


class _Resposta:
    status_code = 200

    def __init__(self, conteudo: bytes):
        self.content = conteudo


class _ClienteFalso:
    def __init__(self, *args, **kwargs):
        self.chamadas = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url):
        self.chamadas += 1
        return _Resposta(_TILE)


def test_tile_bounds_do_mundo():
    sul, oeste, norte, leste = fo.tile_bounds(0, 0, 0)
    assert sul == pytest.approx(-85.05112878, abs=1e-6)
    assert oeste == pytest.approx(-180.0)
    assert norte == pytest.approx(85.05112878, abs=1e-6)
    assert leste == pytest.approx(180.0)


def test_tile_range_cobre_parauapebas_sem_explodir():
    bbox = (-6.259793, -50.8033353, -5.9138581, -49.8372992)
    x0, x1, y0, y1 = fo.tile_range(bbox, 12)
    assert x0 <= x1 and y0 <= y1
    assert (x1 - x0 + 1) * (y1 - y0 + 1) <= 100
    bounds = fo.bounds_mosaico(12, x0, x1, y0, y1)
    assert bounds[0][0] < bounds[1][0]
    assert bounds[0][1] < bounds[1][1]
    assert bounds[0][0] <= bbox[0] and bounds[0][1] <= bbox[1]
    assert bounds[1][0] >= bbox[2] and bounds[1][1] >= bbox[3]


def test_bbox_locais_e_detalhe():
    locais = [
        {"lat": -6.06, "lon": -49.90},
        {"lat": -6.08, "lon": -49.88},
    ]
    bbox = fo._bbox_locais(locais)
    assert bbox == (-6.08, -49.90, -6.06, -49.88)
    perto = fo._bbox_locais(locais, raio_km=1)
    assert perto == bbox


def test_gerar_camada_costura_e_reaproveita_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEITOR_FUNDO_DIR", str(tmp_path))
    bbox = (-6.070, -49.900, -6.069, -49.899)

    cliente = _ClienteFalso()
    camada = fo._gerar_camada(
        cliente, bbox, 12, "osm", 85, "teste", False, None
    )
    assert camada.url.startswith("data:image/jpeg;base64,")
    assert camada.largura % 256 == 0
    assert camada.altura % 256 == 0
    assert camada.largura > 0 and camada.altura > 0
    assert cliente.chamadas > 0

    cliente2 = _ClienteFalso()
    camada2 = fo._gerar_camada(
        cliente2, bbox, 12, "osm", 85, "teste", False, None
    )
    assert cliente2.chamadas == 0
    assert camada2.url == camada.url
    assert list(tmp_path.glob("teste_z12_*.jpg"))


def test_gerar_fundo_com_cliente_falso(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEITOR_FUNDO_DIR", str(tmp_path))
    monkeypatch.setattr(fo.httpx, "Client", _ClienteFalso)
    payload = construir_payload(planilha_exemplo())

    fundo = fo.gerar_fundo(
        payload,
        zoom_baixo=12,
        zoom_detalhe=12,
        raio_detalhe_km=8,
        qualidade=85,
        refazer=True,
    )
    assert fundo.baixo is not None
    assert fundo.baixo.url.startswith("data:image/jpeg;base64,")
    assert fundo.attr == fo.ATTR_OSM
    dados = fundo.para_dict()
    assert dados["baixo"]["bounds"]
    assert dados["alto"] is None or dados["alto"]["bounds"]


def test_gerar_fundo_sem_locais(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEITOR_FUNDO_DIR", str(tmp_path))
    monkeypatch.setattr(fo.httpx, "Client", _ClienteFalso)
    with pytest.raises(fo.FundoOfflineError):
        fo.gerar_fundo({"locais": [], "meta": {}})


def test_dir_cache_respeita_ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEITOR_FUNDO_DIR", str(tmp_path))
    assert fo.dir_cache() == tmp_path
