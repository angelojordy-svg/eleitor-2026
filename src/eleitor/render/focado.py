"""Relatório HTML estático da análise focada de pares.

O relatório é gerado em Python (sem JavaScript e sem recursos externos) para
funcionar como arquivo único, com SVG embutido.
"""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np

TEMPLATE_PATH = Path(__file__).resolve().parent / "focado.html"


def _esc(valor: Any) -> str:
    return html.escape(str(valor if valor is not None else ""), quote=True)


def _fmt(valor: Any, casas: int = 3, sinal: bool = False) -> str:
    if valor is None:
        return "—"
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(numero):
        return "—"
    texto = f"{numero:+.{casas}f}" if sinal else f"{numero:.{casas}f}"
    return texto.replace(".", ",")


def _pct(valor: Any, casas: int = 0) -> str:
    if valor is None:
        return "—"
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(numero):
        return "—"
    return f"{numero * 100:.{casas}f}%".replace(".", ",")


def _pval(valor: Any) -> str:
    if valor is None:
        return "—"
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(numero):
        return "—"
    if numero < 0.001:
        return f"{numero:.2e}".replace(".", ",")
    return f"{numero:.4f}".replace(".", ",")


def _card(valor: Any, rotulo: str) -> str:
    return (
        '<div class="card">'
        f'<div class="valor">{_esc(valor)}</div>'
        f'<div class="rotulo">{_esc(rotulo)}</div>'
        "</div>"
    )


def _svg_scatter(
    pontos: Iterable[dict[str, Any]],
    xlab: str,
    ylab: str,
    largura: int = 600,
    altura: int = 360,
) -> str:
    validos = [
        ponto
        for ponto in pontos
        if ponto.get("x") is not None
        and ponto.get("y") is not None
        and np.isfinite(float(ponto["x"]))
        and np.isfinite(float(ponto["y"]))
    ]
    if len(validos) < 2:
        return '<p class="vazio">Sem dados suficientes para o gráfico.</p>'

    xs = np.array([float(p["x"]) for p in validos])
    ys = np.array([float(p["y"]) for p in validos])
    xmin, xmax = float(xs.min()), float(xs.max())
    ymin, ymax = float(ys.min()), float(ys.max())
    folga_x = max((xmax - xmin) * 0.06, 0.01)
    folga_y = max((ymax - ymin) * 0.06, 0.01)
    xmin -= folga_x
    xmax += folga_x
    ymin -= folga_y
    ymax += folga_y

    esquerda, direita, topo, base = 58, 18, 16, 48
    largura_util = largura - esquerda - direita
    altura_util = altura - topo - base

    def px(x: float) -> float:
        return esquerda + (x - xmin) / (xmax - xmin) * largura_util

    def py(y: float) -> float:
        return topo + (ymax - y) / (ymax - ymin) * altura_util

    partes: list[str] = [
        f'<svg class="grafico" viewBox="0 0 {largura} {altura}" '
        'xmlns="http://www.w3.org/2000/svg" role="img">'
    ]

    for valor in np.linspace(xmin, xmax, 5):
        x = px(float(valor))
        partes.append(
            f'<line x1="{x:.1f}" y1="{topo}" x2="{x:.1f}" y2="{altura - base}" '
            'stroke="#e5e8e8" stroke-width="1"/>'
        )
        partes.append(
            f'<text x="{x:.1f}" y="{altura - base + 16}" font-size="10" '
            f'text-anchor="middle" fill="#5d6d7e">{_esc(_fmt(valor, 2))}</text>'
        )
    for valor in np.linspace(ymin, ymax, 5):
        y = py(float(valor))
        partes.append(
            f'<line x1="{esquerda}" y1="{y:.1f}" x2="{largura - direita}" '
            f'y2="{y:.1f}" stroke="#e5e8e8" stroke-width="1"/>'
        )
        partes.append(
            f'<text x="{esquerda - 8}" y="{y + 3:.1f}" font-size="10" '
            f'text-anchor="end" fill="#5d6d7e">{_esc(_fmt(valor, 2))}</text>'
        )

    partes.append(
        f'<rect x="{esquerda}" y="{topo}" width="{largura_util}" '
        f'height="{altura_util}" fill="none" stroke="#aab7b8" stroke-width="1"/>'
    )

    if len(xs) >= 3 and np.ptp(xs) > 0:
        inclinacao, intercepto = np.polyfit(xs, ys, 1)
        x1, x2 = xmin, xmax
        y1 = intercepto + inclinacao * x1
        y2 = intercepto + inclinacao * x2
        partes.append(
            f'<line x1="{px(x1):.1f}" y1="{py(y1):.1f}" '
            f'x2="{px(x2):.1f}" y2="{py(y2):.1f}" '
            'stroke="#c0392b" stroke-width="1.6" stroke-dasharray="5 4" opacity="0.8"/>'
        )

    for ponto in validos:
        x = px(float(ponto["x"]))
        y = py(float(ponto["y"]))
        rotulo = _esc(ponto.get("label", ""))
        partes.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="#2471a3" '
            f'fill-opacity="0.55"><title>{rotulo}</title></circle>'
        )

    partes.append(
        f'<text x="{esquerda + largura_util / 2:.1f}" y="{altura - 8}" '
        f'font-size="11" text-anchor="middle" fill="#5d6d7e">{_esc(xlab)}</text>'
    )
    partes.append(
        f'<text x="14" y="{topo + altura_util / 2:.1f}" font-size="11" '
        f'text-anchor="middle" fill="#5d6d7e" '
        f'transform="rotate(-90 14 {topo + altura_util / 2:.1f})">{_esc(ylab)}</text>'
    )
    partes.append("</svg>")
    return "".join(partes)


