"""Prévia do 2º turno no exterior a partir dos Boletins de Urna (BU).

O TSE só totaliza o exterior depois das 17h de Brasília, mas os BUs das seções
que já fecharam ficam disponíveis no ``arquivo-urna`` do pleito **3221**. Aqui
os BUs são somados por cidade/país para uma prévia -- não é o resultado
oficial e não substitui a totalização.

O cache é **incremental por seção** (``mundo-bu-t2.json``): o BU é imutável e
só as seções novas recebidas aparecem no config 3221.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from eleitor.config import PLEITO_SEGUNDO, TTL_AUX, TTL_SECOES
from eleitor.http import CachedClient
from eleitor.paises import CIDADE_PAIS
from eleitor.services.mapa import dir_dados
from eleitor.sources.bu import parse_bu
from eleitor.sources.resultados import (
    parse_resultado,
    url_resultado,
    url_secao_aux,
    url_secoes_config,
)
from eleitor.sources.urna import arquivo_bu, arquivos_urna, url_arquivo_urna

CACHE_VERSAO = 1
# TRE-DF/G1: 1.282 urnas eletrônicas no exterior no 2º turno. O config 3221
# tem 1.351 seções principais (inclui manuais/agregadas que não geram BU).
SECOES_ELETRONICAS_2T = 1282

CANDIDATOS_FALLBACK = {
    "13": {"p": "PT", "nome": "LULA"},
    "22": {"p": "PL", "nome": "FLAVIO BOLSONARO"},
}


def _cache_path() -> Path:
    destino = dir_dados()
    destino.mkdir(parents=True, exist_ok=True)
    return destino / "mundo-bu-t2.json"


def _ler_cache() -> dict[str, Any]:
    caminho = _cache_path()
    if not caminho.exists():
        return {"versao": CACHE_VERSAO, "secoes": {}}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"versao": CACHE_VERSAO, "secoes": {}}
    if dados.get("versao") != CACHE_VERSAO or not isinstance(dados.get("secoes"), dict):
        return {"versao": CACHE_VERSAO, "secoes": {}}
    return dados


def _gravar_cache(cache: dict[str, Any], config_gerado: str) -> None:
    cache["versao"] = CACHE_VERSAO
    cache["gerado_em"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    cache["config_gerado"] = config_gerado
    caminho = _cache_path()
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(cache, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tmp.replace(caminho)


def _ler_cidades(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Cidades do exterior e as seções principais (com/sem BU)."""

    cidades: dict[str, dict[str, Any]] = {}
    for abr in data.get("abr", []):
        if str(abr.get("cd", "")).lower() != "zz":
            continue
        for mu in abr.get("mu", []):
            codigo = str(mu.get("cd", "")).strip().zfill(5)
            info = {
                "nome": mu.get("nm", ""),
                "iso": CIDADE_PAIS.get(codigo),
                "secoes_total": 0,
                "secoes": [],
            }
            for zona in mu.get("zon", []):
                zona_cd = str(zona.get("cd", "")).zfill(4)
                for sec in zona.get("sec", []):
                    # Seções agregadas em outra não têm BU própria e não entram
                    # no total de urnas (o TSE totaliza pela principal).
                    if sec.get("nsp"):
                        continue
                    info["secoes_total"] += 1
                    if sec.get("da"):
                        info["secoes"].append(
                            {
                                "zona": zona_cd,
                                "secao": str(sec.get("ns", "")).zfill(4),
                            }
                        )
            cidades[codigo] = info
    return cidades


def _candidatos(client: CachedClient, ttl: float) -> dict[str, dict[str, str]]:
    """Nomes/partidos do 2º turno (o agregado tem os candidatos mesmo com 0)."""

    try:
        body = client.get_json(
            url_resultado(6258, 1, uf="zz"),
            ttl=ttl,
            allow_404=True,
        )
        if body:
            res = parse_resultado(body)
            return {
                cand.numero: {
                    "p": cand.partido,
                    "nome": cand.nome_urna or cand.nome,
                }
                for cand in res.candidatos
            }
    except Exception:
        pass
    return dict(CANDIDATOS_FALLBACK)


def _fetch_aux_bu(
    client: CachedClient,
    item: tuple[str, str, str],
    ttl: float,
) -> tuple[tuple[str, str, str], dict | None]:
    codigo, zona, secao = item
    try:
        aux = client.get_json(
            url_secao_aux("zz", codigo, zona, secao, pleito=PLEITO_SEGUNDO),
            ttl=ttl,
            allow_404=True,
        )
    except Exception:
        return item, None
    if not aux:
        return item, None
    for arq in arquivos_urna(aux):
        nome = arquivo_bu(arq.get("arquivos") or [])
        hash_urna = arq.get("hash")
        if not nome or not hash_urna:
            continue
        try:
            raw = client.get_bytes(
                url_arquivo_urna(
                    "zz",
                    codigo,
                    zona,
                    secao,
                    hash_urna,
                    nome,
                    pleito=PLEITO_SEGUNDO,
                ),
                ttl=ttl,
                allow_404=True,
            )
            if raw:
                return item, parse_bu(raw)
        except Exception:
            return item, None
    return item, None


