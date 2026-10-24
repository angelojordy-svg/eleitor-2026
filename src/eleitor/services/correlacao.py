"""Correlação ecológica e co-votação entre candidatos a partir de BUs.

A unidade de análise é a **urna**. O módulo entrega duas leituras diferentes:

* **correlação** — associação entre lugares (urnas/locais), medida em -1..1;
* **co-votação** — limites determinísticos para o comportamento individual
  ("dos eleitores de A, quantos também votaram em B"), que é o que a inferência
  ecológica tenta estimar.

A correlação é descritiva. A co-votação só é identificada quando os limites são
estreitos; caso contrário o resultado correto é "não identificado". Nenhuma das
duas medidas prova transferência causal de votos.
"""

from __future__ import annotations

import bisect
import csv
import math
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from eleitor.sources.planilha import PlanilhaBU

CARGOS_ORDEM = (
    "presidente",
    "governador",
    "senador",
    "deputado federal",
    "deputado estadual",
    "deputado distrital",
    "conselheiro distrital",
)

PSEUDOCONTAGEM = 0.5

ABREV_CARGOS = {
    "presidente": "Pres",
    "governador": "Gov",
    "senador": "Sen",
    "deputado federal": "DepFed",
    "deputado estadual": "DepEst",
    "deputado distrital": "DepDist",
    "conselheiro distrital": "Cons",
}


def _slug(texto: Any) -> str:
    bruto = unicodedata.normalize("NFKD", str(texto or ""))
    sem_acento = "".join(c for c in bruto if not unicodedata.combining(c))
    return "".join(c if c.isalnum() else "-" for c in sem_acento.lower()).strip("-")


def _norm(texto: Any) -> str:
    bruto = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in bruto if not unicodedata.combining(c)).lower().strip()


def _ordem_cargo(cargo: str) -> tuple[int, str]:
    alvo = _norm(cargo)
    try:
        return (CARGOS_ORDEM.index(alvo), alvo)
    except ValueError:
        return (len(CARGOS_ORDEM), alvo)


def _votos_por_eleitor(cargo: str) -> int:
    return 2 if _norm(cargo) == "senador" else 1


def _chave_urna(zona: str, secao: str) -> str:
    return f"{str(zona).zfill(2)}-{str(secao).zfill(4)}"


def _chave_local(zona: str, codigo: str) -> str:
    return f"{str(zona).zfill(2)}|{str(codigo).zfill(4)}"


_ALIASES_CARGO = {
    "dep federal": "deputado federal",
    "dep. federal": "deputado federal",
    "federal": "deputado federal",
    "dep estadual": "deputado estadual",
    "dep. estadual": "deputado estadual",
    "estadual": "deputado estadual",
    "dep distrital": "deputado distrital",
    "dep. distrital": "deputado distrital",
    "distrital": "deputado distrital",
    "conselheiro": "conselheiro distrital",
}


def _cargo_pedido(texto: Any) -> str:
    alvo = _norm(texto)
    return _ALIASES_CARGO.get(alvo, alvo)


def texto_template_pares() -> str:
    """Template do “espaço aberto” para a lista de pares."""

    return (
        "# Lista de pares para `eleitor correlacao --modo focado`\n"
        "# Formato: Cargo:numero ; Cargo:numero\n"
        "# As linhas começando com # são ignoradas.\n"
        "#\n"
        "# Exemplos (descomente e ajuste):\n"
        "# Deputado Federal:2200 ; Deputado Estadual:22100\n"
        "# Deputado Federal:1500 ; Deputado Estadual:15112\n"
        "# Deputado Federal:1321 ; Deputado Estadual:13500\n"
        "# Deputado Federal:2255 ; Deputado Estadual:22555\n"
        "#\n"
        "# Também aceita Senador:222 ; Senador:200 (2 votos por eleitor).\n"
    )


def parse_par(texto: str) -> tuple[tuple[str, str], tuple[str, str]]:
    """Interpreta “Cargo:numero ; Cargo:numero”."""

    bruto = (texto or "").strip()
    if not bruto:
        raise ValueError("par vazio")
    partes = [p.strip() for p in bruto.split(";") if p.strip()]
    if len(partes) != 2:
        raise ValueError(
            f"par inválido: {texto!r}. Use 'Cargo:numero ; Cargo:numero'."
        )
    saida = []
    for parte in partes:
        if ":" not in parte:
            raise ValueError(
                f"par inválido: {parte!r}. Use 'Cargo:numero' em cada lado."
            )
        cargo, numero = parte.rsplit(":", 1)
        cargo = cargo.strip()
        numero = numero.strip()
        if not cargo or not numero:
            raise ValueError(f"par inválido: {parte!r}. Cargo ou número vazio.")
        saida.append((cargo, numero))
    return (saida[0][0], saida[0][1]), (saida[1][0], saida[1][1])


def parse_pares_texto(texto: str) -> list[tuple[tuple[str, str], tuple[str, str]]]:
    """Aceita um ou vários pares separados por `|` ou quebra de linha."""

    pedacos = [p.strip() for p in (texto or "").replace("\n", "|").split("|")]
    pares = []
    for pedaco in pedacos:
        if not pedaco or pedaco.startswith("#"):
            continue
        pares.append(parse_par(pedaco))
    return pares


def ler_pares_arquivo(caminho: str | Path) -> list[tuple[tuple[str, str], tuple[str, str]]]:
    alvo = Path(caminho)
    if not alvo.exists():
        raise FileNotFoundError(f"arquivo de pares não encontrado: {alvo}")
    pares = []
    for numero_linha, linha in enumerate(alvo.read_text(encoding="utf-8").splitlines(), 1):
        conteudo = linha.split("#", 1)[0].strip()
        if not conteudo:
            continue
        try:
            pares.append(parse_par(conteudo))
        except ValueError as exc:
            raise ValueError(f"{alvo}:{numero_linha}: {exc}") from exc
    return pares


def _resolver_candidato(dados: DadosCorrelacao, cargo: str, numero: str) -> int:
    alvo_cargo = _cargo_pedido(cargo)
    alvo_numero = str(numero).strip()
    candidatos = [
        i for i, cand in enumerate(dados.candidatos) if _norm(cand.cargo) == alvo_cargo
    ]
    if not candidatos:
        cargos = sorted({_norm(c.cargo) for c in dados.candidatos})
        raise ValueError(
            f"cargo não encontrado: {cargo!r}. Cargos disponíveis: {', '.join(cargos)}."
        )

    exatos = [i for i in candidatos if dados.candidatos[i].numero == alvo_numero]
    if len(exatos) == 1:
        return exatos[0]
    if len(exatos) > 1:
        return max(exatos, key=lambda i: dados.candidatos[i].total)

    try:
        alvo_int = int(alvo_numero)
    except ValueError:
        alvo_int = None
    if alvo_int is not None:
        numericos = []
        for i in candidatos:
            try:
                if int(dados.candidatos[i].numero) == alvo_int:
                    numericos.append(i)
            except ValueError:
                continue
        if len(numericos) == 1:
            return numericos[0]
        if len(numericos) > 1:
            return max(numericos, key=lambda i: dados.candidatos[i].total)

    exemplos = sorted(
        candidatos, key=lambda i: dados.candidatos[i].total, reverse=True
    )[:8]
    lista = "; ".join(
        f"{dados.candidatos[i].numero} {dados.candidatos[i].nome} "
        f"({dados.candidatos[i].partido})"
        for i in exemplos
    )
    raise ValueError(
        f"candidato não encontrado: {cargo}:{numero}. "
        f"Exemplos em {alvo_cargo}: {lista}."
    )


def _validar_par_covotacao(a: Candidato, b: Candidato) -> None:
    if _norm(a.cargo) == _norm(b.cargo) and _votos_por_eleitor(a.cargo) < 2:
        raise ValueError(
            f"co-votação não é definida para dois candidatos de "
            f"{a.cargo} (voto único). Use cargos diferentes ou Senador × Senador."
        )


def resolver_pares(
    dados: DadosCorrelacao,
    pares: Sequence[tuple[tuple[str, str], tuple[str, str]]],
) -> list[tuple[int, int]]:
    """Converte pares textuais em índices de candidatos, sem duplicatas."""

    resolvidos: list[tuple[int, int]] = []
    vistos: set[tuple[int, int]] = set()
    for (cargo_a, numero_a), (cargo_b, numero_b) in pares:
        i = _resolver_candidato(dados, cargo_a, numero_a)
        j = _resolver_candidato(dados, cargo_b, numero_b)
        if i == j:
            raise ValueError(
                f"par inválido: os dois lados apontam para o mesmo candidato "
                f"({dados.candidatos[i].rotulo})."
            )
        _validar_par_covotacao(dados.candidatos[i], dados.candidatos[j])
        chave = (min(i, j), max(i, j))
        if chave in vistos:
            continue
        vistos.add(chave)
        resolvidos.append(chave)
    return resolvidos


@dataclass(frozen=True)
class Candidato:
    cargo: str
    numero: str
    nome: str
    partido: str
    total: int
    cobertura: float

    @property
    def chave(self) -> tuple[str, str]:
        return (self.cargo, self.numero)

    @property
    def rotulo(self) -> str:
        nome = self.nome.replace("\ufffd", "?")
        return f"{self.cargo} {self.numero} {nome} ({self.partido})"

    @property
    def rotulo_curto(self) -> str:
        nome = self.nome.replace("\ufffd", "?")
        if len(nome) > 24:
            nome = nome[:23] + "…"
        abrev = ABREV_CARGOS.get(_norm(self.cargo), self.cargo[:6])
        return f"{abrev} {self.numero} {nome} ({self.partido})"