def _svg_histograma(
    valores: Iterable[float],
    alvo: float | None,
    largura: int = 600,
    altura: int = 250,
) -> str:
    limpos = [float(v) for v in valores if v is not None and np.isfinite(float(v))]
    if len(limpos) < 5:
        return '<p class="vazio">Benchmark indisponível: poucos pares de referência.</p>'

    bins = np.linspace(0.0, 1.0, 21)
    contagens, arestas = np.histogram(limpos, bins=bins)
    maximo = int(contagens.max()) or 1

    esquerda, direita, topo, base = 42, 16, 14, 38
    largura_util = largura - esquerda - direita
    altura_util = altura - topo - base
    largura_barra = largura_util / len(contagens)

    partes = [
        f'<svg class="grafico" viewBox="0 0 {largura} {altura}" '
        'xmlns="http://www.w3.org/2000/svg" role="img">'
    ]
    for indice, contagem in enumerate(contagens):
        x = esquerda + indice * largura_barra
        h = (contagem / maximo) * altura_util
        y = topo + altura_util - h
        partes.append(
            f'<rect x="{x + 1:.1f}" y="{y:.1f}" width="{max(largura_barra - 2, 1):.1f}" '
            f'height="{h:.1f}" fill="#5dade2" fill-opacity="0.65"/>'
        )
    for valor in (0.0, 0.25, 0.5, 0.75, 1.0):
        x = esquerda + valor * largura_util
        partes.append(
            f'<line x1="{x:.1f}" y1="{topo}" x2="{x:.1f}" y2="{topo + altura_util}" '
            'stroke="#e5e8e8" stroke-width="1"/>'
        )
        partes.append(
            f'<text x="{x:.1f}" y="{topo + altura_util + 15}" font-size="10" '
            f'text-anchor="middle" fill="#5d6d7e">{_esc(_fmt(valor, 2))}</text>'
        )
    if alvo is not None and np.isfinite(float(alvo)) and 0 <= float(alvo) <= 1:
        x = esquerda + float(alvo) * largura_util
        partes.append(
            f'<line x1="{x:.1f}" y1="{topo}" x2="{x:.1f}" y2="{topo + altura_util}" '
            'stroke="#c0392b" stroke-width="2"/>'
        )
        partes.append(
            f'<text x="{x:.1f}" y="{topo - 2}" font-size="10" '
            f'text-anchor="middle" fill="#c0392b">alvo</text>'
        )
    partes.append(
        f'<rect x="{esquerda}" y="{topo}" width="{largura_util}" '
        f'height="{altura_util}" fill="none" stroke="#aab7b8" stroke-width="1"/>'
    )
    partes.append(
        f'<text x="{esquerda + largura_util / 2:.1f}" y="{altura - 6}" '
        f'font-size="11" text-anchor="middle" fill="#5d6d7e">|r| within-local</text>'
    )
    partes.append("</svg>")
    return "".join(partes)


