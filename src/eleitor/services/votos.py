from __future__ import annotations

from eleitor.config import TTL_AUX, TTL_LIVE, TTL_SECOES
from eleitor.http import CachedClient, NotFound
from eleitor.models import Candidato, Municipio, ResultadoCargo, ZonaSecoes
from eleitor.sources.bu import parse_bu
from eleitor.sources.resultados import (
    parse_aux,
    parse_resultado,
    parse_secoes,
    url_resultado,
    url_secao_aux,
    url_secoes_config,
)
from eleitor.sources.urna import arquivo_bu, arquivos_urna, url_arquivo_urna


def resultado(
    client: CachedClient,
    eleicao: int,
    cargo: int,
    uf: str | None = None,
    municipio: str | None = None,
    zona: str | None = None,
    ttl: float = TTL_LIVE,
) -> ResultadoCargo:
    url = url_resultado(eleicao, cargo, uf=uf, municipio=municipio, zona=zona)
    data = client.get_json(url, ttl=ttl)
    return parse_resultado(data or {})


def resultados_zonas(
    client: CachedClient,
    eleicao: int,
    cargo: int,
    municipio: Municipio,
    ttl: float = TTL_LIVE,
) -> list[tuple[str, ResultadoCargo | None]]:
    urls = [url_resultado(eleicao, cargo, uf=municipio.uf, municipio=municipio.codigo, zona=z) for z in municipio.zonas]
    data = client.get_urls(urls, ttl=ttl, allow_404=True)
    resultados: list[tuple[str, ResultadoCargo | None]] = []
    for zona, url in zip(municipio.zonas, urls):
        body = data.get(url)
        resultados.append((zona, parse_resultado(body) if body else None))
    return resultados


def secoes(
    client: CachedClient,
    uf: str,
    municipio: str,
    zona: str | None = None,
    com_status: bool = True,
    ttl: float = TTL_SECOES,
) -> list[ZonaSecoes]:
    data = client.get_json(url_secoes_config(uf), ttl=ttl)
    zonas = parse_secoes(data or {}, uf, municipio)
    if zona is not None:
        zonas = [z for z in zonas if z.zona == f"{int(zona):04d}"]

    if not com_status:
        return zonas

    urls: list[tuple[object, str]] = []
    for z in zonas:
        for sec in z.secoes:
            if sec.principal is not None:
                continue
            if not sec.data_aux:
                continue
            urls.append((sec, url_secao_aux(uf, municipio, z.zona, sec.numero)))

    if urls:
        bodies = client.get_urls([u for _, u in urls], ttl=TTL_AUX, allow_404=True)
        for sec, url in urls:
            body = bodies.get(url)
            if body:
                sec.status, sec.urnas = parse_aux(body)
    return zonas


def status_aux(
    client: CachedClient,
    uf: str,
    municipio: str,
    zona: str,
    secao: str,
) -> tuple[str, int] | None:
    url = url_secao_aux(uf, municipio, zona, secao)
    try:
        data = client.get_json(url, ttl=TTL_AUX, allow_404=True)
    except NotFound:
        return None
    if not data:
        return None
    return parse_aux(data)


def votos_secao(
    client: CachedClient,
    uf: str,
    municipio: str,
    zona: str,
    secao: str,
    ttl: float = TTL_AUX,
) -> dict | None:
    aux = client.get_json(url_secao_aux(uf, municipio, zona, secao), ttl=ttl, allow_404=True)
    if not aux:
        return None
    for item in arquivos_urna(aux):
        nome = arquivo_bu(item.get("arquivos") or [])
        hash_urna = item.get("hash")
        if not nome or not hash_urna:
            continue
        url = url_arquivo_urna(uf, municipio, zona, secao, hash_urna, nome)
        raw = client.get_bytes(url, allow_404=True)
        if not raw:
            continue
        dados = parse_bu(raw)
        dados["status"] = item.get("status")
        return dados
    return None


def votos_secoes_zona(
    client: CachedClient,
    uf: str,
    municipio: str,
    zona: str,
    ttl: float = TTL_AUX,
) -> dict[str, dict]:
    zonas = secoes(client, uf, municipio, zona=zona, ttl=ttl)
    if not zonas:
        return {}
    alvos = [s for s in zonas[0].secoes if s.data_aux and s.principal is None]
    urls_aux = [url_secao_aux(uf, municipio, zona, s.numero) for s in alvos]
    auxiliares = client.get_urls(urls_aux, ttl=ttl, allow_404=True)

    downloads: list[tuple[str, str]] = []
    for sec, url_aux in zip(alvos, urls_aux):
        aux = auxiliares.get(url_aux)
        if not aux:
            continue
        for item in arquivos_urna(aux):
            nome = arquivo_bu(item.get("arquivos") or [])
            hash_urna = item.get("hash")
            if not nome or not hash_urna:
                continue
            downloads.append((sec.numero, url_arquivo_urna(uf, municipio, zona, sec.numero, hash_urna, nome)))
            break

    if not downloads:
        return {}
    corpos = client.get_urls_bytes([u for _, u in downloads], allow_404=True)
    resultado: dict[str, dict] = {}
    for secao, url in downloads:
        raw = corpos.get(url)
        if not raw:
            continue
        try:
            resultado[secao] = parse_bu(raw)
        except Exception:
            continue
    return resultado

