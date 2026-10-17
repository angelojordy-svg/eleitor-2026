"""Bake das finanças de campanha para o ranking.

Junta três fontes de dados abertos do TSE (via ``sources.contas``) num payload
único por candidato: receita, fundos (Fundo Partidário + FEFC), gasto pago e
patrimônio declarado.

O ZIP de contas é grande (~186 MB) e muda devagar, então o agregado caro fica
em cache por **impressão digital do arquivo local** (tamanho + mtime). O
download só reescreve o ZIP quando o arquivo remoto muda, o que invalida esse
cache automaticamente. Cadastro e bens são leves e relidos a cada execução.

Só entram candidatos com movimento de campanha (receita ou gasto > 0) —
decisão de produto: o ranking mostra "quem apareceu".
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from eleitor.sources import contas

# Versão do formato do cache em disco: mudar aqui força recalcular.
VERSAO_BAKE = 1


def dir_financas() -> Path:
    override = os.environ.get("ELEITOR_FINANCAS_DIR")
    if override:
        return Path(override)
    raiz = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if raiz:
        return Path(raiz) / "eleitor" / "financas"
    return Path.home() / ".cache" / "eleitor" / "financas"


def _arquivo_bake(ano: int) -> Path:
    pasta = dir_financas()
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta / f"contas-{ano}.json"


def _impressao(caminho: Path) -> dict[str, int]:
    stat = caminho.stat()
    return {"size": stat.st_size, "mtime": int(stat.st_mtime)}


def _ler_cache(ano: int) -> dict[str, Any] | None:
    caminho = _arquivo_bake(ano)
    if not caminho.exists():
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if dados.get("versao") != VERSAO_BAKE:
        return None
    return dados


def _gravar_cache(ano: int, dados: dict[str, Any]) -> None:
    caminho = _arquivo_bake(ano)
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(caminho)


def _agregar_contas(
    caminho_contas: Path,
    ano: int,
    forcar: bool,
    aviso: Callable[[str], None],
) -> tuple[dict[str, dict], dict[str, float], str]:
    """Receitas + despesas pagas, com cache caro por impressão do ZIP."""

    impressao = _impressao(caminho_contas)
    if not forcar:
        cache = _ler_cache(ano)
        if cache and cache.get("fonte") == impressao:
            aviso("Finanças — contas reaproveitadas do cache (arquivo do TSE não mudou).")
            return cache.get("por_cand", {}), cache.get("gasto", {}), cache.get("gerado_em", "")

    aviso("Finanças — lendo receitas (pode levar alguns minutos)...")
    por_cand, ponte, gerado_em = contas.parse_receitas(caminho_contas, ano)
    aviso("Finanças — lendo despesas pagas...")
    gasto = contas.parse_despesas_pagas(caminho_contas, ponte, ano)

    _gravar_cache(
        ano,
        {
            "versao": VERSAO_BAKE,
            "fonte": impressao,
            "gerado_em": gerado_em,
            "por_cand": por_cand,
            "gasto": gasto,
        },
    )
    return por_cand, gasto, gerado_em


def bake_financas(
    ano: int = contas.ANO_PADRAO,
    forcar: bool = False,
    progresso: Callable[[str], None] | None = None,
    caminhos: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Constrói o ranking de finanças por candidato.

    ``caminhos`` permite injetar os ZIPs já baixados (usado nos testes); quando
    omitido, baixa/reaproveita as três fontes.
    """

    def aviso(msg: str) -> None:
        if progresso:
            progresso(msg)

    if caminhos is None:
        def baixando(chave: str, baixado: int, total: int) -> None:
            if total:
                aviso(f"Finanças — baixando {chave} ({baixado * 100 // total}%)...")
            else:
                aviso(f"Finanças — baixando {chave}...")

        caminhos = contas.baixar_fontes(ano, forcar=forcar, progresso=baixando)

    por_cand, gasto, gerado_em = _agregar_contas(caminhos["contas"], ano, forcar, aviso)

    aviso("Finanças — lendo cadastro e bens...")
    cadastro = contas.parse_cadastro(caminhos["cadastro"], ano)
    bens = contas.parse_bens(caminhos["bens"], ano)

    itens: list[dict[str, Any]] = []
    for sq, cad in cadastro.items():
        receita = por_cand.get(sq, {})
        valor_receita = float(receita.get("receita", 0.0))
        valor_gasto = float(gasto.get(sq, 0.0))
        if valor_receita <= 0 and valor_gasto <= 0:
            continue
        fundo_partidario = float(receita.get("fp", 0.0))
        fundo_especial = float(receita.get("fefc", 0.0))
        itens.append(
            {
                "sq": sq,
                "nr": cad.get("numero", ""),
                "nome": cad.get("nome", ""),
                "partido": cad.get("partido", ""),
                "uf": cad.get("uf", ""),
                "cargo": cad.get("cargo", 0),
                "sit": cad.get("sit_tot", ""),
                "receita": round(valor_receita, 2),
                "fundos": round(fundo_partidario + fundo_especial, 2),
                "fp": round(fundo_partidario, 2),
                "fefc": round(fundo_especial, 2),
                "gasto": round(valor_gasto, 2),
                "bens": round(float(bens.get(sq, 0.0)), 2),
            }
        )
    itens.sort(key=lambda item: item["gasto"], reverse=True)

    return {
        "ano": ano,
        "gerado_em": gerado_em,
        "fonte": {chave: _impressao(caminho) for chave, caminho in caminhos.items()},
        "total": len(itens),
        "itens": itens,
    }