def _tabela_metricas(par: dict[str, Any]) -> str:
    linhas: list[tuple[str, str]] = []
    linhas.append(("r bruto", _fmt(par.get("r_bruto"), 3, True)))
    linhas.append(("r within-local", _fmt(par.get("r_dentro"), 3, True)))
    linhas.append(("r within-local + bloco", _fmt(par.get("r_bloco"), 3, True)))
    linhas.append(("r local (55 locais)", _fmt(par.get("r_local"), 3, True)))
    linhas.append(("Spearman local", _fmt(par.get("spearman_local"), 3, True)))
    ic_inf = par.get("ic_boot_inf")
    ic_sup = par.get("ic_boot_sup")
    ic = (
        f"[{_fmt(ic_inf, 2, True)}; {_fmt(ic_sup, 2, True)}]"
        if ic_inf is not None and ic_sup is not None
        else "—"
    )
    linhas.append(("IC95 bootstrap (within-local)", ic))
    linhas.append(("p permutação (focado)", _pval(par.get("p_perm"))))
    linhas.append(("p Fisher (within-local)", _pval(par.get("p_fisher"))))
    linhas.append(("q-FDR global", _pval(par.get("q_global"))))
    linhas.append(("q-FDR focado", _pval(par.get("q_focado"))))
    percentil = par.get("benchmark_percentil")
    bench = (
        f"{_fmt(percentil, 0)}º percentil de {par.get('benchmark_n', 0)} pares"
        if percentil is not None
        else f"indisponível ({par.get('benchmark_n', 0)} pares)"
    )
    linhas.append((f"Benchmark ({par.get('benchmark_tipo', '—')})", bench))
    linhas.append(
        (
            "Leave-one-local-out",
            f"[{_fmt(par.get('loo_min'), 2, True)}; "
            f"{_fmt(par.get('loo_mediana'), 2, True)}; "
            f"{_fmt(par.get('loo_max'), 2, True)}]",
        )
    )
    linhas.append(("Votos A", str(par.get("a_votos", 0))))
    linhas.append(("Votos B", str(par.get("b_votos", 0))))
    linhas.append(("Eleitores", str(par.get("n_eleitores", 0))))
    linhas.append(
        (
            "P(B|A)",
            f"{_pct(par.get('p_b_a_inf'), 1)} – {_pct(par.get('p_b_a_sup'), 1)}",
        )
    )
    linhas.append(
        (
            "P(A|B)",
            f"{_pct(par.get('p_a_b_inf'), 1)} – {_pct(par.get('p_a_b_sup'), 1)}",
        )
    )
    largura = max(
        float(par.get("largura_a") or 0), float(par.get("largura_b") or 0)
    )
    linhas.append(("Largura máxima dos limites", _pct(largura, 0)))
    linhas.append(("Flag de co-votação", str(par.get("flag_covotacao", "—"))))
    linhas.append(
        (
            "Goodman P(B|A)",
            _fmt(par.get("goodman_b_a"), 3, True)
            + (
                f" [{_fmt(par.get('goodman_b_a_inf'), 2, True)}; "
                f"{_fmt(par.get('goodman_b_a_sup'), 2, True)}]"
                if par.get("goodman_b_a_inf") is not None
                else ""
            )
            + (" !" if par.get("goodman_flag") else ""),
        )
    )
    linhas.append(
        (
            "Goodman P(A|B)",
            _fmt(par.get("goodman_a_b"), 3, True)
            + (
                f" [{_fmt(par.get('goodman_a_b_inf'), 2, True)}; "
                f"{_fmt(par.get('goodman_a_b_sup'), 2, True)}]"
                if par.get("goodman_a_b_inf") is not None
                else ""
            )
            + (" !" if par.get("goodman_flag") else ""),
        )
    )
    corpo = "".join(
        f"<tr><th>{_esc(rotulo)}</th><td class=\"num\">{_esc(valor)}</td></tr>"
        for rotulo, valor in linhas
    )
    return f'<table class="metricas"><tbody>{corpo}</tbody></table>'


