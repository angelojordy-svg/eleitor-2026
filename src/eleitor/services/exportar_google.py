"""Exporta o mapa eleitoral para Google Earth (KML) e Google My Maps (CSV).

O Google Earth/Maps não executa JavaScript, então a comparação A×B é gravada
no arquivo. Cada local vira um Placemark com balão HTML, cor por vencedor (ou
diferença) e tamanho proporcional aos aptos (ou votos).
"""

from __future__ import annotations

import csv
import io
import math
import unicodedata
from dataclasses import dataclass, field
from html import escape as html_escape
from pathlib import Path
from typing import Any, Sequence
from xml.sax.saxutils import escape as xml_escape

ICONE_GOOGLE = "https://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"
NEUTRO = "#cbd5e1"

CORES_PARTIDO = {
    "PT": "#f20d33", "PL": "#330df2", "UNIÃO": "#f27f0d", "PP": "#bd0df2",
    "MDB": "#adf20d", "PSD": "#0df2db", "REPUBLICANOS": "#0df259",
    "PSDB": "#0d78f2", "PDT": "#f20d0d", "PSB": "#f2cc0d", "PODE": "#f20d9e",
    "PODEMOS": "#f20d9e", "PSOL": "#f24a0d", "NOVO": "#f2330d",
    "SOLIDARIEDADE": "#f21c0d", "CIDADANIA": "#f20d69", "PC do B": "#f20d4a",
    "PV": "#4af20d", "REDE": "#0df296", "AVANTE": "#f2f20d", "MOBILIZA": "#f20df2",
    "DEMOCRATA": "#0d1cf2", "PSTU": "#f20d80", "PCO": "#f20d1c", "PCB": "#f20dcc",
    "UP": "#780df2", "DC": "#0d3bf2", "MISSÃO": "#0df270", "PRTB": "#f2690d",
    "AGIR": "#870df2", "PSDC": "#0ddbf2", "PMN": "#0df2bd", "PTC": "#f2b50d",
}
PALETA_FALLBACK = (
    "#0f766e", "#7c3aed", "#b45309", "#be123c", "#0e7490", "#4d7c0f",
    "#a21caf", "#1d4ed8",
)


class ExportError(Exception):
    """Cargo/candidato inválido ou combinação de opções inconsistente."""


@dataclass
class LinhaComparacao:
    indice: int
    local: dict[str, Any]
    votos_a: int
    votos_b: int
    pct_a: float
    pct_b: float
    margem: float
    vencedor: str
    faixa: str
    top: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Comparacao:
    cargo: dict[str, Any]
    cand_a: dict[str, Any]
    cand_b: dict[str, Any]
    linhas: list[LinhaComparacao]
    total_a: int
    total_b: int
    pct_a: float
    pct_b: float
    locais_a: int
    locais_b: int
    empates: int
    max_aptos: int
    max_votos: int
    max_margem: float


def _slug(texto: Any) -> str:
    bruto = unicodedata.normalize("NFKD", str(texto or ""))
    sem_acento = "".join(c for c in bruto if not unicodedata.combining(c))
    return "".join(c if c.isalnum() else "-" for c in sem_acento.lower()).strip("-")


def _num(valor: Any) -> str:
    try:
        return f"{int(valor):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def _pct(valor: float) -> str:
    return f"{valor:.1f}".replace(".", ",") + "%"


def _pct_csv(valor: float) -> str:
    return f"{valor:.2f}"


def _faixa(margem: float) -> str:
    if abs(margem) < 3:
        return "Empate"
    if margem > 0:
        return "A forte" if margem >= 10 else "A"
    return "B forte" if margem <= -10 else "B"


def cor_partido(partido: Any) -> str:
    sigla = str(partido or "").strip().upper()
    if sigla in CORES_PARTIDO:
        return CORES_PARTIDO[sigla]
    hash_ = 0
    for ch in sigla:
        hash_ = (hash_ * 31 + ord(ch)) & 0xFFFFFFFF
    return PALETA_FALLBACK[hash_ % len(PALETA_FALLBACK)]