@dataclass
class DadosCorrelacao:
    meta: dict[str, Any]
    urnas: list[str]
    locais: list[str]
    zonas: list[str]
    comparecimento: np.ndarray
    candidatos: list[Candidato]
    votos: np.ndarray
    validos: dict[str, np.ndarray]
    agregadas: list[str] = field(default_factory=list)

    @property
    def n_urnas(self) -> int:
        return len(self.urnas)

    @property
    def n_locais(self) -> int:
        return len(set(self.locais))


@dataclass
class ParCorrelacao:
    i: int
    j: int
    a: Candidato
    b: Candidato
    tipo_par: str
    r_bruto: float
    r_dentro: float
    r_bloco: float
    p_bruto: float
    p_dentro: float
    p_bloco: float
    q_bruto: float
    q_dentro: float
    q_bloco: float
    ic95_dentro_inf: float
    ic95_dentro_sup: float
    bootstrap_inf: float | None
    bootstrap_sup: float | None
    n_urnas: int
    n_locais: int
    flag: str


@dataclass
class ResultadoCorrelacao:
    candidatos: list[Candidato]
    indices: list[int]
    X: np.ndarray
    pesos: np.ndarray
    locais: np.ndarray
    grupos_locais: list[np.ndarray]
    r_bruto: np.ndarray
    r_dentro: np.ndarray
    r_bloco: np.ndarray
    pares: list[ParCorrelacao]
    n_urnas: int
    n_locais: int
    n_eff: int
    bloco_metodo: str
    bloco_por_par: bool = False


@dataclass
class ParCovotacao:
    a: Candidato
    b: Candidato
    n_eleitores: int
    a_votos: int
    b_votos: int
    limite_inf: int
    limite_sup: int
    p_b_dado_a_inf: float
    p_b_dado_a_sup: float
    p_a_dado_b_inf: float
    p_a_dado_b_sup: float
    largura_a: float
    largura_b: float
    flag: str
    goodman_b_dado_a: float | None = None
    goodman_b_dado_a_inf: float | None = None
    goodman_b_dado_a_sup: float | None = None
    goodman_a_dado_b: float | None = None
    goodman_a_dado_b_inf: float | None = None
    goodman_a_dado_b_sup: float | None = None
    goodman_flag: str = ""
    i: int = -1
    j: int = -1


@dataclass(frozen=True)
class LocalFocado:
    local: str
    a: int
    b: int
    n: int
    share_a: float
    share_b: float
    limite_inf: int
    limite_sup: int
    p_b_a_inf: float
    p_b_a_sup: float
    p_a_b_inf: float
    p_a_b_sup: float
    largura_a: float
    largura_b: float
    ab_n: float


@dataclass
class ParFocado:
    a: Candidato
    b: Candidato
    i: int
    j: int
    tipo_par: str
    r_bruto: float
    r_dentro: float
    r_bloco: float
    r_local: float
    spearman_local: float
    ic_boot_inf: float | None
    ic_boot_sup: float | None
    p_perm: float
    p_fisher: float
    q_global: float | None
    q_focado: float
    benchmark_tipo: str
    benchmark_n: int
    benchmark_percentil: float | None
    benchmark_valores: list[float] = field(default_factory=list)
    loo_min: float = float("nan")
    loo_mediana: float = float("nan")
    loo_max: float = float("nan")
    n_eleitores: int = 0
    a_votos: int = 0
    b_votos: int = 0
    limite_inf: int = 0
    limite_sup: int = 0
    p_b_a_inf: float = 0.0
    p_b_a_sup: float = 0.0
    p_a_b_inf: float = 0.0
    p_a_b_sup: float = 0.0
    largura_a: float = 0.0
    largura_b: float = 0.0
    flag_covotacao: str = ""
    goodman_b_a: float | None = None
    goodman_b_a_inf: float | None = None
    goodman_b_a_sup: float | None = None
    goodman_a_b: float | None = None
    goodman_a_b_inf: float | None = None
    goodman_a_b_sup: float | None = None
    goodman_flag: str = ""
    locais: list[LocalFocado] = field(default_factory=list)
    pontos: list[tuple[float, float, str, str]] = field(default_factory=list)
    n_urnas: int = 0
    n_locais: int = 0


def construir_dados(planilha: PlanilhaBU) -> DadosCorrelacao:
    """Alinha urnas, locais, comparecimento e votos nominais em matrizes."""

    urnas_por_chave: dict[str, Any] = {}
    agregadas: list[str] = []
    for urna in planilha.urnas:
        chave = _chave_urna(urna.zona, urna.secao)
        urnas_por_chave[chave] = urna
        if any(c.isdigit() for c in str(urna.agrega or "")):
            agregadas.append(chave)

    chaves = sorted(urnas_por_chave)
    indice = {chave: i for i, chave in enumerate(chaves)}
    n = len(chaves)

    comparecimento = np.zeros(n, dtype=float)
    locais = [""] * n
    zonas = [""] * n
    for chave, urna in urnas_por_chave.items():
        i = indice[chave]
        comparecimento[i] = max(int(urna.comparecimento), 0)
        locais[i] = _chave_local(urna.zona, urna.codigo)
        zonas[i] = str(urna.zona)

    cargos_presentes = sorted({r.cargo for r in planilha.resumos}, key=_ordem_cargo)
    validos: dict[str, np.ndarray] = {
        cargo: np.zeros(n, dtype=float) for cargo in cargos_presentes
    }
    for resumo in planilha.resumos:
        chave = _chave_urna(resumo.zona, resumo.secao)
        i = indice.get(chave)
        if i is None:
            continue
        if resumo.cargo not in validos:
            validos[resumo.cargo] = np.zeros(n, dtype=float)
        validos[resumo.cargo][i] += max(int(resumo.validos), 0)

    votos_por_cand: dict[tuple[str, str], np.ndarray] = defaultdict(
        lambda: np.zeros(n, dtype=np.int64)
    )
    dados_cand: dict[tuple[str, str], dict[str, Any]] = {}
    cobertura: dict[tuple[str, str], set[int]] = defaultdict(set)
    for voto in planilha.votos:
        if _norm(voto.tipo) != "nominal" or int(voto.votos) <= 0:
            continue
        chave_urna = _chave_urna(voto.zona, voto.secao)
        i = indice.get(chave_urna)
        if i is None:
            continue
        numero = str(voto.numero or voto.votavel or "").strip()
        chave = (voto.cargo, numero)
        votos_por_cand[chave][i] += int(voto.votos)
        cobertura[chave].add(i)
        dados_cand.setdefault(
            chave,
            {
                "nome": str(voto.votavel or "").strip(),
                "partido": str(voto.partido or "").strip(),
            },
        )

    chaves_cand = sorted(
        votos_por_cand,
        key=lambda chave: (
            _ordem_cargo(chave[0]),
            -int(votos_por_cand[chave].sum()),
            dados_cand[chave]["nome"].lower(),
        ),
    )
    candidatos: list[Candidato] = []
    for chave in chaves_cand:
        total = int(votos_por_cand[chave].sum())
        candidatos.append(
            Candidato(
                cargo=chave[0],
                numero=chave[1],
                nome=dados_cand[chave]["nome"],
                partido=dados_cand[chave]["partido"],
                total=total,
                cobertura=len(cobertura[chave]) / n if n else 0.0,
            )
        )

    matriz = np.zeros((n, len(candidatos)), dtype=np.int64)
    for j, chave in enumerate(chaves_cand):
        matriz[:, j] = votos_por_cand[chave]

    meta = dict(planilha.meta)
    meta.update(
        {
            "total_urnas": n,
            "total_locais": len(set(locais)),
            "total_candidatos": len(candidatos),
            "total_comparecimento": int(comparecimento.sum()),
            "urnas_agregadas": len(agregadas),
        }
    )
    return DadosCorrelacao(
        meta=meta,
        urnas=chaves,
        locais=locais,
        zonas=zonas,
        comparecimento=comparecimento,
        candidatos=candidatos,
        votos=matriz,
        validos=validos,
        agregadas=agregadas,
    )


def selecionar(
    dados: DadosCorrelacao,
    min_votos: float = 0.005,
    min_cobertura: float = 0.9,
) -> list[int]:
    """Seleciona candidatos com massa e cobertura suficientes para correlacionar."""

    escolhidos: list[int] = []
    por_cargo: dict[str, list[int]] = defaultdict(list)
    for i, cand in enumerate(dados.candidatos):
        por_cargo[cand.cargo].append(i)

    for cargo, indices in por_cargo.items():
        total_valido = float(dados.validos.get(cargo, np.zeros(1)).sum())
        if total_valido <= 0:
            continue
        for i in indices:
            cand = dados.candidatos[i]
            if cand.total <= 0:
                continue
            if cand.total < min_votos * total_valido:
                continue
            if cand.cobertura < min_cobertura:
                continue
            escolhidos.append(i)
        if not any(dados.candidatos[i].cargo == cargo for i in escolhidos):
            for i in sorted(indices, key=lambda k: dados.candidatos[k].total, reverse=True)[:2]:
                if dados.candidatos[i].total > 0:
                    escolhidos.append(i)

    escolhidos = sorted(
        set(escolhidos),
        key=lambda i: (
            _ordem_cargo(dados.candidatos[i].cargo),
            -dados.candidatos[i].total,
            dados.candidatos[i].nome.lower(),
        ),
    )
    return escolhidos


def _logit_shares(dados: DadosCorrelacao, indices: Sequence[int]) -> np.ndarray:
    """Log-odds de cada candidato contra os demais votos válidos do cargo.

    É uma transformação log-ratio (ALR) que evita a correlação negativa
    artificial imposta pela soma 1 das shares. A pseudocontagem estabiliza
    urnas com zero votos.
    """

    n = dados.n_urnas
    X = np.zeros((n, len(indices)), dtype=float)
    for j, i in enumerate(indices):
        cand = dados.candidatos[i]
        votos = dados.votos[:, i].astype(float)
        validos = dados.validos.get(cand.cargo, np.zeros(n, dtype=float)).astype(float)
        resto = np.maximum(validos - votos, 0.0)
        X[:, j] = np.log((votos + PSEUDOCONTAGEM) / (resto + PSEUDOCONTAGEM))
    X[~np.isfinite(X)] = 0.0
    return X


