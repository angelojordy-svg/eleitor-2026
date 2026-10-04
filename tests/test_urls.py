from eleitor.sources.resultados import (
    url_acompanhamento,
    url_foto,
    url_municipios_config,
    url_resultado,
    url_secao_aux,
    url_secoes_config,
)


def test_url_presidente_brasil():
    assert (
        url_resultado(6257, 1)
        == "https://resultados.tse.jus.br/oficial/ele2026/6257/dados/br/br-c0001-e006257-u.json"
    )


def test_url_governador_uf():
    assert (
        url_resultado(6259, 3, uf="PA")
        == "https://resultados.tse.jus.br/oficial/ele2026/6259/dados/pa/pa-c0003-e006259-u.json"
    )


def test_url_dep_federal_municipio_parauapebas():
    assert (
        url_resultado(6259, 6, uf="pa", municipio="5835")
        == "https://resultados.tse.jus.br/oficial/ele2026/6259/dados/pa/pa05835-c0006-e006259-u.json"
    )


def test_url_zona_parauapebas():
    assert (
        url_resultado(6259, 6, uf="pa", municipio="5835", zona="75")
        == "https://resultados.tse.jus.br/oficial/ele2026/6259/dados/pa/pa05835-z0075-c0006-e006259-u.json"
    )


def test_url_acompanhamento():
    assert (
        url_acompanhamento(6259, "pa")
        == "https://resultados.tse.jus.br/oficial/ele2026/6259/dados/pa/pa-e006259-ab.json"
    )
    assert (
        url_acompanhamento(6257)
        == "https://resultados.tse.jus.br/oficial/ele2026/6257/dados/br/br-e006257-ab.json"
    )


def test_url_municipios_config():
    assert (
        url_municipios_config()
        == "https://resultados.tse.jus.br/oficial/ele2026/6259/config/mun-e006259-cm.json"
    )


def test_url_foto():
    assert (
        url_foto(6257, None, "280002542548")
        == "https://resultados.tse.jus.br/oficial/ele2026/6257/fotos/br/280002542548.jpeg"
    )
    assert (
        url_foto(6259, "PA", "140002554108")
        == "https://resultados.tse.jus.br/oficial/ele2026/6259/fotos/pa/140002554108.jpeg"
    )


def test_url_secoes_config():
    assert (
        url_secoes_config("PA")
        == "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3220/config/pa/pa-p003220-cs.json"
    )


def test_url_secao_aux():
    assert (
        url_secao_aux("pa", "5835", "75", "1")
        == "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3220/dados/pa/05835/0075/0001/p003220-pa-m05835-z0075-s0001-aux.json"
    )