def _hex_rgb(cor: str) -> tuple[int, int, int]:
    bruto = str(cor).lstrip("#")
    if len(bruto) == 3:
        bruto = "".join(c * 2 for c in bruto)
    if len(bruto) != 6:
        return (100, 116, 139)
    return (int(bruto[0:2], 16), int(bruto[2:4], 16), int(bruto[4:6], 16))


def mix_hex(cor1: str, cor2: str, t: float) -> str:
    f = max(0.0, min(1.0, t))
    a = _hex_rgb(cor1)
    b = _hex_rgb(cor2)
    return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b))


def kml_color(cor: str, alpha: int = 0xFF) -> str:
    r, g, b = _hex_rgb(cor)
    return f"{max(0, min(255, int(alpha))):02x}{b:02x}{g:02x}{r:02x}"


def _xml(texto: Any) -> str:
    return xml_escape(str(texto or ""))


def _cdata(texto: str) -> str:
    return "<![CDATA[" + texto.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def _cargo_por_nome(payload: dict[str, Any], nome: str) -> dict[str, Any]:
    alvo = _slug(nome)
    for cargo in payload.get("cargos", []):
        if alvo in {_slug(cargo.get("id")), _slug(cargo.get("nome"))}:
            return cargo
    disponiveis = ", ".join(cargo.get("nome", "?") for cargo in payload.get("cargos", []))
    raise ExportError(f"Cargo '{nome}' não encontrado. Disponíveis: {disponiveis}.")


def _indice_candidato(cargo: dict[str, Any], numero: Any) -> int:
    for indice, cand in enumerate(cargo.get("cands", [])):
        if str(cand.get("n")) == str(numero):
            return indice
    exemplos = "; ".join(
        f"{cand.get('n')} — {cand.get('nome')} ({cand.get('p')})"
        for cand in cargo.get("cands", [])[:10]
    )
    raise ExportError(
        f"Candidato '{numero}' não encontrado em {cargo.get('nome')}. "
        f"Primeiros candidatos: {exemplos}."
    )


def _top_local(cargo: dict[str, Any], indice_local: int, quantidade: int = 5) -> list[dict[str, Any]]:
    validos = cargo["validos"][indice_local] or 0
    itens: list[dict[str, Any]] = []
    for indice, cand in enumerate(cargo.get("cands", [])):
        votos = cargo["votos"][indice_local][indice]
        if votos <= 0:
            continue
        itens.append(
            {
                "numero": cand.get("n", ""),
                "nome": cand.get("nome", ""),
                "partido": cand.get("p", ""),
                "votos": votos,
                "pct": (votos * 100.0 / validos) if validos else 0.0,
            }
        )
    itens.sort(key=lambda item: (-item["votos"], item["nome"].lower()))
    return itens[:quantidade]