def _correlacao_ponderada(X: np.ndarray, pesos: np.ndarray) -> np.ndarray:
    """Matriz de correlação de Pearson com pesos (n x p)."""

    X = np.asarray(X, dtype=float)
    pesos = np.asarray(pesos, dtype=float)
    if X.ndim == 1:
        X = X[:, None]
    p = X.shape[1]
    mask = np.isfinite(pesos) & (pesos > 0)
    X = X[mask]
    pesos = pesos[mask]
    if X.shape[0] < 2 or pesos.sum() <= 0:
        R = np.full((p, p), np.nan)
        np.fill_diagonal(R, 1.0)
        return R

    w = pesos / pesos.sum()
    media = w @ X
    Xc = X - media
    cov = Xc.T @ (Xc * w[:, None])
    desvios = np.sqrt(np.diag(cov))
    with np.errstate(invalid="ignore", divide="ignore"):
        R = cov / np.outer(desvios, desvios)
    R = np.clip(R, -1.0, 1.0)
    R[~np.isfinite(R)] = np.nan
    np.fill_diagonal(R, 1.0)
    return R


def _residuos_local(
    X: np.ndarray, pesos: np.ndarray, locais: np.ndarray
) -> np.ndarray:
    """Remove a média ponderada do local de cada urna (efeito fixo de local)."""

    Xc = np.asarray(X, dtype=float).copy()
    pesos = np.asarray(pesos, dtype=float)
    for grupo in np.unique(locais):
        mask = locais == grupo
        w = pesos[mask]
        if w.sum() <= 0:
            Xc[mask] = 0.0
            continue
        w = w / w.sum()
        Xc[mask] -= w @ X[mask]
    return Xc


def _residuos_sobre_z(
    X: np.ndarray, z: np.ndarray, pesos: np.ndarray
) -> np.ndarray:
    """Residualiza X em z (regressão ponderada, sem intercepto)."""

    X = np.asarray(X, dtype=float)
    z = np.asarray(z, dtype=float)
    pesos = np.asarray(pesos, dtype=float)
    if X.ndim == 1:
        X = X[:, None]
    w = pesos / pesos.sum() if pesos.sum() > 0 else np.full(len(pesos), 1 / len(pesos))
    var = float(np.sum(w * z * z))
    if var <= 0:
        return X.copy()
    beta = (X * w[:, None]).T @ z / var
    return X - np.outer(z, beta)


def _matriz_bloco_por_par(
    X: np.ndarray,
    X_dentro: np.ndarray,
    pesos: np.ndarray,
    locais: np.ndarray,
    z_fixo: np.ndarray,
    z_fixo_dentro: np.ndarray,
) -> np.ndarray:
    """Correlação parcial controlando um PC1 calculado sem o próprio par.

    O bloco de cada par é o primeiro componente principal dos *outros*
    candidatos. Isso evita controlar um par por ele mesmo e é o que dá sentido
    à coluna ``r_bloco``.
    """

    X = np.asarray(X, dtype=float)
    X_dentro = np.asarray(X_dentro, dtype=float)
    pesos = np.asarray(pesos, dtype=float)
    p = X.shape[1]
    R = np.full((p, p), np.nan)
    np.fill_diagonal(R, 1.0)
    w = pesos / pesos.sum() if pesos.sum() > 0 else np.full(len(pesos), 1 / len(pesos))

    for i in range(p):
        for j in range(i + 1, p):
            cols = [k for k in range(p) if k != i and k != j]
            if len(cols) >= 3:
                Xr = X[:, cols]
                desvios = Xr.std(axis=0)
                desvios[desvios == 0] = 1.0
                Xs = (Xr - Xr.mean(axis=0)) / desvios
                U, S, _ = np.linalg.svd(Xs, full_matrices=False)
                z = U[:, 0] * S[0]
                if np.isfinite(z_fixo).all():
                    with np.errstate(invalid="ignore"):
                        correl = np.corrcoef(z, z_fixo)[0, 1]
                    if np.isfinite(correl) and correl < 0:
                        z = -z
                elif z.sum() < 0:
                    z = -z
                desvio = float(z.std())
                if desvio > 0:
                    z = (z - z.mean()) / desvio
                z_dentro = _residuos_local(z[:, None], pesos, locais)[:, 0]
            else:
                z_dentro = z_fixo_dentro

            var = float(np.sum(w * z_dentro * z_dentro))
            if var <= 0:
                continue
            xi = X_dentro[:, i]
            xj = X_dentro[:, j]
            bi = float(np.sum(w * xi * z_dentro) / var)
            bj = float(np.sum(w * xj * z_dentro) / var)
            ri = xi - bi * z_dentro
            rj = xj - bj * z_dentro
            valor = float(_correlacao_ponderada(np.column_stack([ri, rj]), pesos)[0, 1])
            R[i, j] = R[j, i] = valor
    return R


def referencias_bloco(
    dados: DadosCorrelacao, metodo: str = "presidente", n_por_cargo: int = 5
) -> set[int]:
    """Candidatos usados para construir o índice de bloco.

    Serve para não controlar um par por ele mesmo (o que geraria correlação
    mecânica, especialmente no par dos dois presidenciáveis).
    """

    metodo = (metodo or "presidente").lower()
    if metodo in {"none", "nenhum", "nao"}:
        return set()
    if metodo == "presidente":
        presidenciais = [
            i
            for i, cand in enumerate(dados.candidatos)
            if _norm(cand.cargo) == "presidente" and cand.total > 0
        ]
        presidenciais.sort(key=lambda i: dados.candidatos[i].total, reverse=True)
        return set(presidenciais[:2])
    if metodo == "pc1":
        indices: list[int] = []
        for cargo in sorted({c.cargo for c in dados.candidatos}, key=_ordem_cargo):
            cols = [
                i
                for i, cand in enumerate(dados.candidatos)
                if cand.cargo == cargo and cand.total > 0
            ]
            cols.sort(key=lambda i: dados.candidatos[i].total, reverse=True)
            indices.extend(cols[:n_por_cargo])
        return set(indices)
    return set()


def indice_bloco(
    dados: DadosCorrelacao, metodo: str = "presidente", n_por_cargo: int = 5
) -> np.ndarray | None:
    """Índice de bloco político por urna.

    ``presidente`` usa a diferença de log-odds entre os dois presidenciáveis
    mais votados. ``pc1`` usa o primeiro componente principal dos principais
    candidatos de todos os cargos, com sinal alinhado ao voto presidencial.
    """

    metodo = (metodo or "presidente").lower()
    if metodo in {"none", "nenhum", "nao"}:
        return None

    presidenciais = [
        i
        for i, cand in enumerate(dados.candidatos)
        if _norm(cand.cargo) == "presidente" and cand.total > 0
    ]
    presidenciais.sort(key=lambda i: dados.candidatos[i].total, reverse=True)

    z: np.ndarray | None = None
    if metodo == "presidente":
        if len(presidenciais) >= 2:
            X = _logit_shares(dados, presidenciais[:2])
            z = X[:, 0] - X[:, 1]
    elif metodo == "pc1":
        indices: list[int] = []
        for cargo in sorted({c.cargo for c in dados.candidatos}, key=_ordem_cargo):
            cols = [
                i
                for i, cand in enumerate(dados.candidatos)
                if cand.cargo == cargo and cand.total > 0
            ]
            cols.sort(key=lambda i: dados.candidatos[i].total, reverse=True)
            indices.extend(cols[:n_por_cargo])
        if len(indices) >= 2:
            X = _logit_shares(dados, indices)
            desvios = X.std(axis=0)
            desvios[desvios == 0] = 1.0
            Xs = (X - X.mean(axis=0)) / desvios
            U, S, _ = np.linalg.svd(Xs, full_matrices=False)
            z = U[:, 0] * S[0]
            if len(presidenciais) >= 2:
                ref = _logit_shares(dados, presidenciais[:2])
                ref = ref[:, 0] - ref[:, 1]
                if np.corrcoef(z, ref)[0, 1] < 0:
                    z = -z
            elif z.sum() < 0:
                z = -z
    else:
        raise ValueError(f"método de bloco inválido: {metodo!r}")

    if z is None or not np.isfinite(z).any():
        return None
    z = np.asarray(z, dtype=float)
    z[~np.isfinite(z)] = 0.0
    desvio = float(z.std())
    if desvio > 0:
        z = (z - z.mean()) / desvio
    else:
        z = np.zeros_like(z)
    return z


def _p_fisher(r: float, n_eff: int) -> float:
    if n_eff <= 3 or not np.isfinite(r):
        return 1.0
    rc = float(np.clip(r, -0.999999, 0.999999))
    z = math.atanh(rc)
    se = 1.0 / math.sqrt(n_eff - 3)
    return math.erfc(abs(z) / (se * math.sqrt(2.0)))


def _ic_fisher(r: float, n_eff: int, z_crit: float = 1.959963984540054) -> tuple[float, float]:
    if n_eff <= 3 or not np.isfinite(r):
        return (float("nan"), float("nan"))
    rc = float(np.clip(r, -0.999999, 0.999999))
    z = math.atanh(rc)
    se = 1.0 / math.sqrt(n_eff - 3)
    return (math.tanh(z - z_crit * se), math.tanh(z + z_crit * se))


