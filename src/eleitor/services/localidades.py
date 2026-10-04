from __future__ import annotations

import unicodedata

from eleitor.config import TTL_CONFIG
from eleitor.http import CachedClient
from eleitor.models import Municipio
from eleitor.sources.resultados import parse_municipios, url_municipios_config


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return " ".join(texto.lower().split())


class Localidades:
    def __init__(self, client: CachedClient) -> None:
        self.client = client
        self._municipios: list[Municipio] | None = None

    @property
    def municipios(self) -> list[Municipio]:
        if self._municipios is None:
            data = self.client.get_json(url_municipios_config(), ttl=TTL_CONFIG)
            self._municipios = parse_municipios(data or {})
        return self._municipios

    def buscar(self, termo: str, uf: str | None = None) -> list[Municipio]:
        alvo = normalizar(termo)
        uf = uf.lower() if uf else None
        encontrados = [
            m
            for m in self.municipios
            if normalizar(m.nome) == alvo or alvo in normalizar(m.nome)
        ]
        if uf:
            encontrados = [m for m in encontrados if m.uf == uf]
        exatos = [m for m in encontrados if normalizar(m.nome) == alvo]
        return exatos or encontrados

    def zonas(self, uf: str, codigo_municipio: str) -> list[str]:
        for m in self.municipios:
            if m.uf == uf.lower() and m.codigo == f"{int(codigo_municipio):05d}":
                return m.zonas
        return []

    def nome(self, uf: str, codigo_municipio: str) -> str:
        for m in self.municipios:
            if m.uf == uf.lower() and m.codigo == f"{int(codigo_municipio):05d}":
                return m.nome
        return codigo_municipio