def comparar(
    payload: dict[str, Any],
    cargo_nome: str,
    a: Any = None,
    b: Any = None,
) -> Comparacao:
    """Resolve o cargo e os candidatos e calcula A×B em cada local."""

    cargo = _cargo_por_nome(payload, cargo_nome)
    if not cargo.get("cands"):
        raise ExportError(f"O cargo {cargo.get('nome')} não tem candidatos no payload.")

    ia = _indice_candidato(cargo, a) if a not in (None, "") else 0
    if b not in (None, ""):
        ib = _indice_candidato(cargo, b)
    else:
        ib = next(
            (indice for indice in range(len(cargo["cands"])) if indice != ia),
            ia,
        )
    if ia == ib:
        raise ExportError("Os candidatos A e B precisam ser diferentes.")

    cand_a = cargo["cands"][ia]
    cand_b = cargo["cands"][ib]
    locais = payload.get("locais", [])
    linhas: list[LinhaComparacao] = []
    locais_a = locais_b = empates = 0

    for indice, local in enumerate(locais):
        validos = cargo["validos"][indice] or 0
        votos_a = cargo["votos"][indice][ia]
        votos_b = cargo["votos"][indice][ib]
        pct_a = (votos_a * 100.0 / validos) if validos else 0.0
        pct_b = (votos_b * 100.0 / validos) if validos else 0.0
        margem = pct_a - pct_b
        if abs(margem) < 1e-9:
            vencedor = "Empate"
            empates += 1
        elif margem > 0:
            vencedor = "A"
            locais_a += 1
        else:
            vencedor = "B"
            locais_b += 1
        linhas.append(
            LinhaComparacao(
                indice=indice,
                local=local,
                votos_a=votos_a,
                votos_b=votos_b,
                pct_a=pct_a,
                pct_b=pct_b,
                margem=margem,
                vencedor=vencedor,
                faixa=_faixa(margem),
                top=_top_local(cargo, indice),
            )
        )

    validos_total = cargo.get("totais", {}).get("validos", 0) or 0
    total_a = int(cand_a.get("total", 0))
    total_b = int(cand_b.get("total", 0))
    max_aptos = max((int(local.get("aptos", 0)) for local in locais), default=0)
    max_votos = max((max(linha.votos_a, linha.votos_b) for linha in linhas), default=0)
    maior_margem = max((abs(linha.margem) for linha in linhas), default=0.0)

    return Comparacao(
        cargo=cargo,
        cand_a=cand_a,
        cand_b=cand_b,
        linhas=linhas,
        total_a=total_a,
        total_b=total_b,
        pct_a=(total_a * 100.0 / validos_total) if validos_total else 0.0,
        pct_b=(total_b * 100.0 / validos_total) if validos_total else 0.0,
        locais_a=locais_a,
        locais_b=locais_b,
        empates=empates,
        max_aptos=max_aptos,
        max_votos=max_votos,
        max_margem=min(40.0, max(12.0, maior_margem)),
    )


def _cor_linha(comp: Comparacao, linha: LinhaComparacao, modo: str) -> tuple[str, int]:
    cor_a = cor_partido(comp.cand_a.get("p"))
    cor_b = cor_partido(comp.cand_b.get("p"))
    if linha.vencedor == "Empate":
        return NEUTRO, 0x99
    cor = cor_a if linha.vencedor == "A" else cor_b
    if modo == "diferenca":
        t = (min(1.0, abs(linha.margem) / max(1.0, comp.max_margem))) ** 0.65
        return mix_hex(NEUTRO, cor, t), 0xEE
    t = min(1.0, abs(linha.margem) / max(1.0, comp.max_margem))
    return cor, int(0x66 + 0x99 * t)


def _escala_icone(comp: Comparacao, linha: LinhaComparacao, tamanho: str) -> float:
    if tamanho == "votos":
        valor = max(linha.votos_a, linha.votos_b)
        maximo = max(1, comp.max_votos)
    else:
        valor = int(linha.local.get("aptos", 0))
        maximo = max(1, comp.max_aptos)
    return round(0.8 + 1.2 * math.sqrt(max(0, valor) / maximo), 2)


def _link_maps(local: dict[str, Any]) -> str:
    return (
        "https://www.google.com/maps/search/?api=1&query="
        f"{float(local.get('lat', 0)):.7f},{float(local.get('lon', 0)):.7f}"
    )