def bh_fdr(p: Sequence[float]) -> np.ndarray:
    """Benjamini-Hochberg; devolve q-valores na ordem original."""

    valores = np.asarray(p, dtype=float)
    n = len(valores)
    if n == 0:
        return np.array([], dtype=float)
    validos = np.isfinite(valores)
    q = np.ones(n, dtype=float)
    if not validos.any():
        return q
    idx = np.where(validos)[0]
    ordenados = idx[np.argsort(valores[idx])]
    m = len(ordenados)
    acumulado = 1.0
    for posicao in range(m - 1, -1, -1):
        i = ordenados[posicao]
        valor = valores[i] * m / (posicao + 1)
        acumulado = min(acumulado, valor)
        q[i] = min(max(acumulado, 0.0), 1.0)
    return q


def _tipo_par(a: Candidato, b: Candidato) -> str:
    if _norm(a.cargo) != _norm(b.cargo):
        return "cargos_diferentes"
    if _norm(a.cargo) == "senador":
        return "mesmo_cargo_senador"
    return "mesmo_cargo"


def _flag_correlacao(
    tipo: str, r_dentro: float, q_dentro: float, r_bloco: float, q_bloco: float
) -> str:
    if tipo == "mesmo_cargo":
        return "substituto"
    if np.isfinite(q_dentro) and q_dentro < 0.05 and abs(r_dentro) >= 0.3:
        return "associacao_forte"
    if np.isfinite(q_bloco) and q_bloco < 0.05 and abs(r_bloco) >= 0.3:
        return "associacao_residual"
    return ""


def analisar_correlacoes(
    dados: DadosCorrelacao,
    indices: Sequence[int] | None = None,
    metodo_bloco: str = "presidente",
    bootstrap_top: int = 20,
    bootstrap_repeticoes: int = 1000,
    seed: int = 42,
) -> ResultadoCorrelacao:
    """Calcula a matriz de correlação (bruta, within-local e within-local+bloco)."""

    indices = list(indices) if indices is not None else selecionar(dados)
    if len(indices) < 2:
        raise ValueError("selecione ao menos dois candidatos com votos para correlacionar.")

    X = _logit_shares(dados, indices)
    pesos = np.asarray(dados.comparecimento, dtype=float)
    if pesos.sum() <= 0:
        pesos = np.ones(dados.n_urnas, dtype=float)

    locais = np.asarray(dados.locais)
    grupos = [np.where(locais == grupo)[0] for grupo in np.unique(locais)]

    r_bruto = _correlacao_ponderada(X, pesos)
    X_dentro = _residuos_local(X, pesos, locais)
    r_dentro = _correlacao_ponderada(X_dentro, pesos)
    usar_bloco = (metodo_bloco or "").lower() not in {"none", "nenhum", "nao"}
    bloco = indice_bloco(dados, metodo_bloco) if usar_bloco else None
    refs_bloco = referencias_bloco(dados, metodo_bloco) if usar_bloco else set()
    por_par = bool(usar_bloco and bloco is not None and len(indices) <= 60)
    r_bloco = np.full((len(indices), len(indices)), np.nan)
    if usar_bloco and bloco is not None:
        z_dentro = _residuos_local(bloco[:, None], pesos, locais)[:, 0]
        if por_par:
            r_bloco = _matriz_bloco_por_par(X, X_dentro, pesos, locais, bloco, z_dentro)
        else:
            X_bloco = _residuos_sobre_z(X_dentro, z_dentro, pesos)
            r_bloco = _correlacao_ponderada(X_bloco, pesos)

    n_eff = max(len(grupos), 1)
    n_eff_dentro = max(n_eff - 1, 4)
    n_eff_bloco = max(n_eff - 2, 4)

    pares: list[ParCorrelacao] = []
    for i in range(len(indices)):
        for j in range(i + 1, len(indices)):
            a = dados.candidatos[indices[i]]
            b = dados.candidatos[indices[j]]
            tipo = _tipo_par(a, b)
            r_b = float(r_bruto[i, j])
            r_d = float(r_dentro[i, j])
            r_bl = float(r_bloco[i, j])
            if usar_bloco and not por_par:
                if _norm(metodo_bloco) == "presidente":
                    autodefinido = indices[i] in refs_bloco or indices[j] in refs_bloco
                else:
                    autodefinido = indices[i] in refs_bloco and indices[j] in refs_bloco
            else:
                autodefinido = False
            if autodefinido:
                r_bl = float("nan")
            p_b = _p_fisher(r_b, n_eff)
            p_d = _p_fisher(r_d, n_eff_dentro)
            p_bl = _p_fisher(r_bl, n_eff_bloco)
            inf, sup = _ic_fisher(r_d, n_eff_dentro)
            pares.append(
                ParCorrelacao(
                    i=i,
                    j=j,
                    a=a,
                    b=b,
                    tipo_par=tipo,
                    r_bruto=r_b,
                    r_dentro=r_d,
                    r_bloco=r_bl,
                    p_bruto=p_b,
                    p_dentro=p_d,
                    p_bloco=p_bl,
                    q_bruto=1.0,
                    q_dentro=1.0,
                    q_bloco=1.0,
                    ic95_dentro_inf=inf,
                    ic95_dentro_sup=sup,
                    bootstrap_inf=None,
                    bootstrap_sup=None,
                    n_urnas=dados.n_urnas,
                    n_locais=n_eff,
                    flag="",
                )
            )

    if pares:
        q_bruto = bh_fdr([par.p_bruto for par in pares])
        q_dentro = bh_fdr([par.p_dentro for par in pares])
        q_bloco = bh_fdr([par.p_bloco for par in pares])
        for par, qb, qd, qbl in zip(pares, q_bruto, q_dentro, q_bloco):
            par.q_bruto = float(qb)
            par.q_dentro = float(qd)
            par.q_bloco = float(qbl)
            par.flag = _flag_correlacao(
                par.tipo_par, par.r_dentro, par.q_dentro, par.r_bloco, par.q_bloco
            )

    resultado = ResultadoCorrelacao(
        candidatos=[dados.candidatos[i] for i in indices],
        indices=indices,
        X=X,
        pesos=pesos,
        locais=locais,
        grupos_locais=grupos,
        r_bruto=r_bruto,
        r_dentro=r_dentro,
        r_bloco=r_bloco,
        pares=pares,
        n_urnas=dados.n_urnas,
        n_locais=n_eff,
        n_eff=n_eff,
        bloco_metodo=(
            "pc1_leave_one_pair_out" if por_par else metodo_bloco
        ),
        bloco_por_par=por_par,
    )
    if bootstrap_top > 0 and bootstrap_repeticoes > 0:
        _bootstrap_top(resultado, bootstrap_top, bootstrap_repeticoes, seed)
    return resultado


def _bootstrap_top(
    resultado: ResultadoCorrelacao, top: int, repeticoes: int, seed: int
) -> None:
    """IC por bootstrap de clusters (locais) para os pares mais fortes."""

    candidatos = [par for par in resultado.pares if np.isfinite(par.r_dentro)]
    candidatos.sort(key=lambda par: abs(par.r_dentro), reverse=True)
    alvos = candidatos[:top]
    if not alvos:
        return

    rng = np.random.default_rng(seed)
    X = resultado.X
    pesos = resultado.pesos
    locais = resultado.locais
    grupos = resultado.grupos_locais
    n_grupos = len(grupos)

    for par in alvos:
        x = X[:, par.i]
        y = X[:, par.j]
        amostras: list[float] = []
        for _ in range(repeticoes):
            escolhidos = rng.integers(0, n_grupos, size=n_grupos)
            idx = np.concatenate([grupos[k] for k in escolhidos])
            xb = x[idx]
            yb = y[idx]
            wb = pesos[idx]
            lb = locais[idx]
            xr = _residuos_local(xb[:, None], wb, lb)[:, 0]
            yr = _residuos_local(yb[:, None], wb, lb)[:, 0]
            R = _correlacao_ponderada(np.column_stack([xr, yr]), wb)
            valor = float(R[0, 1])
            if np.isfinite(valor):
                amostras.append(valor)
        if amostras:
            par.bootstrap_inf, par.bootstrap_sup = (
                float(v) for v in np.percentile(amostras, [2.5, 97.5])
            )


def _goodman_ols(
    x: np.ndarray, y: np.ndarray, pesos: np.ndarray
) -> tuple[float, float] | None:
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(pesos) & (pesos > 0)
    x = x[mask]
    y = y[mask]
    pesos = pesos[mask]
    if len(x) < 3 or np.ptp(x) == 0:
        return None
    D = np.column_stack([np.ones_like(x), x])
    raiz = np.sqrt(pesos)
    try:
        beta, *_ = np.linalg.lstsq(D * raiz[:, None], y * raiz, rcond=None)
    except np.linalg.LinAlgError:
        return None
    if not np.all(np.isfinite(beta)):
        return None
    return float(beta[0]), float(beta[1])


def _goodman_bootstrap(
    x: np.ndarray,
    y: np.ndarray,
    pesos: np.ndarray,
    locais: np.ndarray,
    repeticoes: int,
    rng: np.random.Generator,
) -> tuple[float, float] | None:
    grupos = [np.where(locais == g)[0] for g in np.unique(locais)]
    if not grupos:
        return None
    valores: list[float] = []
    for _ in range(repeticoes):
        escolhidos = rng.integers(0, len(grupos), size=len(grupos))
        idx = np.concatenate([grupos[k] for k in escolhidos])
        ajuste = _goodman_ols(x[idx], y[idx], pesos[idx])
        if ajuste is None:
            continue
        alpha, beta = ajuste
        valores.append(alpha + beta)
    if not valores:
        return None
    return (float(np.percentile(valores, 2.5)), float(np.percentile(valores, 97.5)))


