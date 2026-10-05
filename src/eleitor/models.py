from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Candidato:
    numero: str
    nome: str
    nome_urna: str
    partido: str
    votos: int
    percentual: float
    situacao: str
    eleito: bool
    sqcand: str = ""
    destinacao: str = ""


@dataclass
class TotaisVotos:
    total: int = 0
    validos: int = 0
    brancos: int = 0
    nulos: int = 0
    anulados: int = 0


@dataclass
class Totalizacao:
    secoes_total: int = 0
    secoes_totalizadas: int = 0
    percentual_secoes: float = 0.0
    eleitores_total: int = 0
    eleitores_secoes_totalizadas: int = 0
    gerado_em: str = ""


@dataclass
class ResultadoCargo:
    eleicao: int
    cargo: int
    cargo_nome: str
    abrangencia: str
    candidatos: list[Candidato]
    votos: TotaisVotos
    totalizacao: Totalizacao
    vagas: int = 0


@dataclass
class Municipio:
    uf: str
    codigo: str
    ibge: str
    nome: str
    zonas: list[str]
    capital: bool = False


@dataclass
class Secao:
    numero: str
    principal: str | None = None
    agregadas: list[str] = field(default_factory=list)
    data_aux: str | None = None
    hora_aux: str | None = None
    status: str | None = None
    urnas: int = 0


@dataclass
class ZonaSecoes:
    zona: str
    secoes: list[Secao]