def _descricao_html(comp: Comparacao, linha: LinhaComparacao) -> str:
    local = linha.local
    cor_a = cor_partido(comp.cand_a.get("p"))
    cor_b = cor_partido(comp.cand_b.get("p"))
    comp_pct = (float(local.get("comp", 0)) * 100.0 / local["aptos"]) if local.get("aptos") else 0.0
    nome_a = html_escape(str(comp.cand_a.get("nome", "")))
    nome_b = html_escape(str(comp.cand_b.get("nome", "")))
    partido_a = html_escape(str(comp.cand_a.get("p", "")))
    partido_b = html_escape(str(comp.cand_b.get("p", "")))
    margem = linha.pct_a - linha.pct_b
    if linha.vencedor == "Empate":
        texto_margem = "Empate"
    else:
        valor_margem = f"{abs(margem):.1f}".replace(".", ",")
        texto_margem = f"{'A' if margem > 0 else 'B'} +{valor_margem} p.p."

    linhas_top = []
    for item in linha.top:
        linhas_top.append(
            "<tr>"
            f"<td style='padding:2px 4px'>{html_escape(str(item['nome']))}</td>"
            f"<td style='padding:2px 4px;color:#5b6b7c'>{html_escape(str(item['partido']))}</td>"
            f"<td style='padding:2px 4px;text-align:right'>{_num(item['votos'])}</td>"
            f"<td style='padding:2px 4px;text-align:right;color:#5b6b7c'>{_pct(item['pct'])}</td>"
            "</tr>"
        )
    tabela_top = (
        "<table style='width:100%;border-collapse:collapse;font-size:12px'>"
        "<tr style='color:#5b6b7c;font-size:10px;text-transform:uppercase'>"
        "<th style='text-align:left;padding:2px 4px'>Candidato</th>"
        "<th style='text-align:left;padding:2px 4px'>Partido</th>"
        "<th style='text-align:right;padding:2px 4px'>Votos</th>"
        "<th style='text-align:right;padding:2px 4px'>%</th></tr>"
        + "".join(linhas_top)
        + "</table>"
    ) if linhas_top else "<p style='font-size:12px;color:#5b6b7c'>Sem votos nominais neste local.</p>"

    linhas_urnas = []
    for urna in local.get("urnas", []):
        agregada = str(urna.get("agrega") or "")
        secao = html_escape(str(urna.get("secao", "")))
        if agregada and agregada != "—":
            secao += f" (+{html_escape(agregada)})"
        linhas_urnas.append(
            "<tr>"
            f"<td style='padding:2px 4px'>{secao}</td>"
            f"<td style='padding:2px 4px'>{html_escape(str(urna.get('urna') or '—'))}</td>"
            f"<td style='padding:2px 4px;text-align:right'>{_num(urna.get('aptos', 0))}</td>"
            f"<td style='padding:2px 4px;text-align:right'>{_num(urna.get('comp', 0))}</td>"
            f"<td style='padding:2px 4px;text-align:right'>{_num(urna.get('abst', 0))}</td>"
            "</tr>"
        )
    tabela_urnas = (
        "<table style='width:100%;border-collapse:collapse;font-size:11px'>"
        "<tr style='color:#5b6b7c;font-size:10px;text-transform:uppercase'>"
        "<th style='text-align:left;padding:2px 4px'>Seção</th>"
        "<th style='text-align:left;padding:2px 4px'>Urna</th>"
        "<th style='text-align:right;padding:2px 4px'>Aptos</th>"
        "<th style='text-align:right;padding:2px 4px'>Comp.</th>"
        "<th style='text-align:right;padding:2px 4px'>Abst.</th></tr>"
        + "".join(linhas_urnas)
        + "</table>"
    ) if linhas_urnas else "<p style='font-size:12px;color:#5b6b7c'>Sem urnas detalhadas.</p>"

    return (
        "<div style='font-family:Segoe UI,Arial,sans-serif;color:#17253a;width:330px'>"
        f"<div style='font-size:10px;color:#5b6b7c;text-transform:uppercase;letter-spacing:.06em'>"
        f"Zona {html_escape(str(local.get('zona', '')))} · local {html_escape(str(local.get('codigo', '')))}"
        f" · {html_escape(str(comp.cargo.get('nome', '')))}</div>"
        f"<h3 style='margin:4px 0;font-size:15px'>{html_escape(str(local.get('nome', '')))}</h3>"
        f"<div style='font-size:12px;color:#5b6b7c'>"
        f"{html_escape(str(local.get('endereco') or 'Endereço não informado'))}"
        f"{' · ' + html_escape(str(local.get('bairro'))) if local.get('bairro') else ''}</div>"
        "<table style='width:100%;margin:8px 0;font-size:12px;border-collapse:collapse'><tr>"
        f"<td><b>{_num(local.get('aptos', 0))}</b><br><span style='color:#5b6b7c'>aptos</span></td>"
        f"<td><b>{_num(local.get('comp', 0))}</b><br><span style='color:#5b6b7c'>compareceram ({_pct(comp_pct)})</span></td>"
        f"<td><b>{_num(local.get('abst', 0))}</b><br><span style='color:#5b6b7c'>abstenções</span></td>"
        f"<td><b>{len(local.get('urnas', []))}</b><br><span style='color:#5b6b7c'>urnas</span></td>"
        "</tr></table>"
        "<div style='margin:8px 0'>"
        f"<div style='font-size:12px'><b style='color:{cor_a}'>A · {nome_a} ({partido_a})</b>"
        f"<span style='float:right'>{_pct(linha.pct_a)} · {_num(linha.votos_a)}</span></div>"
        "<div style='background:#e8eef5;height:8px;border-radius:4px;margin:2px 0 6px'>"
        f"<div style='width:{min(100.0, linha.pct_a):.1f}%;background:{cor_a};height:8px;border-radius:4px'></div></div>"
        f"<div style='font-size:12px'><b style='color:{cor_b}'>B · {nome_b} ({partido_b})</b>"
        f"<span style='float:right'>{_pct(linha.pct_b)} · {_num(linha.votos_b)}</span></div>"
        "<div style='background:#e8eef5;height:8px;border-radius:4px;margin:2px 0'>"
        f"<div style='width:{min(100.0, linha.pct_b):.1f}%;background:{cor_b};height:8px;border-radius:4px'></div></div>"
        "</div>"
        f"<div style='font-size:12px;margin:6px 0'><b>Vantagem:</b> {texto_margem}</div>"
        "<h4 style='font-size:11px;text-transform:uppercase;color:#5b6b7c;margin:10px 0 4px'>Top 5 no local</h4>"
        f"{tabela_top}"
        f"<h4 style='font-size:11px;text-transform:uppercase;color:#5b6b7c;margin:10px 0 4px'>Urnas ({len(local.get('urnas', []))})</h4>"
        f"{tabela_urnas}"
        f"<p style='font-size:12px;margin:10px 0 0'><a href='{html_escape(_link_maps(local), quote=True)}'>Abrir no Google Maps</a></p>"
        "<p style='font-size:10px;color:#5b6b7c;margin:6px 0 0'>"
        "1 pino = 1 local de votação; as urnas do mesmo local estão agregadas.</p>"
        "</div>"
    )