def _goodman_par(
    dados: DadosCorrelacao,
    a_index: int,
    b_index: int,
    repeticoes: int,
    rng: np.random.Generator,
) -> dict[str, Any]:
    n = dados.comparecimento.astype(float)
    a = dados.votos[:, a_index].astype(float)
    b = dados.votos[:, b_index].astype(float)
    mask = n > 0
    x = np.zeros_like(n)
    y = np.zeros_like(n)
    x[mask] = a[mask] / n[mask]
    y[mask] = b[mask] / n[mask]

    ajuste = _goodman_ols(x, y, n)
    if ajuste is None:
        return {}
    alpha, beta = ajuste
    p_b_a = alpha + beta
    p_b_na = alpha
    locais = np.asarray(dados.locais)
    ic_b_a = _goodman_bootstrap(x, y, n, locais, repeticoes, rng)

    ajuste_inv = _goodman_ols(y, x, n)
    p_a_b = None
    p_a_nb = None
    ic_a_b = None
    if ajuste_inv is not None:
        alpha2, beta2 = ajuste_inv
        p_a_b = alpha2 + beta2
        p_a_nb = alpha2
        ic_a_b = _goodman_bootstrap(y, x, n, locais, repeticoes, rng)

    fora = any(
        valor is not None and (valor < 0.0 or valor > 1.0)
        for valor in (p_b_a, p_b_na, p_a_b, p_a_nb)
    )
    return {
        "b_dado_a": p_b_a,
        "b_dado_a_inf": ic_b_a[0] if ic_b_a else None,
        "b_dado_a_sup": ic_b_a[1] if ic_b_a else None,
        "a_dado_b": p_a_b,
        "a_dado_b_inf": ic_a_b[0] if ic_a_b else None,
        "a_dado_b_sup": ic_a_b[1] if ic_a_b else None,
        "flag": "fora_da_faixa" if fora else "",
    }


def analisar_covotacao(
    dados: DadosCorrelacao,
    indices: Sequence[int] | None = None,
    goodman_top: int = 50,
    repeticoes: int = 1000,
    seed: int = 42,
) -> list[ParCovotacao]:
    """Limites de co-votação para pares de cargos diferentes (e Senador x Senador)."""

    indices = list(indices) if indices is not None else selecionar(dados)
    n_eleitores = int(dados.comparecimento.sum())
    if n_eleitores <= 0:
        return []

    pares: list[ParCovotacao] = []
    for pos_i, i in enumerate(indices):
        a = dados.candidatos[i]
        a_votos = int(dados.votos[:, i].sum())
        if a_votos <= 0:
            continue
        for j in indices[pos_i + 1 :]:
            b = dados.candidatos[j]
            mesmo_cargo = _norm(a.cargo) == _norm(b.cargo)
            if mesmo_cargo and _votos_por_eleitor(a.cargo) < 2:
                continue
            b_votos = int(dados.votos[:, j].sum())
            if b_votos <= 0:
                continue

            limite_inf, limite_sup = limites_covotacao(
                a_votos, b_votos, n_eleitores
            )
            largura_a = (limite_sup - limite_inf) / a_votos
            largura_b = (limite_sup - limite_inf) / b_votos

            if largura_a <= 0.2 and largura_b <= 0.2:
                flag = "informativo"
            elif largura_a >= 0.5 or largura_b >= 0.5:
                flag = "indeterminado"
            else:
                flag = "parcial"

            pares.append(
                ParCovotacao(
                    a=a,
                    b=b,
                    n_eleitores=n_eleitores,
                    a_votos=a_votos,
                    b_votos=b_votos,
                    limite_inf=limite_inf,
                    limite_sup=limite_sup,
                    p_b_dado_a_inf=limite_inf / a_votos,
                    p_b_dado_a_sup=limite_sup / a_votos,
                    p_a_dado_b_inf=limite_inf / b_votos,
                    p_a_dado_b_sup=limite_sup / b_votos,
                    largura_a=largura_a,
                    largura_b=largura_b,
                    flag=flag,
                    i=i,
                    j=j,
                )
            )

    alvos = sorted(
        pares,
        key=lambda par: (
            max(par.largura_a, par.largura_b),
            -(par.a_votos + par.b_votos),
        ),
    )[: max(goodman_top, 0)]
    if alvos:
        rng = np.random.default_rng(seed)
        for par in alvos:
            estimativas = _goodman_par(dados, par.i, par.j, repeticoes, rng)
            par.goodman_b_dado_a = estimativas.get("b_dado_a")
            par.goodman_b_dado_a_inf = estimativas.get("b_dado_a_inf")
            par.goodman_b_dado_a_sup = estimativas.get("b_dado_a_sup")
            par.goodman_a_dado_b = estimativas.get("a_dado_b")
            par.goodman_a_dado_b_inf = estimativas.get("a_dado_b_inf")
            par.goodman_a_dado_b_sup = estimativas.get("a_dado_b_sup")
            par.goodman_flag = estimativas.get("flag", "")

    pares.sort(
        key=lambda par: (
            {"informativo": 0, "parcial": 1, "indeterminado": 2}.get(par.flag, 3),
            max(par.largura_a, par.largura_b),
            -(par.a_votos + par.b_votos),
        )
    )
    return pares


def limites_covotacao(
    a_votos: int, b_votos: int, n_eleitores: int
) -> tuple[int, int]:
    """Limites determinísticos do número de eleitores que votaram em A e B."""

    if n_eleitores <= 0:
        return (0, 0)
    limite_inf = max(0, a_votos + b_votos - n_eleitores)
    limite_sup = min(a_votos, b_votos)
    if limite_inf > limite_sup:
        limite_inf = limite_sup
    return (limite_inf, limite_sup)


def resumo_covotacao(pares: Iterable[ParCovotacao]) -> dict[str, int]:
    contagem = {"informativo": 0, "parcial": 0, "indeterminado": 0, "total": 0}
    for par in pares:
        contagem[par.flag] = contagem.get(par.flag, 0) + 1
        contagem["total"] += 1
    return contagem