def _secao_do_bu(dados: dict[str, Any]) -> dict[str, Any] | None:
    cargo = (dados.get("cargos") or {}).get(1)
    if not cargo:
        return None
    votos: dict[str, int] = {}
    brancos = nulos = 0
    for voto in cargo.get("votos", []):
        tipo = voto.get("tipo")
        if tipo == "nominal":
            codigo = str(voto.get("codigo", ""))
            if codigo:
                votos[codigo] = votos.get(codigo, 0) + int(voto.get("votos", 0))
        elif tipo == "branco":
            brancos += int(voto.get("votos", 0))
        elif tipo == "nulo":
            nulos += int(voto.get("votos", 0))
    return {
        "votos": votos,
        "brancos": brancos,
        "nulos": nulos,
        "comparecimento": int(cargo.get("comparecimento", 0) or 0),
        "aptos": int(cargo.get("aptos", 0) or 0),
    }


def _topo(
    cands: dict[str, int],
    validos: int,
    candidatos: dict[str, dict[str, str]],
) -> list[list[Any]] | None:
    if validos <= 0 or not cands:
        return None
    ordenados = sorted(cands.items(), key=lambda item: item[1], reverse=True)[:2]
    itens: list[list[Any]] = []
    for codigo, votos in ordenados:
        info = candidatos.get(codigo, {})
        itens.append(
            [
                info.get("p", ""),
                round(votos * 100.0 / validos, 2),
                votos,
                info.get("nome", codigo),
                0,  # apuração oficial ainda não começou; a cobertura é à parte
            ]
        )
    return itens


def _agregar(
    cidades: dict[str, dict[str, Any]],
    secoes: dict[str, Any],
    candidatos: dict[str, dict[str, str]],
) -> tuple[dict[str, list[list[Any]]], dict[str, int], list[list[Any]] | None, dict[str, Any]]:
    por_pais: dict[str, dict[str, Any]] = {}
    lidas_pais: dict[str, int] = {}
    secoes_pais: dict[str, int] = {}
    for codigo, info in cidades.items():
        iso = info.get("iso")
        if not iso:
            continue
        secoes_pais[iso] = secoes_pais.get(iso, 0) + int(info.get("secoes_total", 0))
        lidas_pais.setdefault(iso, 0)

    total_cands: dict[str, int] = {}
    total_validos = 0
    for dados in secoes.values():
        codigo = str(dados.get("municipio", "")).zfill(5)
        info = cidades.get(codigo)
        iso = info.get("iso") if info else None
        votos = dados.get("votos") or {}
        validos = sum(int(v) for v in votos.values())
        if iso:
            lidas_pais[iso] = lidas_pais.get(iso, 0) + 1
            acc = por_pais.setdefault(iso, {"cands": {}, "validos": 0})
            acc["validos"] += validos
            for numero, quantidade in votos.items():
                acc["cands"][numero] = acc["cands"].get(numero, 0) + int(quantidade)
        total_validos += validos
        for numero, quantidade in votos.items():
            total_cands[numero] = total_cands.get(numero, 0) + int(quantidade)

    res: dict[str, list[list[Any]]] = {}
    validos_paises: dict[str, int] = {}
    for iso, acc in por_pais.items():
        topo = _topo(acc["cands"], acc["validos"], candidatos)
        if topo:
            res[iso] = topo
            validos_paises[iso] = acc["validos"]

    cobertura = {
        "total": {
            "lidas": len(secoes),
            "secoes": sum(secoes_pais.values()),
            "eletronicas": SECOES_ELETRONICAS_2T,
        },
        "paises": {
            iso: {"lidas": lidas_pais.get(iso, 0), "secoes": total}
            for iso, total in secoes_pais.items()
        },
    }
    return res, validos_paises, _topo(total_cands, total_validos, candidatos), cobertura