def _extended_data(comp: Comparacao, linha: LinhaComparacao) -> str:
    campos = {
        "Zona": linha.local.get("zona", ""),
        "Codigo": linha.local.get("codigo", ""),
        "Local": linha.local.get("nome", ""),
        "Bairro": linha.local.get("bairro", ""),
        "Endereco": linha.local.get("endereco", ""),
        "Aptos": linha.local.get("aptos", 0),
        "Comparecimento": linha.local.get("comp", 0),
        "Abstencao": linha.local.get("abst", 0),
        "Cargo": comp.cargo.get("nome", ""),
        "CandidatoA": comp.cand_a.get("nome", ""),
        "PartidoA": comp.cand_a.get("p", ""),
        "VotosA": linha.votos_a,
        "PercentualA": f"{linha.pct_a:.2f}",
        "CandidatoB": comp.cand_b.get("nome", ""),
        "PartidoB": comp.cand_b.get("p", ""),
        "VotosB": linha.votos_b,
        "PercentualB": f"{linha.pct_b:.2f}",
        "Vencedor": linha.vencedor,
        "CandidatoVencedor": (
            comp.cand_a.get("nome", "") if linha.vencedor == "A"
            else comp.cand_b.get("nome", "") if linha.vencedor == "B"
            else "Empate"
        ),
        "PartidoVencedor": (
            comp.cand_a.get("p", "") if linha.vencedor == "A"
            else comp.cand_b.get("p", "") if linha.vencedor == "B"
            else ""
        ),
        "Margem": f"{linha.margem:.2f}",
        "Faixa": linha.faixa,
        "Urnas": len(linha.local.get("urnas", [])),
    }
    itens = "".join(
        f"<Data name='{_xml(nome)}'><value>{_xml(valor)}</value></Data>"
        for nome, valor in campos.items()
    )
    return f"<ExtendedData>{itens}</ExtendedData>"