def _pair_arrays(
    dados: DadosCorrelacao, i: int, j: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    X = _logit_shares(dados, [i, j])
    pesos = np.asarray(dados.comparecimento, dtype=float)
    if pesos.sum() <= 0:
        pesos = np.ones(dados.n_urnas, dtype=float)
    return X[:, 0], X[:, 1], pesos, np.asarray(dados.locais)


def _r_dentro_pair(
    x: np.ndarray, y: np.ndarray, pesos: np.ndarray, locais: np.ndarray
) -> tuple[float, np.ndarray, np.ndarray]:
    xr = _residuos_local(x[:, None], pesos, locais)[:, 0]
    yr = _residuos_local(y[:, None], pesos, locais)[:, 0]
    r = float(_correlacao_ponderada(np.column_stack([xr, yr]), pesos)[0, 1])
    return r, xr, yr


def bootstrap_par(
    dados: DadosCorrelacao,
    i: int,
    j: int,
    repeticoes: int = 2000,
    seed: int = 42,
) -> tuple[float | None, float | None]:
    """IC95% por bootstrap de clusters (locais) para r_dentro do par."""

    if repeticoes <= 0:
        return (None, None)
    x, y, pesos, locais = _pair_arrays(dados, i, j)
    grupos = [np.where(locais == g)[0] for g in np.unique(locais)]
    if not grupos:
        return (None, None)
    rng = np.random.default_rng(seed)
    valores: list[float] = []
    for _ in range(repeticoes):
        escolhidos = rng.integers(0, len(grupos), size=len(grupos))
        idx = np.concatenate([grupos[k] for k in escolhidos])
        r, _, _ = _r_dentro_pair(x[idx], y[idx], pesos[idx], locais[idx])
        if np.isfinite(r):
            valores.append(r)
    if not valores:
        return (None, None)
    inf, sup = np.percentile(valores, [2.5, 97.5])
    return (float(inf), float(sup))


def permutacao_par(
    dados: DadosCorrelacao,
    i: int,
    j: int,
    repeticoes: int = 5000,
    seed: int = 42,
) -> float:
    """p-valor focado: permutação de B dentro de cada local."""

    if repeticoes <= 0:
        return float("nan")
    x, y, pesos, locais = _pair_arrays(dados, i, j)
    observado, xr, yr = _r_dentro_pair(x, y, pesos, locais)
    if not np.isfinite(observado):
        return 1.0
    grupos = [np.where(locais == g)[0] for g in np.unique(locais)]
    rng = np.random.default_rng(seed)
    extremos = 0
    for _ in range(repeticoes):
        yp = yr.copy()
        for idx in grupos:
            yp[idx] = rng.permutation(yp[idx])
        r = float(_correlacao_ponderada(np.column_stack([xr, yp]), pesos)[0, 1])
        if np.isfinite(r) and abs(r) >= abs(observado):
            extremos += 1
    return (1 + extremos) / (repeticoes + 1)


def leave_one_local_out(
    dados: DadosCorrelacao, i: int, j: int
) -> tuple[float, float, float]:
    """Faixa de r_dentro excluindo cada local."""

    x, y, pesos, locais = _pair_arrays(dados, i, j)
    valores: list[float] = []
    for grupo in np.unique(locais):
        mask = locais != grupo
        if mask.sum() < 2 or len(np.unique(locais[mask])) < 2:
            continue
        r, _, _ = _r_dentro_pair(x[mask], y[mask], pesos[mask], locais[mask])
        if np.isfinite(r):
            valores.append(r)
    if not valores:
        return (float("nan"), float("nan"), float("nan"))
    return (float(min(valores)), float(np.median(valores)), float(max(valores)))


def _agregados_por_local(
    dados: DadosCorrelacao, i: int, j: int
) -> list[LocalFocado]:
    a_cand = dados.candidatos[i]
    b_cand = dados.candidatos[j]
    locais = np.asarray(dados.locais)
    validos_a = dados.validos.get(a_cand.cargo, np.zeros(dados.n_urnas))
    validos_b = dados.validos.get(b_cand.cargo, np.zeros(dados.n_urnas))
    saida: list[LocalFocado] = []
    for grupo in sorted(set(locais)):
        mask = locais == grupo
        a = int(dados.votos[mask, i].sum())
        b = int(dados.votos[mask, j].sum())
        n = int(dados.comparecimento[mask].sum())
        va = float(validos_a[mask].sum())
        vb = float(validos_b[mask].sum())
        share_a = a / va if va > 0 else 0.0
        share_b = b / vb if vb > 0 else 0.0
        limite_inf, limite_sup = limites_covotacao(a, b, n)
        largura_a = (limite_sup - limite_inf) / a if a > 0 else 1.0
        largura_b = (limite_sup - limite_inf) / b if b > 0 else 1.0
        saida.append(
            LocalFocado(
                local=str(grupo),
                a=a,
                b=b,
                n=n,
                share_a=share_a,
                share_b=share_b,
                limite_inf=limite_inf,
                limite_sup=limite_sup,
                p_b_a_inf=limite_inf / a if a > 0 else 0.0,
                p_b_a_sup=limite_sup / a if a > 0 else 0.0,
                p_a_b_inf=limite_inf / b if b > 0 else 0.0,
                p_a_b_sup=limite_sup / b if b > 0 else 0.0,
                largura_a=largura_a,
                largura_b=largura_b,
                ab_n=(a + b) / n if n > 0 else 0.0,
            )
        )
    return saida


def _r_local_e_spearman(locais: Sequence[LocalFocado]) -> tuple[float, float]:
    xs = np.array([local.share_a for local in locais], dtype=float)
    ys = np.array([local.share_b for local in locais], dtype=float)
    if len(xs) < 3 or xs.std() == 0 or ys.std() == 0:
        return (float("nan"), float("nan"))
    pearson = float(np.corrcoef(xs, ys)[0, 1])
    rx = np.argsort(np.argsort(xs))
    ry = np.argsort(np.argsort(ys))
    spearman = float(np.corrcoef(rx, ry)[0, 1])
    return (pearson, spearman)


def _eh_fed_est(a: Candidato, b: Candidato) -> bool:
    return {_norm(a.cargo), _norm(b.cargo)} == {
        "deputado federal",
        "deputado estadual",
    }


def _benchmark_para(
    resultado: ResultadoCorrelacao,
    alvo: tuple[int, int],
    tipo: str,
    a: Candidato,
    b: Candidato,
) -> tuple[str, int, float | None, list[float]]:
    tipo = (tipo or "none").lower()
    if tipo in {"none", "nenhum", "nao"}:
        return ("none", 0, None, [])

    rotulo = tipo
    if tipo == "fed-est" and not _eh_fed_est(a, b):
        tipo = "todos"
        rotulo = "todos (fed-est não se aplica)"
    elif tipo == "fed-est":
        rotulo = "fed-est"

    refs: list[float] = []
    for par in resultado.pares:
        if tuple(sorted((par.i, par.j))) == tuple(sorted(alvo)):
            continue
        if not np.isfinite(par.r_dentro):
            continue
        if tipo == "fed-est" and not _eh_fed_est(par.a, par.b):
            continue
        if tipo == "same-party":
            if not par.a.partido or not par.b.partido:
                continue
            if _norm(par.a.partido) != _norm(par.b.partido):
                continue
            if par.tipo_par == "mesmo_cargo":
                continue
        if tipo == "todos" and par.tipo_par == "mesmo_cargo":
            continue
        refs.append(abs(float(par.r_dentro)))

    alvo_abs = None
    # O alvo é procurado no resultado pelo par de posições.
    for par in resultado.pares:
        if tuple(sorted((par.i, par.j))) == tuple(sorted(alvo)):
            alvo_abs = abs(float(par.r_dentro)) if np.isfinite(par.r_dentro) else None
            break
    percentil = None
    if alvo_abs is not None and len(refs) >= 5:
        ordenados = sorted(refs)
        posicao = bisect.bisect_right(ordenados, alvo_abs)
        percentil = 100.0 * posicao / len(ordenados)
    return (rotulo, len(refs), percentil, refs)


def analisar_par_focado(
    dados: DadosCorrelacao,
    i: int,
    j: int,
    resultado: ResultadoCorrelacao,
    benchmark_tipo: str = "fed-est",
    bootstrap_repeticoes: int = 2000,
    permutacoes: int = 5000,
    goodman_repeticoes: int = 1000,
    loo: bool = True,
    seed: int = 42,
) -> ParFocado:
    """Métricas completas de um par, para o relatório focado."""

    a = dados.candidatos[i]
    b = dados.candidatos[j]
    _validar_par_covotacao(a, b)

    posicoes = {indice: posicao for posicao, indice in enumerate(resultado.indices)}
    if i not in posicoes or j not in posicoes:
        raise ValueError(
            "par fora do conjunto analisado; inclua os candidatos no resultado "
            "antes de chamar analisar_par_focado."
        )
    pi, pj = posicoes[i], posicoes[j]
    alvo = (pi, pj)
    par = None
    for candidato_par in resultado.pares:
        if tuple(sorted((candidato_par.i, candidato_par.j))) == tuple(sorted(alvo)):
            par = candidato_par
            break

    r_bruto = float(resultado.r_bruto[pi, pj])
    r_dentro = float(resultado.r_dentro[pi, pj])
    r_bloco = float(resultado.r_bloco[pi, pj])
    p_fisher = (
        float(par.p_dentro)
        if par is not None
        else _p_fisher(r_dentro, max(resultado.n_locais - 1, 4))
    )
    q_global = float(par.q_dentro) if par is not None else None

    x, y, pesos, locais = _pair_arrays(dados, i, j)
    ic_inf, ic_sup = bootstrap_par(
        dados, i, j, repeticoes=bootstrap_repeticoes, seed=seed
    )
    p_perm = permutacao_par(
        dados, i, j, repeticoes=permutacoes, seed=seed + 1
    )
    if loo:
        loo_min, loo_mediana, loo_max = leave_one_local_out(dados, i, j)
    else:
        loo_min = loo_mediana = loo_max = float("nan")
    locais_focados = _agregados_por_local(dados, i, j)
    r_local, spearman_local = _r_local_e_spearman(locais_focados)

    n_eleitores = int(pesos.sum())
    a_votos = int(dados.votos[:, i].sum())
    b_votos = int(dados.votos[:, j].sum())
    limite_inf, limite_sup = limites_covotacao(a_votos, b_votos, n_eleitores)
    largura_a = (limite_sup - limite_inf) / a_votos if a_votos > 0 else 1.0
    largura_b = (limite_sup - limite_inf) / b_votos if b_votos > 0 else 1.0
    if largura_a <= 0.2 and largura_b <= 0.2:
        flag_covotacao = "informativo"
    elif largura_a >= 0.5 or largura_b >= 0.5:
        flag_covotacao = "indeterminado"
    else:
        flag_covotacao = "parcial"

    goodman = _goodman_par(
        dados, i, j, goodman_repeticoes, np.random.default_rng(seed + 2)
    )

    _, xr, yr = _r_dentro_pair(x, y, pesos, locais)
    pontos = [
        (float(ra), float(rb), dados.locais[k], dados.urnas[k])
        for k, (ra, rb) in enumerate(zip(xr, yr))
        if np.isfinite(ra) and np.isfinite(rb)
    ]

    rotulo_benchmark, benchmark_n, benchmark_percentil, benchmark_valores = (
        _benchmark_para(resultado, alvo, benchmark_tipo, a, b)
    )

    return ParFocado(
        a=a,
        b=b,
        i=i,
        j=j,
        tipo_par=_tipo_par(a, b),
        r_bruto=r_bruto,
        r_dentro=r_dentro,
        r_bloco=r_bloco,
        r_local=r_local,
        spearman_local=spearman_local,
        ic_boot_inf=ic_inf,
        ic_boot_sup=ic_sup,
        p_perm=p_perm,
        p_fisher=p_fisher,
        q_global=q_global,
        q_focado=float("nan"),
        benchmark_tipo=rotulo_benchmark,
        benchmark_n=benchmark_n,
        benchmark_percentil=benchmark_percentil,
        benchmark_valores=benchmark_valores,
        loo_min=loo_min,
        loo_mediana=loo_mediana,
        loo_max=loo_max,
        n_eleitores=n_eleitores,
        a_votos=a_votos,
        b_votos=b_votos,
        limite_inf=limite_inf,
        limite_sup=limite_sup,
        p_b_a_inf=limite_inf / a_votos if a_votos > 0 else 0.0,
        p_b_a_sup=limite_sup / a_votos if a_votos > 0 else 0.0,
        p_a_b_inf=limite_inf / b_votos if b_votos > 0 else 0.0,
        p_a_b_sup=limite_sup / b_votos if b_votos > 0 else 0.0,
        largura_a=largura_a,
        largura_b=largura_b,
        flag_covotacao=flag_covotacao,
        goodman_b_a=goodman.get("b_dado_a"),
        goodman_b_a_inf=goodman.get("b_dado_a_inf"),
        goodman_b_a_sup=goodman.get("b_dado_a_sup"),
        goodman_a_b=goodman.get("a_dado_b"),
        goodman_a_b_inf=goodman.get("a_dado_b_inf"),
        goodman_a_b_sup=goodman.get("a_dado_b_sup"),
        goodman_flag=goodman.get("flag", ""),
        locais=locais_focados,
        pontos=pontos,
        n_urnas=dados.n_urnas,
        n_locais=dados.n_locais,
    )


def analisar_pares_focados(
    dados: DadosCorrelacao,
    pares: Sequence[tuple[int, int]],
    resultado: ResultadoCorrelacao,
    benchmark_tipo: str = "fed-est",
    bootstrap_repeticoes: int = 2000,
    permutacoes: int = 5000,
    goodman_repeticoes: int = 1000,
    loo: bool = True,
    seed: int = 42,
) -> list[ParFocado]:
    focados = [
        analisar_par_focado(
            dados,
            i,
            j,
            resultado,
            benchmark_tipo=benchmark_tipo,
            bootstrap_repeticoes=bootstrap_repeticoes,
            permutacoes=permutacoes,
            goodman_repeticoes=goodman_repeticoes,
            loo=loo,
            seed=seed + 10 * posicao,
        )
        for posicao, (i, j) in enumerate(pares)
    ]
    p_valores = [par.p_perm for par in focados]
    q_valores = bh_fdr(p_valores)
    for par, q in zip(focados, q_valores):
        par.q_focado = float(q) if np.isfinite(par.p_perm) else float("nan")
    return focados


def _num(valor: Any, casas: int = 6) -> str:
    if valor is None:
        return ""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    if not np.isfinite(numero):
        return ""
    return f"{numero:.{casas}f}".replace(".", ",")


def _pval(valor: Any) -> str:
    if valor is None:
        return ""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    if not np.isfinite(numero):
        return ""
    return f"{numero:.6g}".replace(".", ",")


def _texto(valor: Any) -> str:
    return str(valor or "").replace("\ufffd", "?")


def _cabecalho_par() -> list[str]:
    return [
        "cargo_a",
        "numero_a",
        "nome_a",
        "partido_a",
        "cargo_b",
        "numero_b",
        "nome_b",
        "partido_b",
        "tipo_par",
        "r_bruto",
        "r_dentro",
        "r_bloco",
        "p_bruto",
        "p_dentro",
        "p_bloco",
        "q_bruto",
        "q_dentro",
        "q_bloco",
        "ic95_dentro_inf",
        "ic95_dentro_sup",
        "bootstrap_inf",
        "bootstrap_sup",
        "n_urnas",
        "n_locais",
        "flag",
    ]


def escrever_correlacao_csv(resultado: ResultadoCorrelacao, caminho: str | Path) -> Path:
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow(_cabecalho_par())
        for par in resultado.pares:
            escritor.writerow(
                [
                    _texto(par.a.cargo),
                    par.a.numero,
                    _texto(par.a.nome),
                    _texto(par.a.partido),
                    _texto(par.b.cargo),
                    par.b.numero,
                    _texto(par.b.nome),
                    _texto(par.b.partido),
                    par.tipo_par,
                    _num(par.r_bruto),
                    _num(par.r_dentro),
                    _num(par.r_bloco),
                    _pval(par.p_bruto),
                    _pval(par.p_dentro),
                    _pval(par.p_bloco),
                    _pval(par.q_bruto),
                    _pval(par.q_dentro),
                    _pval(par.q_bloco),
                    _num(par.ic95_dentro_inf),
                    _num(par.ic95_dentro_sup),
                    _num(par.bootstrap_inf),
                    _num(par.bootstrap_sup),
                    par.n_urnas,
                    par.n_locais,
                    par.flag,
                ]
            )
    return destino


def escrever_matriz_csv(
    resultado: ResultadoCorrelacao,
    caminho: str | Path,
    matriz: np.ndarray | None = None,
) -> Path:
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    valores = resultado.r_dentro if matriz is None else matriz
    rotulos = [cand.rotulo for cand in resultado.candidatos]
    with destino.open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow(["candidato", *rotulos])
        for i, rotulo in enumerate(rotulos):
            escritor.writerow([rotulo, *(_num(v) for v in valores[i])])
    return destino


def _cabecalho_covotacao() -> list[str]:
    return [
        "cargo_a",
        "numero_a",
        "nome_a",
        "partido_a",
        "cargo_b",
        "numero_b",
        "nome_b",
        "partido_b",
        "n_eleitores",
        "a_votos",
        "b_votos",
        "limite_inf",
        "limite_sup",
        "p_b_dado_a_inf",
        "p_b_dado_a_sup",
        "p_a_dado_b_inf",
        "p_a_dado_b_sup",
        "largura_a",
        "largura_b",
        "flag",
        "goodman_b_dado_a",
        "goodman_b_dado_a_inf",
        "goodman_b_dado_a_sup",
        "goodman_a_dado_b",
        "goodman_a_dado_b_inf",
        "goodman_a_dado_b_sup",
        "goodman_flag",
    ]


def escrever_covotacao_csv(pares: Iterable[ParCovotacao], caminho: str | Path) -> Path:
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow(_cabecalho_covotacao())
        for par in pares:
            escritor.writerow(
                [
                    _texto(par.a.cargo),
                    par.a.numero,
                    _texto(par.a.nome),
                    _texto(par.a.partido),
                    _texto(par.b.cargo),
                    par.b.numero,
                    _texto(par.b.nome),
                    _texto(par.b.partido),
                    par.n_eleitores,
                    par.a_votos,
                    par.b_votos,
                    par.limite_inf,
                    par.limite_sup,
                    _num(par.p_b_dado_a_inf),
                    _num(par.p_b_dado_a_sup),
                    _num(par.p_a_dado_b_inf),
                    _num(par.p_a_dado_b_sup),
                    _num(par.largura_a),
                    _num(par.largura_b),
                    par.flag,
                    _num(par.goodman_b_dado_a),
                    _num(par.goodman_b_dado_a_inf),
                    _num(par.goodman_b_dado_a_sup),
                    _num(par.goodman_a_dado_b),
                    _num(par.goodman_a_dado_b_inf),
                    _num(par.goodman_a_dado_b_sup),
                    par.goodman_flag,
                ]
            )
    return destino


def _cabecalho_focado() -> list[str]:
    return [
        "cargo_a",
        "numero_a",
        "nome_a",
        "partido_a",
        "cargo_b",
        "numero_b",
        "nome_b",
        "partido_b",
        "tipo_par",
        "r_bruto",
        "r_dentro",
        "r_bloco",
        "r_local",
        "spearman_local",
        "ic_boot_inf",
        "ic_boot_sup",
        "p_perm",
        "p_fisher",
        "q_global",
        "q_focado",
        "benchmark_tipo",
        "benchmark_n",
        "benchmark_percentil",
        "loo_min",
        "loo_mediana",
        "loo_max",
        "n_eleitores",
        "a_votos",
        "b_votos",
        "limite_inf",
        "limite_sup",
        "p_b_a_inf",
        "p_b_a_sup",
        "p_a_b_inf",
        "p_a_b_sup",
        "largura_a",
        "largura_b",
        "flag_covotacao",
        "goodman_b_a",
        "goodman_b_a_inf",
        "goodman_b_a_sup",
        "goodman_a_b",
        "goodman_a_b_inf",
        "goodman_a_b_sup",
        "goodman_flag",
    ]


def escrever_focado_csv(pares: Iterable[ParFocado], caminho: str | Path) -> Path:
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow(_cabecalho_focado())
        for par in pares:
            escritor.writerow(
                [
                    _texto(par.a.cargo),
                    par.a.numero,
                    _texto(par.a.nome),
                    _texto(par.a.partido),
                    _texto(par.b.cargo),
                    par.b.numero,
                    _texto(par.b.nome),
                    _texto(par.b.partido),
                    par.tipo_par,
                    _num(par.r_bruto),
                    _num(par.r_dentro),
                    _num(par.r_bloco),
                    _num(par.r_local),
                    _num(par.spearman_local),
                    _num(par.ic_boot_inf),
                    _num(par.ic_boot_sup),
                    _pval(par.p_perm),
                    _pval(par.p_fisher),
                    _pval(par.q_global),
                    _pval(par.q_focado),
                    par.benchmark_tipo,
                    par.benchmark_n,
                    _num(par.benchmark_percentil, 1),
                    _num(par.loo_min),
                    _num(par.loo_mediana),
                    _num(par.loo_max),
                    par.n_eleitores,
                    par.a_votos,
                    par.b_votos,
                    par.limite_inf,
                    par.limite_sup,
                    _num(par.p_b_a_inf),
                    _num(par.p_b_a_sup),
                    _num(par.p_a_b_inf),
                    _num(par.p_a_b_sup),
                    _num(par.largura_a),
                    _num(par.largura_b),
                    par.flag_covotacao,
                    _num(par.goodman_b_a),
                    _num(par.goodman_b_a_inf),
                    _num(par.goodman_b_a_sup),
                    _num(par.goodman_a_b),
                    _num(par.goodman_a_b_inf),
                    _num(par.goodman_a_b_sup),
                    par.goodman_flag,
                ]
            )
    return destino


def _cabecalho_focado_locais() -> list[str]:
    return [
        "cargo_a",
        "numero_a",
        "cargo_b",
        "numero_b",
        "local",
        "a",
        "b",
        "n",
        "share_a",
        "share_b",
        "limite_inf",
        "limite_sup",
        "p_b_a_inf",
        "p_b_a_sup",
        "p_a_b_inf",
        "p_a_b_sup",
        "largura_a",
        "largura_b",
        "ab_n",
    ]


def escrever_focado_locais_csv(
    pares: Iterable[ParFocado], caminho: str | Path
) -> Path:
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow(_cabecalho_focado_locais())
        for par in pares:
            for local in par.locais:
                escritor.writerow(
                    [
                        _texto(par.a.cargo),
                        par.a.numero,
                        _texto(par.b.cargo),
                        par.b.numero,
                        local.local,
                        local.a,
                        local.b,
                        local.n,
                        _num(local.share_a),
                        _num(local.share_b),
                        local.limite_inf,
                        local.limite_sup,
                        _num(local.p_b_a_inf),
                        _num(local.p_b_a_sup),
                        _num(local.p_a_b_inf),
                        _num(local.p_a_b_sup),
                        _num(local.largura_a),
                        _num(local.largura_b),
                        _num(local.ab_n),
                    ]
                )
    return destino


def _cabecalho_focado_benchmark() -> list[str]:
    return [
        "cargo_a",
        "numero_a",
        "cargo_b",
        "numero_b",
        "benchmark_tipo",
        "benchmark_n",
        "alvo_abs",
        "percentil",
        "ref_min",
        "ref_p10",
        "ref_p50",
        "ref_p90",
        "ref_max",
    ]


def escrever_focado_benchmark_csv(
    pares: Iterable[ParFocado], caminho: str | Path
) -> Path:
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow(_cabecalho_focado_benchmark())
        for par in pares:
            refs = np.asarray(par.benchmark_valores, dtype=float)
            refs = refs[np.isfinite(refs)]
            if len(refs):
                q = np.percentile(refs, [0, 10, 50, 90, 100])
                valores = [_num(v) for v in q]
            else:
                valores = ["", "", "", "", ""]
            escritor.writerow(
                [
                    _texto(par.a.cargo),
                    par.a.numero,
                    _texto(par.b.cargo),
                    par.b.numero,
                    par.benchmark_tipo,
                    par.benchmark_n,
                    _num(abs(par.r_dentro)),
                    _num(par.benchmark_percentil, 1),
                    *valores,
                ]
            )
    return destino


def _finito(valor: Any) -> float | None:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if np.isfinite(numero) else None


def montar_relatorio(
    dados: DadosCorrelacao,
    resultado: ResultadoCorrelacao,
    pares_covot: Iterable[ParCovotacao],
    top_candidatos: int = 25,
    top_pares: int = 50,
) -> dict[str, Any]:
    """Payload do HTML: heatmap, top pares e tabela de co-votação."""

    pares_covot = list(pares_covot)
    posicoes = sorted(
        range(len(resultado.candidatos)),
        key=lambda k: resultado.candidatos[k].total,
        reverse=True,
    )[: max(top_candidatos, 2)]
    grade_bloco = resultado.r_bloco[np.ix_(posicoes, posicoes)]
    grade_dentro = resultado.r_dentro[np.ix_(posicoes, posicoes)]

    candidatos = []
    for posicao in posicoes:
        cand = resultado.candidatos[posicao]
        candidatos.append(
            {
                "rotulo": cand.rotulo,
                "curto": cand.rotulo_curto,
                "cargo": cand.cargo,
                "numero": cand.numero,
                "nome": cand.nome.replace("\ufffd", "?"),
                "partido": cand.partido,
                "total": cand.total,
            }
        )

    pares_corr = sorted(
        resultado.pares,
        key=lambda par: (
            par.tipo_par == "mesmo_cargo",
            -(
                abs(par.r_bloco)
                if np.isfinite(par.r_bloco)
                else abs(par.r_dentro)
            ),
        ),
    )[: max(top_pares, 0)]
    correlacoes = [
        {
            "a": par.a.rotulo,
            "b": par.b.rotulo,
            "tipo": par.tipo_par,
            "r_bruto": _finito(par.r_bruto),
            "r_dentro": _finito(par.r_dentro),
            "r_bloco": _finito(par.r_bloco),
            "ic_inf": _finito(par.ic95_dentro_inf),
            "ic_sup": _finito(par.ic95_dentro_sup),
            "q_dentro": _finito(par.q_dentro),
            "q_bloco": _finito(par.q_bloco),
            "flag": par.flag,
        }
        for par in pares_corr
    ]

    covotacoes = [
        {
            "a": par.a.rotulo,
            "b": par.b.rotulo,
            "p_b_a_inf": _finito(par.p_b_dado_a_inf),
            "p_b_a_sup": _finito(par.p_b_dado_a_sup),
            "p_a_b_inf": _finito(par.p_a_dado_b_inf),
            "p_a_b_sup": _finito(par.p_a_dado_b_sup),
            "largura": _finito(max(par.largura_a, par.largura_b)),
            "goodman": _finito(par.goodman_b_dado_a),
            "goodman_flag": par.goodman_flag,
            "flag": par.flag,
        }
        for par in list(pares_covot)[: max(top_pares, 0)]
    ]

    meta = dict(dados.meta)
    meta.update(
        {
            "n_urnas": dados.n_urnas,
            "n_locais": dados.n_locais,
            "n_eff": resultado.n_eff,
            "n_candidatos": len(resultado.candidatos),
            "bloco_metodo": resultado.bloco_metodo,
            "bloco_por_par": resultado.bloco_por_par,
            "resumo_covotacao": resumo_covotacao(pares_covot),
        }
    )
    return {
        "meta": meta,
        "candidatos": candidatos,
        "matriz_bloco": [
            [_finito(valor) for valor in linha] for linha in grade_bloco
        ],
        "matriz_dentro": [
            [_finito(valor) for valor in linha] for linha in grade_dentro
        ],
        "correlacoes": correlacoes,
        "covotacoes": covotacoes,
    }


def montar_payload_focado(
    dados: DadosCorrelacao, pares: Iterable[ParFocado]
) -> dict[str, Any]:
    """Payload do HTML estático do relatório focado."""

    pares = list(pares)
    resumo = {"total": len(pares), "informativo": 0, "parcial": 0, "indeterminado": 0}
    for par in pares:
        resumo[par.flag_covotacao] = resumo.get(par.flag_covotacao, 0) + 1

    def _candidato(cand: Candidato) -> dict[str, Any]:
        return {
            "rotulo": cand.rotulo,
            "curto": cand.rotulo_curto,
            "cargo": cand.cargo,
            "numero": cand.numero,
            "nome": cand.nome.replace("\ufffd", "?"),
            "partido": cand.partido,
            "total": cand.total,
        }

    def _local(local: LocalFocado) -> dict[str, Any]:
        return {
            "local": local.local,
            "a": local.a,
            "b": local.b,
            "n": local.n,
            "share_a": _finito(local.share_a),
            "share_b": _finito(local.share_b),
            "limite_inf": local.limite_inf,
            "limite_sup": local.limite_sup,
            "p_b_a_inf": _finito(local.p_b_a_inf),
            "p_b_a_sup": _finito(local.p_b_a_sup),
            "p_a_b_inf": _finito(local.p_a_b_inf),
            "p_a_b_sup": _finito(local.p_a_b_sup),
            "largura_a": _finito(local.largura_a),
            "largura_b": _finito(local.largura_b),
            "ab_n": _finito(local.ab_n),
        }

    def _par(par: ParFocado) -> dict[str, Any]:
        return {
            "a": _candidato(par.a),
            "b": _candidato(par.b),
            "tipo_par": par.tipo_par,
            "r_bruto": _finito(par.r_bruto),
            "r_dentro": _finito(par.r_dentro),
            "r_bloco": _finito(par.r_bloco),
            "r_local": _finito(par.r_local),
            "spearman_local": _finito(par.spearman_local),
            "ic_boot_inf": _finito(par.ic_boot_inf),
            "ic_boot_sup": _finito(par.ic_boot_sup),
            "p_perm": _finito(par.p_perm),
            "p_fisher": _finito(par.p_fisher),
            "q_global": _finito(par.q_global),
            "q_focado": _finito(par.q_focado),
            "benchmark_tipo": par.benchmark_tipo,
            "benchmark_n": par.benchmark_n,
            "benchmark_percentil": _finito(par.benchmark_percentil),
            "benchmark_valores": sorted(
                float(v) for v in par.benchmark_valores if np.isfinite(v)
            ),
            "loo_min": _finito(par.loo_min),
            "loo_mediana": _finito(par.loo_mediana),
            "loo_max": _finito(par.loo_max),
            "n_eleitores": par.n_eleitores,
            "a_votos": par.a_votos,
            "b_votos": par.b_votos,
            "limite_inf": par.limite_inf,
            "limite_sup": par.limite_sup,
            "p_b_a_inf": _finito(par.p_b_a_inf),
            "p_b_a_sup": _finito(par.p_b_a_sup),
            "p_a_b_inf": _finito(par.p_a_b_inf),
            "p_a_b_sup": _finito(par.p_a_b_sup),
            "largura_a": _finito(par.largura_a),
            "largura_b": _finito(par.largura_b),
            "flag_covotacao": par.flag_covotacao,
            "goodman_b_a": _finito(par.goodman_b_a),
            "goodman_b_a_inf": _finito(par.goodman_b_a_inf),
            "goodman_b_a_sup": _finito(par.goodman_b_a_sup),
            "goodman_a_b": _finito(par.goodman_a_b),
            "goodman_a_b_inf": _finito(par.goodman_a_b_inf),
            "goodman_a_b_sup": _finito(par.goodman_a_b_sup),
            "goodman_flag": par.goodman_flag,
            "n_urnas": par.n_urnas,
            "n_locais": par.n_locais,
            "locais": [_local(local) for local in par.locais],
            "pontos": [
                {"ra": _finito(ra), "rb": _finito(rb), "local": local, "urna": urna}
                for ra, rb, local, urna in par.pontos
            ],
        }

    meta = dict(dados.meta)
    meta.update(
        {
            "n_urnas": dados.n_urnas,
            "n_locais": dados.n_locais,
            "n_pares": len(pares),
            "resumo": resumo,
            "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    return {"meta": meta, "pares": [_par(par) for par in pares]}


def nome_base(meta: dict[str, Any]) -> str:
    municipio = str(meta.get("municipio") or "municipio").split("/")[0].strip()
    ano = meta.get("ano") or "sem-ano"
    return f"correlacao_{_slug(municipio)}_{ano}"


def nome_base_focado(meta: dict[str, Any]) -> str:
    municipio = str(meta.get("municipio") or "municipio").split("/")[0].strip()
    ano = meta.get("ano") or "sem-ano"
    return f"focado_{_slug(municipio)}_{ano}"
