"""Prestação de contas de campanha, cadastro e bens (dados abertos do TSE).

Três fontes, todas CSV em ISO-8859-1 com separador ``;``:

- contas de candidatos (receitas e despesas pagas);
- cadastro de candidatos (``consulta_cand``): cargo, partido, situação;
- bens declarados (``bem_candidato``): patrimônio.

O ZIP de contas passa de 180 MB, então o download vai para disco com uma
**impressão digital** (tamanho + ``Last-Modified``) e a leitura é em streaming,
direto do ZIP, sem descompactar. Quando existe a variante ``BRASIL`` do
arquivo, ela é a única lida — assim o Brasil inteiro é processado uma vez só
(os arquivos por UF repetiriam os mesmos candidatos).

Achado do TSE 2026: ``despesas_pagas`` **não** traz ``SQ_CANDIDATO``, só
``SQ_PRESTADOR_CONTAS``. A ponte prestador -> candidato vem das receitas.
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
import zipfile
from pathlib import Path
from typing import Callable, Iterator

import httpx

CONTAS_BASE = "https://cdn.tse.jus.br/estatistica/sead/odsele"
USER_AGENT = "eleitor-cli/0.1 (consulta local; projeto de estudo)"
ANO_PADRAO = 2026

FONTE_FUNDO_PARTIDARIO = "FUNDO PARTIDARIO"
FONTE_FUNDO_ESPECIAL = "FUNDO ESPECIAL"

Progresso = Callable[[int, int], None]


class ContasError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# URLs e diretório de cache
# --------------------------------------------------------------------------


def url_contas(ano: int = ANO_PADRAO) -> str:
    return f"{CONTAS_BASE}/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_{ano}.zip"


def url_cadastro(ano: int = ANO_PADRAO) -> str:
    return f"{CONTAS_BASE}/consulta_cand/consulta_cand_{ano}.zip"


def url_bens(ano: int = ANO_PADRAO) -> str:
    return f"{CONTAS_BASE}/bem_candidato/bem_candidato_{ano}.zip"


def dir_contas() -> Path:
    override = os.environ.get("ELEITOR_CONTAS_DIR")
    if override:
        return Path(override)
    raiz = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if raiz:
        return Path(raiz) / "eleitor" / "contas"
    return Path.home() / ".cache" / "eleitor" / "contas"


def _destino(nome: str) -> Path:
    pasta = dir_contas()
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta / nome


def _meta_path(destino: Path) -> Path:
    return destino.with_suffix(destino.suffix + ".meta.json")


# --------------------------------------------------------------------------
# Download com impressão digital
# --------------------------------------------------------------------------


def _ler_meta(caminho: Path) -> dict:
    if not caminho.exists():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _fingerprint(url: str) -> dict | None:
    """Tamanho + Last-Modified do arquivo remoto (HEAD). ``None`` se falhar."""

    try:
        with httpx.Client(
            timeout=30.0,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as cliente:
            resposta = cliente.head(url)
            resposta.raise_for_status()
    except httpx.HTTPError:
        return None
    tamanho = int(resposta.headers.get("content-length", 0) or 0)
    return {"length": tamanho, "last_modified": resposta.headers.get("last-modified", "")}


def _ja_atual(destino: Path, meta: dict, fingerprint: dict | None) -> bool:
    if not destino.exists() or not meta or fingerprint is None or not fingerprint["length"]:
        return False
    if fingerprint["length"] != meta.get("length"):
        return False
    return fingerprint.get("last_modified") == meta.get("last_modified")


def baixar_zip(
    url: str,
    nome: str,
    forcar: bool = False,
    progresso: Progresso | None = None,
) -> Path:
    """Garante o ZIP em disco, rebaixando só quando o arquivo remoto mudou."""

    destino = _destino(nome)
    meta_caminho = _meta_path(destino)
    meta = _ler_meta(meta_caminho)

    if not forcar:
        fingerprint = _fingerprint(url)
        if _ja_atual(destino, meta, fingerprint):
            return destino
        if destino.exists() and fingerprint is None:
            # Sem HEAD (CDN fora do ar): mantém o que já temos.
            return destino

    parcial = destino.with_suffix(destino.suffix + ".part")
    with httpx.Client(
        timeout=httpx.Timeout(30.0, read=900.0),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as cliente:
        with cliente.stream("GET", url) as resposta:
            resposta.raise_for_status()
            total = int(resposta.headers.get("content-length", 0) or 0)
            baixado = 0
            with parcial.open("wb") as saida:
                for bloco in resposta.iter_bytes(1 << 20):
                    saida.write(bloco)
                    baixado += len(bloco)
                    if progresso:
                        progresso(baixado, total)
            meta = {
                "url": url,
                "length": total or baixado,
                "last_modified": resposta.headers.get("last-modified", ""),
                "baixado_em": time.time(),
            }
    parcial.replace(destino)
    meta_caminho.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return destino


def baixar_fontes(
    ano: int = ANO_PADRAO,
    forcar: bool = False,
    progresso: Callable[[str, int, int], None] | None = None,
) -> dict[str, Path]:
    """Baixa (ou reaproveita) os três ZIPs e devolve os caminhos."""

    fontes = {
        "contas": (url_contas(ano), f"contas-candidatos-{ano}.zip"),
        "cadastro": (url_cadastro(ano), f"consulta-cand-{ano}.zip"),
        "bens": (url_bens(ano), f"bem-candidato-{ano}.zip"),
    }
    caminhos: dict[str, Path] = {}
    for chave, (url, nome) in fontes.items():
        def aviso(baixado: int, total: int, _chave: str = chave) -> None:
            if progresso:
                progresso(_chave, baixado, total)

        caminhos[chave] = baixar_zip(url, nome, forcar=forcar, progresso=aviso)
    return caminhos


# --------------------------------------------------------------------------
# Leitura dos CSVs
# --------------------------------------------------------------------------


def _valor(texto: str | None) -> float:
    """Converte valor do TSE (``1.234,56`` ou ``1234.56``) para float."""

    texto = (texto or "").strip()
    if not texto:
        return 0.0
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0.0


def _arquivos(zf: zipfile.ZipFile, prefixo: str) -> list[str]:
    """CSVs com o prefixo; só a variante ``_BRASIL`` quando ela existe."""

    nomes = [n for n in zf.namelist() if n.startswith(prefixo) and n.endswith(".csv")]
    brasil = [n for n in nomes if n.endswith("_BRASIL.csv")]
    return brasil or nomes


def _linhas(zf: zipfile.ZipFile, nomes: list[str]) -> Iterator[dict[str, str]]:
    for nome in nomes:
        with zf.open(nome) as bruto:
            texto = io.TextIOWrapper(bruto, encoding="latin-1", newline="")
            yield from csv.DictReader(texto, delimiter=";", quotechar='"')


def parse_cadastro(caminho: Path | str, ano: int = ANO_PADRAO) -> dict[str, dict]:
    """``{SQ_CANDIDATO: {nome, partido, cargo, uf, sit_cand, sit_tot, numero}}``.

    Só a situação determina quem é eleito/suplente. Prefere a linha do 2º turno
    quando existir (é a mais recente).
    """

    registros: dict[str, dict] = {}
    with zipfile.ZipFile(caminho) as zf:
        for linha in _linhas(zf, _arquivos(zf, f"consulta_cand_{ano}_")):
            sq = (linha.get("SQ_CANDIDATO") or "").strip()
            if not sq:
                continue
            turno = (linha.get("NR_TURNO") or "1").strip()
            anterior = registros.get(sq)
            if anterior is not None and anterior.get("_turno") == "2":
                continue
            registros[sq] = {
                "nome": (linha.get("NM_URNA_CANDIDATO") or linha.get("NM_CANDIDATO") or "").strip(),
                "partido": (linha.get("SG_PARTIDO") or "").strip(),
                "cargo": int((linha.get("CD_CARGO") or "0").strip() or 0),
                "uf": (linha.get("SG_UF") or "").strip().upper(),
                "numero": (linha.get("NR_CANDIDATO") or "").strip(),
                "sit_cand": (linha.get("DS_SITUACAO_CANDIDATURA") or "").strip(),
                "sit_tot": (linha.get("DS_SIT_TOT_TURNO") or "").strip(),
                "_turno": turno,
            }
    for registro in registros.values():
        registro.pop("_turno", None)
    return registros


def parse_bens(caminho: Path | str, ano: int = ANO_PADRAO) -> dict[str, float]:
    """``{SQ_CANDIDATO: patrimônio declarado}`` (soma de ``VR_BEM_CANDIDATO``)."""

    total: dict[str, float] = {}
    with zipfile.ZipFile(caminho) as zf:
        for linha in _linhas(zf, _arquivos(zf, f"bem_candidato_{ano}_")):
            sq = (linha.get("SQ_CANDIDATO") or "").strip()
            if sq:
                total[sq] = total.get(sq, 0.0) + _valor(linha.get("VR_BEM_CANDIDATO"))
    return total


def parse_receitas(
    caminho: Path | str, ano: int = ANO_PADRAO
) -> tuple[dict[str, dict], dict[str, str], str]:
    """Receitas por candidato, ponte prestador -> candidato e data do arquivo.

    Devolve ``(por_candidato, ponte, gerado_em)``, onde ``por_candidato`` é
    ``{SQ_CANDIDATO: {receita, fp, fefc}}`` (``fp`` = Fundo Partidário,
    ``fefc`` = Fundo Especial de Financiamento de Campanha).
    """

    por_cand: dict[str, dict] = {}
    ponte: dict[str, str] = {}
    gerado_em = ""
    with zipfile.ZipFile(caminho) as zf:
        for linha in _linhas(zf, _arquivos(zf, f"receitas_candidatos_{ano}_")):
            sq = (linha.get("SQ_CANDIDATO") or "").strip()
            if not sq:
                continue
            if not gerado_em:
                gerado_em = f"{linha.get('DT_GERACAO', '')} {linha.get('HH_GERACAO', '')}".strip()
            prestador = (linha.get("SQ_PRESTADOR_CONTAS") or "").strip()
            if prestador:
                ponte[prestador] = sq
            valor = _valor(linha.get("VR_RECEITA"))
            item = por_cand.setdefault(sq, {"receita": 0.0, "fp": 0.0, "fefc": 0.0})
            item["receita"] += valor
            fonte = (linha.get("DS_FONTE_RECEITA") or "").strip().upper()
            if fonte == FONTE_FUNDO_PARTIDARIO:
                item["fp"] += valor
            elif fonte == FONTE_FUNDO_ESPECIAL:
                item["fefc"] += valor
    return por_cand, ponte, gerado_em


def parse_despesas_pagas(
    caminho: Path | str, ponte: dict[str, str], ano: int = ANO_PADRAO
) -> dict[str, float]:
    """``{SQ_CANDIDATO: total gasto}`` usando a ponte prestador -> candidato."""

    total: dict[str, float] = {}
    with zipfile.ZipFile(caminho) as zf:
        for linha in _linhas(zf, _arquivos(zf, f"despesas_pagas_candidatos_{ano}_")):
            sq = ponte.get((linha.get("SQ_PRESTADOR_CONTAS") or "").strip())
            if not sq:
                continue
            total[sq] = total.get(sq, 0.0) + _valor(linha.get("VR_PAGTO_DESPESA"))
    return total