def _tabela_locais(par: dict[str, Any]) -> str:
    locais = sorted(
        par.get("locais", []),
        key=lambda local: (
            max(local.get("largura_a") or 0, local.get("largura_b") or 0),
            -(local.get("ab_n") or 0),
        ),
    )
    if not locais:
        return '<p class="vazio">Sem dados por local.</p>'
    max_ab = max((local.get("ab_n") or 0) for local in locais)
    nota = (
        "Nenhum local tem (a+b)/N ≥ 100%: os limites inferiores ficam em 0 e os "
        "superiores em min(a,b)."
        if max_ab < 1
        else "Há local(is) com (a+b)/N ≥ 100%; nesses casos o limite inferior é positivo."
    )
    linhas = []
    for local in locais:
        largura = max(local.get("largura_a") or 0, local.get("largura_b") or 0)
        linhas.append(
            "<tr>"
            f"<td>{_esc(local.get('local'))}</td>"
            f"<td>{local.get('a', 0)}</td>"
            f"<td>{local.get('b', 0)}</td>"
            f"<td>{local.get('n', 0)}</td>"
            f"<td>{_pct(local.get('ab_n'), 0)}</td>"
            f"<td>{_pct(local.get('p_b_a_inf'), 0)}–{_pct(local.get('p_b_a_sup'), 0)}</td>"
            f"<td>{_pct(local.get('p_a_b_inf'), 0)}–{_pct(local.get('p_a_b_sup'), 0)}</td>"
            f"<td>{_pct(largura, 0)}</td>"
            "</tr>"
        )
    cabecalho = (
        "<thead><tr>"
        "<th>Local</th><th>a</th><th>b</th><th>N</th><th>(a+b)/N</th>"
        "<th>P(B|A)</th><th>P(A|B)</th><th>largura</th>"
        "</tr></thead>"
    )
    return (
        f'<p class="legenda">{_esc(nota)}</p>'
        '<table class="locais">'
        f"{cabecalho}<tbody>{''.join(linhas)}</tbody></table>"
    )


def _conclusao(par: dict[str, Any]) -> str:
    flag = par.get("flag_covotacao", "indeterminado")
    if flag == "informativo":
        leitura = (
            "Limites estreitos: há informação sobre co-votação. Ainda assim, é uma "
            "estimativa ecológica; não prova o voto individual."
        )
    else:
        leitura = (
            "Limites largos: os dados <strong>não identificam</strong> a co-votação "
            "individual deste par."
        )
    p_perm = par.get("p_perm")
    q_global = par.get("q_global")
    q_focado = par.get("q_focado")
    inferencia = (
        f"p permutação focado = {_pval(p_perm)}; "
        f"q-FDR focado = {_pval(q_focado)}; "
        f"q-FDR global = {_pval(q_global)}."
    )
    if p_perm is not None and q_global is not None:
        if p_perm < 0.05 and q_global < 0.05:
            inferencia += " A associação passa tanto no teste focado quanto no FDR global."
        elif p_perm < 0.05:
            inferencia += (
                " A associação é sugestiva no teste focado, mas não passa no FDR global; "
                "trate como hipótese, não como resultado confirmado."
            )
        else:
            inferencia += " Não há evidência suficiente de associação within-local."
    percentil = par.get("benchmark_percentil")
    if percentil is not None:
        inferencia += (
            f" O par está no {_fmt(percentil, 0)}º percentil de |r| entre "
            f"{par.get('benchmark_n', 0)} pares de referência."
        )
    loo_min = par.get("loo_min")
    loo_max = par.get("loo_max")
    if loo_min is not None and loo_max is not None:
        inferencia += (
            f" Leave-one-local-out: r within-local entre {_fmt(loo_min, 2, True)} "
            f"e {_fmt(loo_max, 2, True)}."
        )
    if par.get("goodman_flag"):
        inferencia += (
            " Goodman tem parâmetro fora de [0,1]; não use a estimativa como verdade."
        )
    return (
        '<div class="conclusao">'
        f"<p><strong>{_esc(flag)}</strong> — {leitura}</p>"
        f"<p>{_esc(inferencia)}</p>"
        "</div>"
    )


