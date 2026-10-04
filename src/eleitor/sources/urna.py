from __future__ import annotations

from typing import Any

from eleitor.config import BASE_URL, CICLO, PLEITO
from eleitor.models import Secao


def arquivos_urna(aux: dict[str, Any]) -> list[dict[str, Any]]:
    itens: list[dict[str, Any]] = []
    for h in aux.get("hashes", []):
        nomes: list[str] = []
        for arq in h.get("arq", []):
            if isinstance(arq, dict) and arq.get("nm"):
                nomes.append(str(arq["nm"]))
            elif isinstance(arq, str):
                nomes.append(arq)
        for nome in h.get("nmarq", []):
            nomes.append(str(nome))
        itens.append({"hash": h.get("hash"), "status": h.get("st"), "arquivos": nomes})
    return itens


def arquivo_bu(nomes: list[str]) -> str | None:
    for nome in nomes:
        baixo = nome.lower()
        if "imgbu" in baixo:
            continue
        if baixo.endswith(".bu") or baixo.endswith("-bu.dat"):
            return nome
    return None


def url_arquivo_urna(uf: str, municipio: str, zona: str, secao: str, hash_urna: str, nome: str) -> str:
    uf = uf.lower()
    mun = f"{int(municipio):05d}"
    zon = f"{int(zona):04d}"
    sec = f"{int(secao):04d}"
    return f"{BASE_URL}/{CICLO}/arquivo-urna/{PLEITO}/dados/{uf}/{mun}/{zon}/{sec}/{hash_urna}/{nome}"


def secoes_com_aux(secoes: list[Secao]) -> list[Secao]:
    return [s for s in secoes if s.data_aux and s.principal is None]