def _placemark(comp: Comparacao, linha: LinhaComparacao, modo: str, tamanho: str) -> str:
    cor, alpha = _cor_linha(comp, linha, modo)
    escala = _escala_icone(comp, linha, tamanho)
    local = linha.local
    snippet = (
        f"A {_pct(linha.pct_a)} × B {_pct(linha.pct_b)} · "
        f"{_num(local.get('aptos', 0))} aptos"
    )
    return (
        "<Placemark>"
        f"<name>{_xml(local.get('nome', ''))}</name>"
        f"<Snippet maxLines='2'>{_xml(snippet)}</Snippet>"
        f"<description>{_cdata(_descricao_html(comp, linha))}</description>"
        f"{_extended_data(comp, linha)}"
        "<Style>"
        "<IconStyle>"
        f"<color>{kml_color(cor, alpha)}</color>"
        f"<scale>{escala}</scale>"
        f"<Icon><href>{ICONE_GOOGLE}</href></Icon>"
        "</IconStyle>"
        "<LabelStyle><scale>0</scale></LabelStyle>"
        "<BalloonStyle><text>$[description]</text></BalloonStyle>"
        "</Style>"
        f"<Point><coordinates>{float(local.get('lon', 0)):.7f},"
        f"{float(local.get('lat', 0)):.7f},0</coordinates></Point>"
        "</Placemark>"
    )


def _folder(comp: Comparacao, modo: str, tamanho: str, visivel: bool) -> str:
    nome = (
        f"{comp.cargo.get('nome', '')} — "
        f"{comp.cand_a.get('nome', '')} × {comp.cand_b.get('nome', '')}"
    )
    descricao = (
        f"{comp.cargo.get('nome', '')}: "
        f"A {comp.cand_a.get('nome', '')} ({comp.cand_a.get('p', '')}) "
        f"{_pct(comp.pct_a)} · B {comp.cand_b.get('nome', '')} "
        f"({comp.cand_b.get('p', '')}) {_pct(comp.pct_b)}. "
        f"Locais vencidos: A {comp.locais_a} · B {comp.locais_b} · "
        f"empates {comp.empates}."
    )
    placemarks = "".join(_placemark(comp, linha, modo, tamanho) for linha in comp.linhas)
    return (
        "<Folder>"
        f"<name>{_xml(nome)}</name>"
        f"<description>{_cdata(descricao)}</description>"
        f"<visibility>{1 if visivel else 0}</visibility>"
        f"<open>{1 if visivel else 0}</open>"
        f"{placemarks}"
        "</Folder>"
    )


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    raio = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * raio * math.asin(math.sqrt(a))


def _look_at(payload: dict[str, Any]) -> str:
    locais = payload.get("locais", [])
    if not locais:
        return ""
    lats = [float(local.get("lat", 0)) for local in locais]
    lons = [float(local.get("lon", 0)) for local in locais]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    centro_lat = (min_lat + max_lat) / 2
    centro_lon = (min_lon + max_lon) / 2
    diagonal = _haversine(min_lat, min_lon, max_lat, max_lon)
    alcance = max(2_000.0, diagonal * 1.4)
    return (
        "<LookAt>"
        f"<longitude>{centro_lon:.7f}</longitude>"
        f"<latitude>{centro_lat:.7f}</latitude>"
        "<altitude>0</altitude>"
        "<heading>0</heading>"
        "<tilt>0</tilt>"
        f"<range>{alcance:.0f}</range>"
        "</LookAt>"
    )