def bake_mundo_bu(
    client: CachedClient,
    progresso: Callable[[str], None] | None = None,
    refazer: bool = False,
) -> dict[str, Any] | None:
    """Lê os BUs disponíveis do pleito 3221 e agrega por país.

    Devolve ``None`` se não houver config/BUs. O resultado é preliminar: as
    seções sem BU (manuais/atrasadas) ficam de fora e são mostradas na
    cobertura.
    """

    def aviso(msg: str) -> None:
        if progresso:
            progresso(msg)

    ttl = 0.0 if refazer else TTL_AUX
    if refazer:
        caminho = _cache_path()
        if caminho.exists():
            caminho.unlink()

    try:
        data = client.get_json(
            url_secoes_config("zz", pleito=PLEITO_SEGUNDO),
            ttl=0.0 if refazer else TTL_SECOES,
        )
    except Exception as exc:
        aviso(f"Mundo BU — config 3221 indisponível: {exc}")
        return None
    if not data:
        return None

    cidades = _ler_cidades(data)
    secoes_config = [
        (codigo, sec["zona"], sec["secao"])
        for codigo, info in cidades.items()
        for sec in info["secoes"]
    ]
    if not secoes_config:
        aviso("Mundo BU — nenhuma urna com BU disponível neste momento.")
        return None

    config_gerado = f"{data.get('dg', '')} {data.get('hg', '')}".strip()
    cache = _ler_cache()
    cache.setdefault("secoes", {})
    pendentes = [
        item
        for item in secoes_config
        if f"{item[0]}/{item[1]}/{item[2]}" not in cache["secoes"]
    ]
    total = len(secoes_config)
    lidas = total - len(pendentes)
    if pendentes:
        aviso(
            f"Mundo BU — {lidas} já em cache; baixando {len(pendentes)} de "
            f"{total} urnas disponíveis..."
        )
    else:
        aviso(f"Mundo BU — {lidas} urnas já em cache.")

    antigo_ritmo = getattr(client, "min_interval", None)
    antigos_workers = getattr(client, "workers", None)
    if antigo_ritmo is not None:
        client.min_interval = 0.04  # ~25 req/s, bem abaixo do limite de 100/s
    if antigos_workers is not None:
        client.workers = 8
    try:
        if pendentes:
            with ThreadPoolExecutor(max_workers=max(1, int(getattr(client, "workers", 4) or 4))) as pool:
                for feitos, (item, dados_bu) in enumerate(
                    pool.map(lambda it: _fetch_aux_bu(client, it, ttl), pendentes),
                    1,
                ):
                    if dados_bu:
                        secao = _secao_do_bu(dados_bu)
                        if secao:
                            chave = f"{item[0]}/{item[1]}/{item[2]}"
                            cache["secoes"][chave] = {
                                "municipio": int(item[0]),
                                **secao,
                            }
                    if feitos % 30 == 0 or feitos == len(pendentes):
                        aviso(f"Mundo BU — {feitos}/{len(pendentes)} urnas baixadas...")
                        _gravar_cache(cache, config_gerado)
    finally:
        if antigo_ritmo is not None:
            client.min_interval = antigo_ritmo
        if antigos_workers is not None:
            client.workers = antigos_workers

    _gravar_cache(cache, config_gerado)
    if not cache["secoes"]:
        return None

    candidatos = _candidatos(client, ttl)
    res, validos, total_topo, cobertura = _agregar(cidades, cache["secoes"], candidatos)
    aviso(
        f"Mundo BU — prévia com {cobertura['total']['lidas']} de "
        f"{SECOES_ELETRONICAS_2T} urnas eletrônicas."
    )
    return {
        "res": res,
        "validos": validos,
        "total": total_topo,
        "cobertura": cobertura,
        "meta": {
            "fonte": "BU 2º turno (preliminar)",
            "secoes_lidas": cobertura["total"]["lidas"],
            "secoes_total": cobertura["total"]["secoes"],
            "secoes_eletronicas": SECOES_ELETRONICAS_2T,
            "config_gerado": config_gerado,
            "gerado_em": cache.get("gerado_em"),
        },
    }


def comparar_mundo(bu: dict[str, Any] | None, oficial: dict[str, Any] | None) -> dict[str, Any]:
    """Compara a prévia BU com o resultado oficial do 2º turno."""

    if not bu:
        return {"oficial_disponivel": False, "bu": None, "paises": [], "total": None}
    oficial_total = (oficial or {}).get("total")
    oficial_disponivel = bool(
        oficial_total and oficial_total[0] and oficial_total[0][2] > 0
    )
    bu_total = bu.get("total")
    total = {
        "bu": bu_total,
        "oficial": oficial_total if oficial_disponivel else None,
        "dif_lider": (
            bu_total[0][2] - oficial_total[0][2]
            if bu_total and oficial_disponivel and oficial_total
            else None
        ),
    }
    paises: list[dict[str, Any]] = []
    for iso, bu_topo in (bu.get("res") or {}).items():
        of_topo = ((oficial or {}).get("res") or {}).get(iso)
        cob = ((bu.get("cobertura") or {}).get("paises") or {}).get(iso, {})
        paises.append(
            {
                "iso": iso,
                "bu": bu_topo,
                "oficial": of_topo if (of_topo and of_topo[0] and of_topo[0][2] > 0) else None,
                "cobertura": cob,
                "dif_lider": (
                    bu_topo[0][2] - of_topo[0][2]
                    if of_topo and of_topo[0] and of_topo[0][2] > 0
                    else None
                ),
            }
        )
    return {
        "oficial_disponivel": oficial_disponivel,
        "bu": bu.get("meta"),
        "oficial": (oficial or {}).get("total"),
        "total": total,
        "paises": paises,
    }