def _bloco_par(par: dict[str, Any]) -> str:
    a = par.get("a", {})
    b = par.get("b", {})
    rotulo_a = a.get("rotulo", "A")
    rotulo_b = b.get("rotulo", "B")
    flag = par.get("flag_covotacao", "")
    pontos_local = [
        {
            "x": local.get("share_a"),
            "y": local.get("share_b"),
            "label": f"{local.get('local')} (N={local.get('n')})",
        }
        for local in par.get("locais", [])
    ]
    pontos_resid = [
        {
            "x": ponto.get("ra"),
            "y": ponto.get("rb"),
            "label": f"{ponto.get('local')} {ponto.get('urna')}",
        }
        for ponto in par.get("pontos", [])
    ]
    alvo = abs(float(par.get("r_dentro"))) if par.get("r_dentro") is not None else None
    return (
        '<section class="par">'
        '<div class="cabecalho">'
        f"<h2>{_esc(rotulo_a)} × {_esc(rotulo_b)}</h2>"
        f'<span class="tag {_esc(flag)}">{_esc(flag)}</span>'
        "</div>"
        '<p class="legenda">'
        f"{_esc(a.get('cargo'))} {_esc(a.get('numero'))} × "
        f"{_esc(b.get('cargo'))} {_esc(b.get('numero'))} · "
        f"{par.get('n_urnas', 0)} urnas · {par.get('n_locais', 0)} locais"
        "</p>"
        '<div class="grade">'
        '<div class="painel"><h4>Dispersão por local — shares</h4>'
        + _svg_scatter(pontos_local, "share A (votos válidos)", "share B (votos válidos)")
        + "</div>"
        '<div class="painel"><h4>Resíduos within-local</h4>'
        + _svg_scatter(
            pontos_resid,
            "resíduo log-odds A",
            "resíduo log-odds B",
        )
        + "</div>"
        "</div>"
        "<h3>Métricas</h3>"
        + _tabela_metricas(par)
        + "<h3>Benchmark</h3>"
        + '<div class="painel"><h4>Distribuição de |r| within-local na referência</h4>'
        + _svg_histograma(
            par.get("benchmark_valores", []),
            alvo,
        )
        + "</div>"
        + "<details><summary>Limites de co-votação por local</summary>"
        + _tabela_locais(par)
        + "</details>"
        + _conclusao(par)
        + "</section>"
    )


def render_focado(payload: dict[str, Any]) -> str:
    """Monta o HTML standalone a partir do payload de `montar_payload_focado`."""

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    meta = payload.get("meta", {})
    pares = payload.get("pares", [])
    subtitulo = (
        f"{meta.get('municipio') or 'município'} · {meta.get('ano') or ''} · "
        f"{meta.get('n_urnas', 0)} urnas · {meta.get('n_locais', 0)} locais"
    )
    resumo = meta.get("resumo", {})
    cards = "".join(
        [
            _card(meta.get("n_urnas", 0), "urnas"),
            _card(meta.get("n_locais", 0), "locais (clusters)"),
            _card(len(pares), "pares analisados"),
            _card(resumo.get("informativo", 0), "pares informativos"),
        ]
    )
    conteudo = "".join(_bloco_par(par) for par in pares)
    return (
        template.replace("__SUBTITULO__", _esc(subtitulo))
        .replace("__CARDS__", cards)
        .replace("__PARES__", conteudo)
    )