def _descricao_documento(payload: dict[str, Any], modo: str, tamanho: str) -> str:
    meta = payload.get("meta", {})
    return (
        f"<h2>Mapa eleitoral — {html_escape(str(meta.get('municipio', '')))}</h2>"
        f"<p>{html_escape(str(meta.get('eleicao', '')))}</p>"
        f"<p><b>{_num(meta.get('total_locais', 0))}</b> locais · "
        f"<b>{_num(meta.get('total_urnas', 0))}</b> urnas · "
        f"<b>{_num(meta.get('total_aptos', 0))}</b> eleitores aptos</p>"
        f"<p>Fonte: {html_escape(str(meta.get('fonte', 'TSE — Boletim de Urna')))}</p>"
        "<p>1 pino = 1 local de votação; as urnas do mesmo local estão agregadas. "
        "Clique no pino para ver o balão com A × B, top 5 e as urnas.</p>"
        f"<p>Modo: <b>{html_escape(modo)}</b> · Tamanho do pino: "
        f"<b>{html_escape(tamanho)}</b>.</p>"
        "<p>A comparação é estática (Google Earth/Maps não executam JavaScript). "
        "Para trocar os candidatos, regenere o arquivo com --cargo/--a/--b.</p>"
    )


def gerar_kml(
    payload: dict[str, Any],
    cargos: Sequence[str] | None = None,
    modo: str = "vencedor",
    tamanho: str = "aptos",
    a: Any = None,
    b: Any = None,
) -> str:
    """KML combinado (pastas por cargo) ou de um cargo (placemarks planos)."""

    if modo not in {"vencedor", "diferenca"}:
        raise ExportError("Modo inválido: use 'vencedor' ou 'diferenca'.")
    if tamanho not in {"aptos", "votos"}:
        raise ExportError("Tamanho inválido: use 'aptos' ou 'votos'.")

    nomes = list(cargos) if cargos else [cargo["nome"] for cargo in payload.get("cargos", [])]
    if not nomes:
        raise ExportError("O payload não tem cargos.")
    if len(nomes) > 1 and (a not in (None, "") or b not in (None, "")):
        raise ExportError("--a/--b só podem ser usados com um único --cargo.")

    meta = payload.get("meta", {})
    titulo = f"Mapa eleitoral — {meta.get('municipio', 'município')} — {meta.get('ano', '')}"
    descricao = _descricao_documento(payload, modo, tamanho)
    corpo: list[str] = []

    if len(nomes) == 1:
        comp = comparar(payload, nomes[0], a=a, b=b)
        corpo.extend(_placemark(comp, linha, modo, tamanho) for linha in comp.linhas)
    else:
        for indice, nome in enumerate(nomes):
            comp = comparar(payload, nome)
            visivel = _slug(comp.cargo.get("nome")) == "governador"
            if not any(_slug(item) == "governador" for item in nomes):
                visivel = indice == 0
            corpo.append(_folder(comp, modo, tamanho, visivel))

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
        "<Document>\n"
        f"<name>{_xml(titulo)}</name>\n"
        f"<description>{_cdata(descricao)}</description>\n"
        f"{_look_at(payload)}\n"
        + "\n".join(corpo)
        + "\n</Document>\n</kml>\n"
    )


CABECALHO_CSV = [
    "Latitude",
    "Longitude",
    "Local",
    "Zona",
    "Codigo",
    "Bairro",
    "Endereco",
    "Aptos",
    "Comparecimento",
    "Abstencao",
    "Cargo",
    "Candidato A",
    "Partido A",
    "Votos A",
    "Percentual A",
    "Candidato B",
    "Partido B",
    "Votos B",
    "Percentual B",
    "Vencedor",
    "Candidato vencedor",
    "Partido vencedor",
    "Margem (p.p.)",
    "Faixa",
    "Urnas",
    "Link Google Maps",
]


def gerar_csv(
    payload: dict[str, Any],
    cargo: str,
    a: Any = None,
    b: Any = None,
) -> str:
    """CSV para importação no Google My Maps (uma linha por local)."""

    comp = comparar(payload, cargo, a=a, b=b)
    saida = io.StringIO()
    escritor = csv.writer(saida, lineterminator="\n")
    escritor.writerow(CABECALHO_CSV)
    for linha in comp.linhas:
        local = linha.local
        vencedor_nome = (
            comp.cand_a.get("nome", "") if linha.vencedor == "A"
            else comp.cand_b.get("nome", "") if linha.vencedor == "B"
            else "Empate"
        )
        vencedor_partido = (
            comp.cand_a.get("p", "") if linha.vencedor == "A"
            else comp.cand_b.get("p", "") if linha.vencedor == "B"
            else ""
        )
        escritor.writerow(
            [
                f"{float(local.get('lat', 0)):.7f}",
                f"{float(local.get('lon', 0)):.7f}",
                local.get("nome", ""),
                local.get("zona", ""),
                local.get("codigo", ""),
                local.get("bairro", ""),
                local.get("endereco", ""),
                local.get("aptos", 0),
                local.get("comp", 0),
                local.get("abst", 0),
                comp.cargo.get("nome", ""),
                comp.cand_a.get("nome", ""),
                comp.cand_a.get("p", ""),
                linha.votos_a,
                _pct_csv(linha.pct_a),
                comp.cand_b.get("nome", ""),
                comp.cand_b.get("p", ""),
                linha.votos_b,
                _pct_csv(linha.pct_b),
                linha.vencedor,
                vencedor_nome,
                vencedor_partido,
                f"{linha.margem:.2f}",
                linha.faixa,
                len(local.get("urnas", [])),
                _link_maps(local),
            ]
        )
    return saida.getvalue()


def _base_nome(payload: dict[str, Any]) -> str:
    meta = payload.get("meta", {})
    municipio = str(meta.get("municipio") or "municipio").split("/")[0].strip()
    ano = meta.get("ano") or 2026
    return f"mapa_eleitoral_{_slug(municipio)}_{ano}"


def exportar_google(
    payload: dict[str, Any],
    destino: str | Path,
    cargo: str | None = None,
    a: Any = None,
    b: Any = None,
    modo: str = "vencedor",
    tamanho: str = "aptos",
) -> list[Path]:
    """Grava KML(s) e CSV(s) e devolve os caminhos criados."""

    if (a not in (None, "") or b not in (None, "")) and not cargo:
        raise ExportError("--a/--b exigem --cargo.")
    pasta = Path(destino)
    pasta.mkdir(parents=True, exist_ok=True)
    base = _base_nome(payload)
    arquivos: list[Path] = []

    if cargo:
        nome_cargo = _cargo_por_nome(payload, cargo)["nome"]
        sufixo = _slug(nome_cargo)
        caminho_kml = pasta / f"{base}_{sufixo}.kml"
        caminho_kml.write_text(
            gerar_kml(payload, [nome_cargo], modo=modo, tamanho=tamanho, a=a, b=b),
            encoding="utf-8",
        )
        arquivos.append(caminho_kml)
        caminho_csv = pasta / f"{base}_{sufixo}_my_maps.csv"
        with caminho_csv.open("w", encoding="utf-8-sig", newline="") as fh:
            fh.write(gerar_csv(payload, nome_cargo, a=a, b=b))
        arquivos.append(caminho_csv)
        return arquivos

    caminho_todos = pasta / f"{base}_todos.kml"
    caminho_todos.write_text(
        gerar_kml(payload, modo=modo, tamanho=tamanho),
        encoding="utf-8",
    )
    arquivos.append(caminho_todos)

    for item in payload.get("cargos", []):
        nome_cargo = item.get("nome", "")
        if not nome_cargo:
            continue
        sufixo = _slug(nome_cargo)
        caminho_kml = pasta / f"{base}_{sufixo}.kml"
        caminho_kml.write_text(
            gerar_kml(payload, [nome_cargo], modo=modo, tamanho=tamanho),
            encoding="utf-8",
        )
        arquivos.append(caminho_kml)
        caminho_csv = pasta / f"{base}_{sufixo}_my_maps.csv"
        with caminho_csv.open("w", encoding="utf-8-sig", newline="") as fh:
            fh.write(gerar_csv(payload, nome_cargo))
        arquivos.append(caminho_csv)

    return arquivos
