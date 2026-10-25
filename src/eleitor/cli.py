from __future__ import annotations

import argparse
import json
import math
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any, Sequence

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import IntPrompt, Prompt
from rich.table import Table

from eleitor.config import (
    CARGO_NOMES,
    ELEICAO_FEDERAL,
    ELEICAO_ESTADUAL,
    SEGUNDO_TURNO,
    TTL_LIVE,
)
from eleitor.http import DEFAULT_MIN_INTERVAL, CachedClient, RateLimited, TTSError
from eleitor.models import Municipio, ResultadoCargo, ZonaSecoes
from eleitor.services.localidades import Localidades
from eleitor.services.votos import (
    resultado,
    resultados_zonas,
    secoes,
    votos_secao,
    votos_secoes_zona,
)

console = Console()

MAPA_POR_LOCAL_URL = (
    "https://angelojordy-svg.github.io/eleitor-2026/mapa/parauapebas/"
    "#cargo=presidente&a=22&b=13&modo=vencedor&base=offline"
)

CARGO_ALIASES = {
    "presidente": 1,
    "governador": 3,
    "senador": 5,
    "deputado federal": 6,
    "dep federal": 6,
    "dep. federal": 6,
    "deputado estadual": 7,
    "dep estadual": 7,
    "dep. estadual": 7,
    "deputado distrital": 8,
    "dep distrital": 8,
    "conselheiro distrital": 25,
    "conselheiro": 25,
}


def parse_cargo(valor: str) -> int:
    texto = valor.strip().lower()
    if texto.isdigit() and int(texto) in CARGO_NOMES:
        return int(texto)
    if texto in CARGO_ALIASES:
        return CARGO_ALIASES[texto]
    raise argparse.ArgumentTypeError(
        f"cargo inválido: {valor!r}. Use um de: {', '.join(sorted(CARGO_ALIASES))} ou código (1,3,5,6,7,8,25)."
    )


def eleicao_do_cargo(cargo: int, turno: int) -> int:
    if cargo in (1,):
        eleicao = ELEICAO_FEDERAL
    elif cargo == 25:
        eleicao = 6261
    else:
        eleicao = ELEICAO_ESTADUAL
    if turno == 2:
        if eleicao not in SEGUNDO_TURNO:
            raise TTSError(f"{CARGO_NOMES[cargo]} não tem 2º turno.")
        eleicao = SEGUNDO_TURNO[eleicao]
    return eleicao


def fmt_int(valor: int) -> str:
    return f"{valor:,}".replace(",", ".")


def pct(valor: float) -> str:
    return f"{valor:.2f}%".replace(".", ",")


def fmt_moeda(valor: float) -> str:
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def render_resultado(res: ResultadoCargo, titulo: str, limite: int = 25) -> None:
    t = res.totalizacao
    votos = res.votos
    cabecalho = (
        f"[bold]{titulo}[/bold]\n"
        f"{res.cargo_nome} • {res.abrangencia.upper()} • eleição {res.eleicao}\n"
        f"Seções totalizadas: [bold]{fmt_int(t.secoes_totalizadas)}[/bold]"
        f"/{fmt_int(t.secoes_total)} ({pct(t.percentual_secoes)}) • "
        f"gerado em {t.gerado_em or '—'}\n"
        f"Votos válidos: [bold]{fmt_int(votos.validos)}[/bold] • "
        f"Brancos: {fmt_int(votos.brancos)} • Nulos: {fmt_int(votos.nulos)} • "
        f"Anulados: {fmt_int(votos.anulados)}"
    )
    console.print(Panel(cabecalho, expand=False))

    table = Table(box=box.SIMPLE_HEAVY, header_style="bold")
    table.add_column("#", justify="right")
    table.add_column("Candidato")
    table.add_column("Partido")
    table.add_column("Nº", justify="center")
    table.add_column("Votos", justify="right")
    table.add_column("%", justify="right")
    table.add_column("Situação")

    for pos, cand in enumerate(res.candidatos[:limite], start=1):
        estilo = "bold green" if cand.eleito else None
        nome = cand.nome_urna or cand.nome
        table.add_row(
            str(pos),
            nome,
            cand.partido,
            cand.numero,
            fmt_int(cand.votos),
            pct(cand.percentual),
            "ELEITO" if cand.eleito else (cand.situacao or "—"),
            style=estilo,
        )
    console.print(table)
    eleitos = [c for c in res.candidatos if c.eleito]
    if eleitos:
        lista = ", ".join(f"{c.nome_urna or c.nome} ({c.partido})" for c in eleitos)
        console.print(Panel(f"[bold green]Eleitos:[/bold green] {lista}", expand=False))
    if len(res.candidatos) > limite:
        console.print(f"[dim]{len(res.candidatos) - limite} candidatos omitidos (use --todos).[/dim]")


def render_zonas(municipio: Municipio, cargo: int, itens: list[tuple[str, ResultadoCargo | None]]) -> None:
    table = Table(title=f"Zonas eleitorais — {municipio.nome}/{municipio.uf.upper()}", box=box.SIMPLE_HEAVY)
    table.add_column("Zona", justify="center")
    table.add_column("Seções", justify="right")
    table.add_column("Votos válidos", justify="right")
    table.add_column("Líder", justify="left")
    table.add_column("Votos líder", justify="right")

    for zona, res in itens:
        if res is None:
            table.add_row(zona, "—", "—", "[dim]sem arquivo[/dim]", "—")
            continue
        lider = res.candidatos[0] if res.candidatos else None
        t = res.totalizacao
        table.add_row(
            zona,
            f"{fmt_int(t.secoes_totalizadas)}/{fmt_int(t.secoes_total)}",
            fmt_int(res.votos.validos),
            (lider.nome_urna or lider.nome) if lider else "—",
            fmt_int(lider.votos) if lider else "—",
        )
    console.print(table)


def render_secoes(municipio: Municipio, zonas: list[ZonaSecoes], limite: int | None = None) -> None:
    table = Table(
        title=f"Seções eleitorais — {municipio.nome}/{municipio.uf.upper()}",
        box=box.SIMPLE_HEAVY,
    )
    table.add_column("Zona", justify="center")
    table.add_column("Seção", justify="center")
    table.add_column("Urnas", justify="right")
    table.add_column("Status", justify="left")
    table.add_column("Agregadas", justify="left")
    table.add_column("Aux gerado", justify="left")

    mostradas = 0
    for z in zonas:
        for sec in z.secoes:
            if limite is not None and mostradas >= limite:
                break
            agregadas = ", ".join(sec.agregadas)
            aux = f"{sec.data_aux or ''} {sec.hora_aux or ''}".strip() or "—"
            status = sec.status or ("aguardando" if not sec.data_aux else "sem retorno")
            table.add_row(
                z.zona,
                sec.numero,
                str(sec.urnas) if sec.urnas else "—",
                status,
                agregadas or "—",
                aux,
            )
            mostradas += 1
        if limite is not None and mostradas >= limite:
            break
    console.print(table)
    if limite is not None:
        total = sum(len(z.secoes) for z in zonas)
        if total > limite:
            console.print(f"[dim]{total - limite} seções omitidas (use --limite 0 para todas).[/dim]")


def escolher_municipio(loc: Localidades, termo: str, uf: str | None) -> Municipio | None:
    encontrados = loc.buscar(termo, uf)
    if not encontrados:
        console.print(f"[red]Nenhum município encontrado para {termo!r}.[/red]")
        return None
    if len(encontrados) == 1:
        return encontrados[0]

    table = Table(title="Municípios encontrados", box=box.SIMPLE)
    table.add_column("#", justify="right")
    table.add_column("UF", justify="center")
    table.add_column("Código", justify="center")
    table.add_column("Município")
    for i, m in enumerate(encontrados[:30], start=1):
        table.add_row(str(i), m.uf.upper(), m.codigo, m.nome)
    console.print(table)
    escolha = IntPrompt.ask("Escolha o número", default=1)
    if 1 <= escolha <= min(len(encontrados), 30):
        return encontrados[escolha - 1]
    return None


def exibir_municipio(client: CachedClient, loc: Localidades, municipio: Municipio, cargo: int, turno: int, todos: bool) -> None:
    eleicao = eleicao_do_cargo(cargo, turno)
    res = resultado(client, eleicao, cargo, uf=municipio.uf, municipio=municipio.codigo)
    render_resultado(res, f"{municipio.nome}/{municipio.uf.upper()} (somatório do município)", limite=1000 if todos else 25)
    itens = resultados_zonas(client, eleicao, cargo, municipio)
    render_zonas(municipio, cargo, itens)


def exibir_uf(client: CachedClient, uf: str, cargo: int, turno: int, todos: bool) -> None:
    eleicao = eleicao_do_cargo(cargo, turno)
    res = resultado(client, eleicao, cargo, uf=uf)
    render_resultado(res, f"Estado {uf.upper()}", limite=1000 if todos else 25)


def exibir_brasil(client: CachedClient, cargo: int, turno: int, todos: bool) -> None:
    if cargo != 1:
        raise TTSError("Somente Presidente tem abrangência nacional. Escolha uma UF para este cargo.")
    eleicao = eleicao_do_cargo(cargo, turno)
    res = resultado(client, eleicao, cargo)
    render_resultado(res, "Brasil", limite=1000 if todos else 25)


def render_governadores(itens: list[tuple[str, ResultadoCargo | None]]) -> None:
    table = Table(
        title="Governador — todos os estados (Brasil)",
        box=box.SIMPLE_HEAVY,
        header_style="bold",
    )
    table.add_column("UF", justify="center")
    table.add_column("Totalizado", justify="right")
    table.add_column("Líder", justify="left")
    table.add_column("Partido", justify="left")
    table.add_column("Votos", justify="right")
    table.add_column("%", justify="right")
    table.add_column("Eleito", justify="center")

    for uf, res in itens:
        if res is None or not res.candidatos:
            table.add_row(uf.upper(), "—", "[dim]sem dados[/dim]", "", "", "", "")
            continue
        lider = res.candidatos[0]
        t = res.totalizacao
        table.add_row(
            uf.upper(),
            f"{pct(t.percentual_secoes)}",
            lider.nome_urna or lider.nome,
            lider.partido,
            fmt_int(lider.votos),
            pct(lider.percentual),
            "[bold green]sim[/bold green]" if lider.eleito else "—",
        )
    console.print(table)


def render_financas(dados: dict, limite: int = 30) -> None:
    itens = dados.get("itens", [])
    cabecalho = (
        "[bold]Finanças de campanha — ranking[/bold]\n"
        f"{dados.get('total', 0)} candidato(s) com movimento de campanha • "
        f"arquivo do TSE gerado em {dados.get('gerado_em') or '—'} (parcial)"
    )
    console.print(Panel(cabecalho, expand=False))

    table = Table(box=box.SIMPLE_HEAVY, header_style="bold")
    table.add_column("#", justify="right")
    table.add_column("Candidato")
    table.add_column("Partido")
    table.add_column("UF", justify="center")
    table.add_column("Cargo")
    table.add_column("Receita", justify="right")
    table.add_column("Fundos", justify="right")
    table.add_column("Gasto", justify="right")
    table.add_column("Patrimônio", justify="right")
    table.add_column("Situação")

    for pos, item in enumerate(itens[:limite], start=1):
        estilo = "bold green" if (item.get("sit") or "").upper().startswith("ELEITO") else None
        table.add_row(
            str(pos),
            item.get("nome", ""),
            item.get("partido", ""),
            item.get("uf", ""),
            CARGO_NOMES.get(item.get("cargo"), str(item.get("cargo", ""))),
            fmt_moeda(item.get("receita", 0.0)),
            fmt_moeda(item.get("fundos", 0.0)),
            fmt_moeda(item.get("gasto", 0.0)),
            fmt_moeda(item.get("bens", 0.0)),
            item.get("sit") or "—",
            style=estilo,
        )
    console.print(table)
    if len(itens) > limite:
        console.print(f"[dim]{len(itens) - limite} candidato(s) omitido(s) (use --limite 0 para todos).[/dim]")


def exibir_governadores(client: CachedClient, turno: int) -> None:
    from eleitor.config import UF_SIGLAS
    from eleitor.sources.resultados import parse_resultado, url_resultado

    eleicao = eleicao_do_cargo(3, turno)
    ufs = [u for u in UF_SIGLAS if u != "ZZ"]
    urls = [url_resultado(eleicao, 3, uf=uf) for uf in ufs]
    corpos = client.get_urls(urls, ttl=TTL_LIVE, allow_404=True)
    itens: list[tuple[str, ResultadoCargo | None]] = []
    for uf, url in zip(ufs, urls):
        body = corpos.get(url)
        itens.append((uf, parse_resultado(body) if body else None))
    render_governadores(itens)


def loop_atualizacao(render, intervalo: int) -> None:
    try:
        while True:
            console.clear()
            render()
            console.print(f"\n[dim]Atualizando a cada {intervalo}s — Ctrl+C para sair.[/dim]")
            time.sleep(intervalo)
    except KeyboardInterrupt:
        console.print("\n[dim]Encerrado.[/dim]")


def render_votos_secao(
    municipio: Municipio,
    zona: str,
    secao: str,
    cargo: int,
    dados: dict,
    nomes: dict[str, str],
    partidos: dict[str, str],
) -> None:
    info = dados.get("cargos", {}).get(cargo)
    cabecalho = (
        f"[bold]Urna — {municipio.nome}/{municipio.uf.upper()} • "
        f"zona {zona} • seção {secao}[/bold]\n"
        f"{CARGO_NOMES.get(cargo, cargo)} • BU {dados.get('versao', '?')} • "
        f"status: {dados.get('status') or '—'}"
    )
    if not info:
        console.print(Panel(cabecalho + "\n[dim]Este cargo não aparece no boletim desta urna.[/dim]", expand=False))
        return
    cabecalho += (
        f"\nAptos: {fmt_int(info['aptos'])} • "
        f"Comparecimento: {fmt_int(info['comparecimento'])}"
    )
    console.print(Panel(cabecalho, expand=False))

    linhas = []
    brancos = nulos = legenda = 0
    for voto in info["votos"]:
        tipo = voto["tipo"]
        if tipo == "nominal":
            codigo = str(voto.get("codigo", ""))
            linhas.append(
                (
                    nomes.get(codigo, f"candidato {codigo}"),
                    partidos.get(codigo, str(voto.get("partido", ""))),
                    codigo,
                    voto["votos"],
                )
            )
        elif tipo == "branco":
            brancos += voto["votos"]
        elif tipo == "nulo":
            nulos += voto["votos"]
        elif tipo == "legenda":
            legenda += voto["votos"]
    linhas.sort(key=lambda x: x[3], reverse=True)

    table = Table(box=box.SIMPLE_HEAVY, header_style="bold")
    table.add_column("Candidato")
    table.add_column("Partido")
    table.add_column("Nº", justify="center")
    table.add_column("Votos", justify="right")
    for nome, partido, numero, votos in linhas:
        table.add_row(nome, partido, numero, fmt_int(votos))
    if legenda:
        table.add_row("[dim]Legenda[/dim]", "", "", fmt_int(legenda))
    table.add_row("[dim]Brancos[/dim]", "", "", fmt_int(brancos))
    table.add_row("[dim]Nulos[/dim]", "", "", fmt_int(nulos))
    console.print(table)


def exibir_votos_secao(
    client: CachedClient,
    loc: Localidades,
    municipio: Municipio,
    cargo: int,
    turno: int,
    zona: str,
    secao: str,
) -> None:
    dados = votos_secao(client, municipio.uf, municipio.codigo, zona, secao)
    if not dados:
        console.print("[yellow]Ainda não há boletim de urna (BU) disponível para esta seção.[/yellow]")
        return
    eleicao = eleicao_do_cargo(cargo, turno)
    res = resultado(client, eleicao, cargo, uf=municipio.uf, municipio=municipio.codigo)
    nomes = {c.numero: (c.nome_urna or c.nome) for c in res.candidatos}
    partidos = {c.numero: c.partido for c in res.candidatos}
    render_votos_secao(municipio, zona, secao, cargo, dados, nomes, partidos)


def render_votos_por_secao(
    municipio: Municipio,
    zona: str,
    cargo: int,
    votos_por_secao: dict[str, dict],
    nomes: dict[str, str],
) -> None:
    total_secoes = len(votos_por_secao)
    cabecalho = (
        f"[bold]Votos por seção — {municipio.nome}/{municipio.uf.upper()} • "
        f"zona {zona} • {CARGO_NOMES.get(cargo, cargo)}[/bold]\n"
        f"{total_secoes} urnas com BU disponível"
    )
    console.print(Panel(cabecalho, expand=False))
    if not votos_por_secao:
        console.print("[yellow]Nenhum boletim de urna disponível nesta zona ainda.[/yellow]")
        return

    table = Table(box=box.SIMPLE_HEAVY, header_style="bold")
    table.add_column("Seção", justify="center")
    table.add_column("Aptos", justify="right")
    table.add_column("Comparec.", justify="right")
    numeros = list(nomes)
    for numero in numeros:
        table.add_column(f"{nomes[numero]}", justify="right")
    table.add_column("Brancos", justify="right")
    table.add_column("Nulos", justify="right")
    for secao in sorted(votos_por_secao):
        dados = votos_por_secao[secao]
        info = dados.get("cargos", {}).get(cargo)
        if not info:
            continue
        votos = {}
        brancos = nulos = 0
        for voto in info["votos"]:
            if voto["tipo"] == "nominal":
                codigo = str(voto.get("codigo", ""))
                votos[codigo] = votos.get(codigo, 0) + voto["votos"]
            elif voto["tipo"] == "branco":
                brancos += voto["votos"]
            elif voto["tipo"] == "nulo":
                nulos += voto["votos"]
        table.add_row(
            secao,
            fmt_int(info["aptos"]),
            fmt_int(info["comparecimento"]),
            *[fmt_int(votos.get(numero, 0)) for numero in numeros],
            fmt_int(brancos),
            fmt_int(nulos),
        )
    console.print(table)


def exibir_votos_por_secao(
    client: CachedClient,
    municipio: Municipio,
    cargo: int,
    turno: int,
    zona: str,
    top: int = 10,
) -> None:
    votos_por_secao = votos_secoes_zona(client, municipio.uf, municipio.codigo, zona)
    eleicao = eleicao_do_cargo(cargo, turno)
    res = resultado(client, eleicao, cargo, uf=municipio.uf, municipio=municipio.codigo, zona=zona)
    principais = [c for c in res.candidatos[:top] if c.votos > 0] or res.candidatos[:top]
    nomes = {c.numero: (c.nome_urna or c.nome) for c in principais}
    if len(res.candidatos) > len(nomes):
        console.print(f"[dim]Mostrando os {len(nomes)} primeiros colocados na zona (de {len(res.candidatos)}).[/dim]")
    render_votos_por_secao(municipio, zona, cargo, votos_por_secao, nomes)


def menu(client: CachedClient) -> None:
    loc = Localidades(client)
    while True:
        console.print(
            Panel(
                "[bold]Eleitor 2026 — TSE[/bold]\n"
                "1. Resultados ao vivo (Brasil / UF / Município, com zonas)\n"
                "2. Todos os governadores do Brasil\n"
                "3. Seções e urnas de um município\n"
                "4. Votos de uma seção (boletim de urna)\n"
                "5. Votos por seção de uma zona inteira\n"
                "6. Gerar HTML offline (snapshot estilo TSE)\n"
                "7. Ranking de gastos de campanha (prestação de contas)\n"
                "8. Abrir mapa por local de votação (Parauapebas) no navegador\n"
                "0. Sair",
                title="Menu",
                expand=False,
            )
        )
        opcao = Prompt.ask("Opção", choices=["1", "2", "3", "4", "5", "6", "7", "8", "0"], default="1")

        if opcao == "0":
            return

        if opcao == "1":
            cargo_nome = Prompt.ask(
                "Cargo",
                choices=["presidente", "governador", "senador", "deputado federal", "deputado estadual", "deputado distrital"],
                default="presidente",
            )
            cargo = parse_cargo(cargo_nome)
            abrangencia = Prompt.ask("Abrangência", choices=["brasil", "uf", "municipio"], default="municipio")
            turno = IntPrompt.ask("Turno", choices=["1", "2"], default=1)
            try:
                if abrangencia == "brasil":
                    exibir_brasil(client, cargo, turno, todos=False)
                elif abrangencia == "uf":
                    uf = Prompt.ask("UF (ex: PA)").strip().lower()
                    exibir_uf(client, uf, cargo, turno, todos=False)
                else:
                    termo = Prompt.ask("Nome do município (ex: Parauapebas)")
                    uf = Prompt.ask("UF (opcional, Enter para buscar em todo o Brasil)", default="").strip().lower() or None
                    municipio = escolher_municipio(loc, termo, uf)
                    if municipio:
                        exibir_municipio(client, loc, municipio, cargo, turno, todos=False)
            except (TTSError, RateLimited) as exc:
                console.print(f"[red]{exc}[/red]")
            Prompt.ask("[dim]Enter para voltar ao menu[/dim]", default="")

        elif opcao == "2":
            turno = IntPrompt.ask("Turno", choices=["1", "2"], default=1)
            try:
                exibir_governadores(client, turno)
            except (TTSError, RateLimited) as exc:
                console.print(f"[red]{exc}[/red]")
            Prompt.ask("[dim]Enter para voltar ao menu[/dim]", default="")

        elif opcao == "3":
            termo = Prompt.ask("Nome do município (ex: Parauapebas)")
            uf = Prompt.ask("UF (opcional)", default="").strip().lower() or None
            municipio = escolher_municipio(loc, termo, uf)
            if municipio:
                zona = Prompt.ask("Zona (opcional, Enter para todas)", default="").strip() or None
                limite_texto = Prompt.ask("Limite de seções exibidas (0 = todas)", default="200").strip()
                limite = None if limite_texto == "0" else int(limite_texto or "200")
                try:
                    zonas = secoes(client, municipio.uf, municipio.codigo, zona=zona)
                    render_secoes(municipio, zonas, limite=limite)
                except (TTSError, RateLimited) as exc:
                    console.print(f"[red]{exc}[/red]")
            Prompt.ask("[dim]Enter para voltar ao menu[/dim]", default="")

        elif opcao == "4":
            termo = Prompt.ask("Nome do município (ex: Parauapebas)")
            uf = Prompt.ask("UF (opcional)", default="").strip().lower() or None
            municipio = escolher_municipio(loc, termo, uf)
            if municipio:
                zona = Prompt.ask("Zona").strip()
                secao = Prompt.ask("Seção").strip()
                cargo_nome = Prompt.ask(
                    "Cargo",
                    choices=["presidente", "governador", "senador", "deputado federal", "deputado estadual", "deputado distrital"],
                    default="presidente",
                )
                cargo = parse_cargo(cargo_nome)
                turno = IntPrompt.ask("Turno", choices=["1", "2"], default=1)
                try:
                    exibir_votos_secao(client, loc, municipio, cargo, turno, zona, secao)
                except (TTSError, RateLimited) as exc:
                    console.print(f"[red]{exc}[/red]")
            Prompt.ask("[dim]Enter para voltar ao menu[/dim]", default="")

        elif opcao == "5":
            termo = Prompt.ask("Nome do município (ex: Parauapebas)")
            uf = Prompt.ask("UF (opcional)", default="").strip().lower() or None
            municipio = escolher_municipio(loc, termo, uf)
            if municipio:
                zona = Prompt.ask("Zona").strip()
                cargo_nome = Prompt.ask(
                    "Cargo",
                    choices=["presidente", "governador", "senador", "deputado federal", "deputado estadual", "deputado distrital"],
                    default="presidente",
                )
                cargo = parse_cargo(cargo_nome)
                turno = IntPrompt.ask("Turno", choices=["1", "2"], default=1)
                try:
                    with console.status("Baixando boletins de urna da zona..."):
                        exibir_votos_por_secao(client, municipio, cargo, turno, zona)
                except (TTSError, RateLimited) as exc:
                    console.print(f"[red]{exc}[/red]")
            Prompt.ask("[dim]Enter para voltar ao menu[/dim]", default="")

        elif opcao == "6":
            texto = Prompt.ask(
                "Municípios para incluir (ex: Ananindeua/PA, Parauapebas/PA; Enter = só Brasil/Estados)",
                default="",
            ).strip()
            municipios = [p.strip() for p in texto.split(",") if p.strip()]
            saida = Prompt.ask("Arquivo de saída", default="resultado-2026.html").strip()
            fotos = Prompt.ask("Incluir fotos? (s/n)", choices=["s", "n"], default="s") == "s"
            secoes_html = Prompt.ask("Incluir votos por seção? (s/n)", choices=["s", "n"], default="s") == "s"
            args_html = argparse.Namespace(
                municipio=municipios,
                uf=None,
                out=saida,
                sem_fotos=not fotos,
                sem_secoes=not secoes_html,
                sem_mapa=False,
                mapa_municipios="br",
                refazer_mapa=False,
                sem_financas=False,
                refazer_financas=False,
            )
            try:
                cmd_html(client, args_html)
            except (TTSError, RateLimited) as exc:
                console.print(f"[red]{exc}[/red]")
            Prompt.ask("[dim]Enter para voltar ao menu[/dim]", default="")

        elif opcao == "7":
            try:
                cmd_financas(
                    client,
                    argparse.Namespace(cargo=None, uf=None, ordenar="gasto", limite=30, out=None, refazer=False),
                )
            except (TTSError, RateLimited) as exc:
                console.print(f"[red]{exc}[/red]")
            Prompt.ask("[dim]Enter para voltar ao menu[/dim]", default="")

        elif opcao == "8":
            webbrowser.open_new_tab(MAPA_POR_LOCAL_URL)
            console.print(f"[green]Mapa aberto no navegador:[/green] {MAPA_POR_LOCAL_URL}")
            Prompt.ask("[dim]Enter para voltar ao menu[/dim]", default="")


def cmd_buscar(client: CachedClient, args: argparse.Namespace) -> int:
    loc = Localidades(client)
    municipio = escolher_municipio(loc, args.municipio, args.uf)
    if municipio is None:
        return 1
    if args.zona:
        eleicao = eleicao_do_cargo(args.cargo, args.turno)
        res = resultado(client, eleicao, args.cargo, uf=municipio.uf, municipio=municipio.codigo, zona=args.zona)
        render_resultado(res, f"Zona {args.zona} — {municipio.nome}/{municipio.uf.upper()}", limite=1000 if args.todos else 25)
        return 0
    if args.watch:
        loop_atualizacao(lambda: exibir_municipio(client, loc, municipio, args.cargo, args.turno, args.todos), args.watch)
    else:
        exibir_municipio(client, loc, municipio, args.cargo, args.turno, args.todos)
    return 0


def cmd_uf(client: CachedClient, args: argparse.Namespace) -> int:
    if args.watch:
        loop_atualizacao(lambda: exibir_uf(client, args.uf, args.cargo, args.turno, args.todos), args.watch)
    else:
        exibir_uf(client, args.uf, args.cargo, args.turno, args.todos)
    return 0


def cmd_br(client: CachedClient, args: argparse.Namespace) -> int:
    if args.watch:
        loop_atualizacao(lambda: exibir_brasil(client, args.cargo, args.turno, args.todos), args.watch)
    else:
        exibir_brasil(client, args.cargo, args.turno, args.todos)
    return 0


def cmd_governadores(client: CachedClient, args: argparse.Namespace) -> int:
    if args.watch:
        loop_atualizacao(lambda: exibir_governadores(client, args.turno), args.watch)
    else:
        exibir_governadores(client, args.turno)
    return 0


def cmd_secoes(client: CachedClient, args: argparse.Namespace) -> int:
    loc = Localidades(client)
    municipio = escolher_municipio(loc, args.municipio, args.uf)
    if municipio is None:
        return 1
    zonas = secoes(client, municipio.uf, municipio.codigo, zona=args.zona)
    limite = None if args.limite == 0 else args.limite
    render_secoes(municipio, zonas, limite=limite)
    return 0


def cmd_secao(client: CachedClient, args: argparse.Namespace) -> int:
    loc = Localidades(client)
    municipio = escolher_municipio(loc, args.municipio, args.uf)
    if municipio is None:
        return 1
    exibir_votos_secao(client, loc, municipio, args.cargo, args.turno, args.zona, args.numero_secao)
    return 0


def cmd_votos(client: CachedClient, args: argparse.Namespace) -> int:
    loc = Localidades(client)
    municipio = escolher_municipio(loc, args.municipio, args.uf)
    if municipio is None:
        return 1
    exibir_votos_por_secao(client, municipio, args.cargo, args.turno, args.zona)
    return 0


def cmd_municipios(client: CachedClient, args: argparse.Namespace) -> int:
    loc = Localidades(client)
    uf = args.uf.lower()
    municipios = [m for m in loc.municipios if m.uf == uf]
    table = Table(title=f"Municípios de {uf.upper()} ({len(municipios)})", box=box.SIMPLE)
    table.add_column("Código", justify="center")
    table.add_column("Município")
    table.add_column("Zonas", justify="center")
    for m in sorted(municipios, key=lambda x: x.nome):
        table.add_row(m.codigo, m.nome, ", ".join(m.zonas))
    console.print(table)
    return 0


def _ufs_do_mapa(valor: str | None) -> list[str] | None:
    """'br' = Brasil inteiro, 'none' = desligado, 'pa,mg' = só esses."""

    from eleitor.config import UF_SIGLAS

    alvo = (valor or "br").strip().lower()
    if alvo in ("none", "nenhum", "off", "nao", "não", ""):
        return None
    if alvo in ("br", "brasil", "tudo", "all", "*"):
        return [u.lower() for u in UF_SIGLAS if u != "ZZ"]
    pedidas = [p.strip().lower() for p in alvo.split(",") if p.strip()]
    validas = {u.lower() for u in UF_SIGLAS if u != "ZZ"}
    invalidas = [u for u in pedidas if u not in validas]
    if invalidas:
        raise argparse.ArgumentTypeError(f"UF inválida em --mapa-municipios: {', '.join(invalidas)}")
    return pedidas


def cmd_mapa(client: CachedClient, args: argparse.Namespace) -> int:
    """Calcula (e guarda em cache) o líder por município para o mapa."""

    from eleitor.config import CARGO_NOMES, SEGUNDO_TURNO
    from eleitor.services.localidades import Localidades
    from eleitor.services.mapa import bake_resultado_municipios

    loc = Localidades(client)
    ufs = _ufs_do_mapa(args.mapa_municipios) or []
    if not ufs:
        console.print("[yellow]Nenhuma UF selecionada.[/yellow]")
        return 1

    combos: list[tuple[str, str]] = []
    for cargo in args.cargo or [3, 1]:
        for turno in args.turno or [1, 2]:
            eleicao = 6257 if cargo == 1 else 6259
            if turno == 2:
                if eleicao not in SEGUNDO_TURNO:
                    continue
                eleicao = SEGUNDO_TURNO[eleicao]
            combos.append((str(cargo), str(turno)))

    for cargo, turno in combos:
        with console.status(
            f"Baixando {CARGO_NOMES.get(int(cargo), cargo)} — {turno}º turno ({len(ufs)} UF(s))..."
        ):
            resultado = bake_resultado_municipios(
                client,
                loc,
                cargo,
                turno,
                ufs,
                progresso=lambda msg: console.print(f"[dim]{msg}[/dim]"),
                refazer=args.refazer,
            )
        com_dados = sum(len(v) for v in resultado.values())
        console.print(
            f"[green]{CARGO_NOMES.get(int(cargo), cargo)} — {turno}º turno:[/green] "
            f"{com_dados} município(s) com votos em {len(resultado)} UF(s)."
        )
    return 0


def cmd_financas(client: CachedClient, args: argparse.Namespace) -> int:
    """Ranking de gastos/arrecadação de campanha (prestação de contas do TSE)."""

    from eleitor.services.financas import bake_financas

    dados = bake_financas(
        forcar=args.refazer,
        progresso=lambda msg: console.print(f"[dim]{msg}[/dim]"),
    )
    itens = list(dados.get("itens", []))
    if args.cargo is not None:
        itens = [item for item in itens if item.get("cargo") == args.cargo]
    if args.uf:
        itens = [item for item in itens if item.get("uf") == args.uf.upper()]
    campo = args.ordenar
    itens.sort(key=lambda item: item.get(campo, 0) or 0, reverse=True)

    if args.out:
        destino = Path(args.out)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(
                {"ano": dados.get("ano"), "gerado_em": dados.get("gerado_em"), "itens": itens},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        console.print(f"[green]Ranking gravado:[/green] {destino} ({len(itens)} candidato(s))")

    limite = len(itens) if args.limite == 0 else args.limite
    render_financas({"total": len(itens), "gerado_em": dados.get("gerado_em"), "itens": itens}, limite=limite)
    return 0


def cmd_html(client: CachedClient, args: argparse.Namespace) -> int:
    from eleitor.render.html import render_html
    from eleitor.services.snapshot import coletar_snapshot

    loc = Localidades(client)
    municipios: list[Municipio] = []
    for referencia in args.municipio or []:
        nome, _, uf_ref = referencia.partition("/")
        uf = uf_ref.strip().lower() or (args.uf or "").strip().lower() or None
        municipio = escolher_municipio(loc, nome.strip(), uf)
        if municipio is None:
            return 1
        municipios.append(municipio)

    try:
        ufs_mapa = _ufs_do_mapa(args.mapa_municipios)
    except argparse.ArgumentTypeError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    def progresso(msg: str) -> None:
        console.print(f"[dim]{msg}[/dim]")

    with console.status("Coletando dados para o snapshot..."):
        dados = coletar_snapshot(
            client,
            loc,
            municipios,
            com_fotos=not args.sem_fotos,
            com_secoes=not args.sem_secoes,
            com_mapa=not args.sem_mapa,
            com_mapa_municipios=ufs_mapa,
            refazer_mapa=args.refazer_mapa,
            com_mundo=not args.sem_mundo,
            refazer_mundo=args.refazer_mundo,
            com_mundo_bu=not args.sem_mundo_bu,
            refazer_mundo_bu=args.refazer_mundo_bu,
            com_financas=not args.sem_financas,
            refazer_financas=args.refazer_financas,
            progresso=progresso,
        )
    html = render_html(dados)
    destino = Path(args.out)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(html, encoding="utf-8")
    tamanho_mb = destino.stat().st_size / (1024 * 1024)
    console.print(f"[green]Artefato gerado:[/green] {destino} ({tamanho_mb:.1f} MB)")
    console.print(f"Municípios incluídos: {', '.join(m.nome + '/' + m.uf.upper() for m in municipios) or 'nenhum (só Brasil/Estados)'}")
    return 0


def cmd_conferir_mundo(client: CachedClient, args: argparse.Namespace) -> int:
    """Compara a prévia dos BUs do exterior com a totalização oficial."""

    from eleitor.paises import PAISES
    from eleitor.services.mundo import bake_mundo
    from eleitor.services.mundo_bu import bake_mundo_bu, comparar_mundo

    def progresso(msg: str) -> None:
        console.print(f"[dim]{msg}[/dim]")

    with console.status("Lendo os BUs do exterior (prévia do 2º turno)..."):
        bu = bake_mundo_bu(client, progresso=progresso, refazer=args.refazer)
    if not bu:
        console.print("[yellow]Sem BUs disponíveis para a prévia do 2º turno.[/yellow]")
        return 1

    meta = bu.get("meta", {})
    console.print(
        f"[bold]Prévia BU:[/bold] {meta.get('secoes_lidas', 0)} de "
        f"{meta.get('secoes_eletronicas', 0)} urnas eletrônicas "
        f"({meta.get('secoes_total', 0)} seções no total) • config 3221 de "
        f"{meta.get('config_gerado', '—')} • atualizado em {meta.get('gerado_em', '—')}"
    )

    with console.status("Buscando a totalização oficial do 2º turno..."):
        oficial = bake_mundo(client, Localidades(client), "2", progresso=progresso, refazer=args.refazer)
    cmp = comparar_mundo(bu, oficial)

    if not cmp["oficial_disponivel"]:
        console.print(
            "[yellow]O TSE ainda não iniciou a totalização oficial do exterior "
            "(prevista para após as 17h de Brasília).[/yellow]"
        )
        console.print("[dim]Mostrando apenas a prévia dos BUs já recebidos.[/dim]")

    linhas = []
    for item in cmp["paises"]:
        iso = item["iso"]
        topo_bu = item["bu"] or []
        topo_of = item["oficial"]
        cob = item["cobertura"] or {}
        cobertura = f"{cob.get('lidas', 0)}/{cob.get('secoes', 0)}"
        bu_lider = f"{topo_bu[0][3]} ({topo_bu[0][0]}) {fmt_int(topo_bu[0][2])}" if topo_bu else "—"
        if topo_of:
            of_lider = f"{topo_of[0][3]} ({topo_of[0][0]}) {fmt_int(topo_of[0][2])}"
            dif = item["dif_lider"]
            confere = "sim" if dif == 0 else ("líder difere" if topo_bu[0][0] != topo_of[0][0] else "dif. de votos")
        else:
            of_lider = "—"
            dif = None
            confere = "—"
        linhas.append((iso, cob, cobertura, bu_lider, of_lider, dif, confere))

    linhas.sort(key=lambda l: (l[1] or {}).get("lidas", 0), reverse=True)
    tabela = Table(
        title="Prévia BU x oficial — exterior (2º turno)",
        box=box.SIMPLE_HEAVY,
    )
    tabela.add_column("País")
    tabela.add_column("Cobertura BU", justify="right")
    tabela.add_column("BU (líder)", max_width=38)
    tabela.add_column("Oficial (líder)", max_width=38)
    tabela.add_column("Dif. líder", justify="right")
    tabela.add_column("Conferência")
    for iso, _, cobertura, bu_lider, of_lider, dif, confere in linhas:
        tabela.add_row(
            PAISES.get(iso, {}).get("nome", iso),
            cobertura,
            bu_lider,
            of_lider,
            fmt_int(dif) if dif is not None else "—",
            confere,
        )
    console.print(tabela)

    total = cmp["total"] or {}
    if cmp["oficial_disponivel"]:
        bu_total = total.get("bu") or []
        of_total = total.get("oficial") or []
        console.print(
            "[bold]Total exterior — BU:[/bold] "
            f"{fmt_int(bu_total[0][2]) if bu_total else 0} votos do líder • "
            "[bold]oficial:[/bold] "
            f"{fmt_int(of_total[0][2]) if of_total else 0} votos do líder"
        )
    return 0


def cmd_mapa_urnas(client: CachedClient, args: argparse.Namespace) -> int:
    """Gera o mapa por local (HTML + fundo offline + KML/CSV do Google)."""

    from eleitor.render.html import render_mapa_urnas
    from eleitor.services.exportar_google import ExportError, exportar_google
    from eleitor.services.fundo_offline import FundoOfflineError, gerar_fundo
    from eleitor.services.mapa_urnas import (
        conferir_planilha,
        construir_payload,
        nome_arquivo,
    )
    from eleitor.sources.planilha import PlanilhaError, ler_planilha

    caminho = Path(args.xlsx)
    try:
        with console.status("Lendo a planilha de BUs..."):
            planilha = ler_planilha(caminho)
    except PlanilhaError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    avisos = conferir_planilha(planilha)
    for aviso in avisos:
        console.print(f"[yellow]Atenção:[/yellow] {aviso}")

    with console.status("Agregando votos por local..."):
        payload = construir_payload(planilha)

    fundo = None
    if not getattr(args, "sem_fundo_offline", False):
        try:
            with console.status("Gerando fundo offline..."):
                fundo = gerar_fundo(
                    payload,
                    zoom_baixo=args.zoom_fundo,
                    zoom_detalhe=args.zoom_detalhe,
                    raio_detalhe_km=args.raio_detalhe,
                    qualidade=args.qualidade,
                    refazer=args.refazer_fundo,
                    progresso=lambda msg: console.print(f"[dim]{msg}[/dim]"),
                )
        except FundoOfflineError as exc:
            console.print(f"[yellow]Fundo offline indisponível:[/yellow] {exc}")
        except Exception as exc:  # rede/Pillow: não impede o HTML
            console.print(f"[yellow]Fundo offline indisponível:[/yellow] {exc}")
    if fundo:
        detalhe = (
            f" + detalhe {fundo.alto.largura}x{fundo.alto.altura} (z{fundo.alto.zoom})"
            if fundo.alto
            else ""
        )
        console.print(
            f"[green]Fundo offline:[/green] "
            f"{fundo.baixo.largura}x{fundo.baixo.altura} (z{fundo.baixo.zoom})"
            f"{detalhe} · {fundo.attr}"
        )
    else:
        console.print("[yellow]Seguindo sem fundo offline; padrão Ruas (Esri).[/yellow]")

    html = render_mapa_urnas(payload, fundo.para_dict() if fundo else None)
    destino = Path(args.out) if args.out else caminho.parent / nome_arquivo(payload["meta"])
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(html, encoding="utf-8")

    google_dir = (
        Path(args.google_dir) if args.google_dir else destino.parent / "google"
    )
    try:
        arquivos = exportar_google(payload, google_dir)
    except ExportError as exc:
        console.print(f"[yellow]Google não gerado:[/yellow] {exc}")
    else:
        console.print(
            f"[green]Google:[/green] {len(arquivos)} arquivo(s) em {google_dir}"
        )

    tamanho_mb = destino.stat().st_size / (1024 * 1024)
    meta = payload["meta"]
    console.print(f"[green]Mapa eleitoral gerado:[/green] {destino} ({tamanho_mb:.1f} MB)")
    console.print(
        f"{meta.get('municipio') or 'município'} — {meta['total_locais']} local(is), "
        f"{meta['total_urnas']} urna(s), {meta['total_cargos']} cargo(s), "
        f"{meta['total_aptos']:,} aptos.".replace(",", ".")
    )
    if not avisos:
        console.print("[dim]Conferência de totais: OK.[/dim]")
    return 0


def _coletar_pares_focados(
    args: argparse.Namespace, caminho_planilha: Path
) -> list[tuple[tuple[str, str], tuple[str, str]]] | None:
    """Lê --pares e --pares-arquivo; cria o template quando necessário."""

    from eleitor.services.correlacao import (
        ler_pares_arquivo,
        parse_pares_texto,
        texto_template_pares,
    )

    pares: list[tuple[tuple[str, str], tuple[str, str]]] = []
    try:
        for texto in args.pares or []:
            pares.extend(parse_pares_texto(texto))
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return None

    arquivo = (
        Path(args.pares_arquivo)
        if args.pares_arquivo
        else caminho_planilha.parent / "pares.txt"
    )
    if args.pares_arquivo:
        if not arquivo.exists():
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(texto_template_pares(), encoding="utf-8")
            console.print(f"[yellow]Template criado:[/yellow] {arquivo}")
            console.print("Edite a lista de pares e rode o comando de novo.")
            return None
        try:
            pares.extend(ler_pares_arquivo(arquivo))
        except (OSError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            return None
    elif not pares:
        if not arquivo.exists():
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(texto_template_pares(), encoding="utf-8")
            console.print(f"[yellow]Nenhum par informado. Template criado:[/yellow] {arquivo}")
            console.print(
                "Edite o arquivo (ou use --pares \"Cargo:numero; Cargo:numero\") "
                "e rode de novo."
            )
            return None
        try:
            pares.extend(ler_pares_arquivo(arquivo))
        except (OSError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            return None

    if not pares:
        console.print(
            "[yellow]A lista de pares está vazia. Edite o arquivo ou use --pares.[/yellow]"
        )
        return None
    return pares


def cmd_correlacao_focada(
    dados: Any, caminho_planilha: Path, args: argparse.Namespace
) -> int:
    """Relatório focado de pares (bootstrap, permutação, benchmark e limites)."""

    from eleitor.render.focado import render_focado
    from eleitor.services.correlacao import (
        analisar_correlacoes,
        analisar_pares_focados,
        escrever_focado_benchmark_csv,
        escrever_focado_csv,
        escrever_focado_locais_csv,
        montar_payload_focado,
        nome_base_focado,
        resolver_pares,
        selecionar,
    )

    pares_texto = _coletar_pares_focados(args, caminho_planilha)
    if pares_texto is None:
        return 1

    try:
        pares = resolver_pares(dados, pares_texto)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    indices = selecionar(
        dados, min_votos=args.min_votos, min_cobertura=args.min_cobertura
    )
    for i, j in pares:
        if i not in indices:
            indices.append(i)
        if j not in indices:
            indices.append(j)
    indices = sorted(set(indices))
    if len(indices) < 2:
        console.print("[red]Poucos candidatos com votos para analisar.[/red]")
        return 1

    with console.status("Calculando correlações de referência..."):
        resultado = analisar_correlacoes(
            dados,
            indices,
            metodo_bloco=args.bloco,
            bootstrap_top=0,
            bootstrap_repeticoes=0,
            seed=args.seed,
        )

    with console.status("Calculando métricas focadas (bootstrap/permutação)..."):
        focados = analisar_pares_focados(
            dados,
            pares,
            resultado,
            benchmark_tipo=args.benchmark,
            bootstrap_repeticoes=args.bootstrap,
            permutacoes=args.permutacoes,
            goodman_repeticoes=args.bootstrap,
            loo=not args.sem_loo,
            seed=args.seed,
        )

    base = nome_base_focado(dados.meta)
    if args.out and Path(args.out).suffix.lower() == ".csv":
        csv_principal = Path(args.out)
        destino = csv_principal.parent
        csv_locais = destino / f"{csv_principal.stem}_locais.csv"
        csv_benchmark = destino / f"{csv_principal.stem}_benchmark.csv"
    else:
        destino = Path(args.out) if args.out else caminho_planilha.parent
        destino.mkdir(parents=True, exist_ok=True)
        csv_principal = destino / f"{base}.csv"
        csv_locais = destino / f"{base}_locais.csv"
        csv_benchmark = destino / f"{base}_benchmark.csv"

    escritos = [
        escrever_focado_csv(focados, csv_principal),
        escrever_focado_locais_csv(focados, csv_locais),
        escrever_focado_benchmark_csv(focados, csv_benchmark),
    ]

    if args.html:
        alvo = Path(args.html)
        if not alvo.suffix:
            alvo = alvo / f"{base}.html"
        alvo.parent.mkdir(parents=True, exist_ok=True)
        html = render_focado(montar_payload_focado(dados, focados))
        alvo.write_text(html, encoding="utf-8")
        escritos.append(alvo)

    meta = dados.meta
    console.print(
        f"[bold]{meta.get('municipio') or 'município'}[/bold] — "
        f"{dados.n_urnas} urna(s), {dados.n_locais} local(is), "
        f"{len(focados)} par(es) focado(s)."
    )
    console.print(
        "[dim]p permutação = teste focado within-local; q = FDR. "
        "Use p se o par foi pré-especificado; use q se foi escolhido após "
        "varrer muitos pares. Limites de co-votação são exatos; Goodman é "
        "sensibilidade, não verdade.[/dim]"
    )

    for posicao, par in enumerate(focados, start=1):
        console.print(
            f"\n[bold]{posicao}. {par.a.rotulo} × {par.b.rotulo}[/bold]"
        )
        bloco_txt = (
            f"{par.r_bloco:+.3f}" if math.isfinite(par.r_bloco) else "—"
        )
        ic_txt = (
            f"[{par.ic_boot_inf:+.2f}; {par.ic_boot_sup:+.2f}]"
            if par.ic_boot_inf is not None and par.ic_boot_sup is not None
            else "—"
        )
        p_txt = f"{par.p_perm:.2g}" if math.isfinite(par.p_perm) else "—"
        q_focado_txt = (
            f"{par.q_focado:.2g}" if math.isfinite(par.q_focado) else "—"
        )
        q_global_txt = (
            f"{par.q_global:.2g}"
            if par.q_global is not None and math.isfinite(par.q_global)
            else "—"
        )
        console.print(
            f"    bruto {par.r_bruto:+.3f} | dentro {par.r_dentro:+.3f} | "
            f"bloco {bloco_txt} | local {par.r_local:+.3f} | "
            f"Spearman {par.spearman_local:+.3f}"
        )
        partes_q: list[str] = []
        if args.fdr in ("focado", "ambos"):
            partes_q.append(f"q focado {q_focado_txt}")
        if args.fdr in ("global", "ambos"):
            partes_q.append(f"q global {q_global_txt}")
        console.print(
            f"    IC95 bootstrap {ic_txt} | p perm {p_txt} | "
            + " | ".join(partes_q)
        )
        benchmark_txt = (
            f"{par.benchmark_percentil:.0f}º percentil de "
            f"{par.benchmark_n} pares ({par.benchmark_tipo})"
            if par.benchmark_percentil is not None
            else f"indisponível ({par.benchmark_n} pares, {par.benchmark_tipo})"
        )
        loo_txt = (
            f"[{par.loo_min:+.2f}; {par.loo_mediana:+.2f}; {par.loo_max:+.2f}]"
            if math.isfinite(par.loo_min)
            else "—"
        )
        console.print(f"    benchmark {benchmark_txt} | LOO {loo_txt}")
        console.print(
            f"    P(B|A) {par.p_b_a_inf:.1%}–{par.p_b_a_sup:.1%} | "
            f"P(A|B) {par.p_a_b_inf:.1%}–{par.p_a_b_sup:.1%} | "
            f"largura {max(par.largura_a, par.largura_b):.0%} | "
            f"{par.flag_covotacao}"
        )
        if par.goodman_b_a is not None:
            goodman_txt = f"{par.goodman_b_a:+.3f}"
            if par.goodman_b_a_inf is not None and par.goodman_b_a_sup is not None:
                goodman_txt += (
                    f" [{par.goodman_b_a_inf:+.2f}; {par.goodman_b_a_sup:+.2f}]"
                )
            if par.goodman_flag:
                goodman_txt += " !"
            console.print(f"    Goodman P(B|A) {goodman_txt}")
        if par.flag_covotacao != "informativo":
            console.print(
                "[yellow]    Co-votação individual: não identificada para este par "
                "(limites largos).[/yellow]"
            )

    for caminho_escrito in escritos:
        rotulo = "HTML" if caminho_escrito.suffix.lower() == ".html" else "CSV"
        console.print(f"[green]{rotulo}:[/green] {caminho_escrito}")
    return 0


def cmd_correlacao(client: CachedClient, args: argparse.Namespace) -> int:
    """Correlação ecológica e limites de co-votação a partir da planilha de BUs."""

    from eleitor.services.correlacao import (
        analisar_correlacoes,
        analisar_covotacao,
        construir_dados,
        escrever_correlacao_csv,
        escrever_covotacao_csv,
        escrever_matriz_csv,
        montar_relatorio,
        nome_base,
        resumo_covotacao,
        selecionar,
    )
    from eleitor.services.mapa_urnas import conferir_planilha
    from eleitor.sources.planilha import PlanilhaError, ler_planilha

    caminho = Path(args.xlsx)
    try:
        with console.status("Lendo a planilha de BUs..."):
            planilha = ler_planilha(caminho)
    except PlanilhaError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    for aviso in conferir_planilha(planilha):
        console.print(f"[yellow]Atenção:[/yellow] {aviso}")

    with console.status("Montando matriz de urnas e candidatos..."):
        dados = construir_dados(planilha)
        indices = selecionar(
            dados, min_votos=args.min_votos, min_cobertura=args.min_cobertura
        )

    if args.modo == "focado":
        return cmd_correlacao_focada(dados, caminho, args)

    if len(indices) < 2:
        console.print(
            "[red]Poucos candidatos com votos para correlacionar. "
            "Tente --min-votos 0 --min-cobertura 0.[/red]"
        )
        return 1

    base = nome_base(dados.meta)
    if args.out and Path(args.out).suffix.lower() == ".csv":
        saida = Path(args.out)
        if args.modo == "covotacao":
            csv_covot = saida
            csv_matriz = None
        else:
            csv_matriz = saida
            csv_covot = saida.with_name(f"{saida.stem}_covotacao.csv")
        destino = saida.parent
        csv_matriz_bruto = destino / f"{saida.stem}_bruto.csv"
    else:
        destino = Path(args.out) if args.out else caminho.parent
        destino.mkdir(parents=True, exist_ok=True)
        csv_matriz = destino / f"{base}.csv"
        csv_matriz_bruto = destino / f"{base}_bruto.csv"
        csv_covot = destino / f"{base.replace('correlacao', 'covotacao', 1)}.csv"

    resultado = None
    pares_covot = []
    escritos: list[Path] = []
    if args.modo in ("matriz", "ambos"):
        with console.status("Calculando correlações (within-local + bloco)..."):
            resultado = analisar_correlacoes(
                dados,
                indices,
                metodo_bloco=args.bloco,
                bootstrap_top=args.top,
                bootstrap_repeticoes=args.bootstrap,
                seed=args.seed,
            )
        escritos.append(escrever_correlacao_csv(resultado, csv_matriz))
        escritos.append(
            escrever_matriz_csv(
                resultado,
                csv_matriz.with_name(f"{csv_matriz.stem}_matriz.csv"),
                resultado.r_dentro,
            )
        )
        escritos.append(
            escrever_matriz_csv(resultado, csv_matriz_bruto, resultado.r_bruto)
        )
        escritos.append(
            escrever_matriz_csv(
                resultado,
                csv_matriz.with_name(f"{csv_matriz.stem}_bloco.csv"),
                resultado.r_bloco,
            )
        )

    if args.modo in ("covotacao", "ambos"):
        with console.status("Calculando limites de co-votação..."):
            pares_covot = analisar_covotacao(
                dados,
                indices,
                goodman_top=args.goodman_top,
                repeticoes=args.bootstrap,
                seed=args.seed,
            )
        escritos.append(escrever_covotacao_csv(pares_covot, csv_covot))

    caminho_html = None
    if args.html:
        if resultado is None:
            console.print(
                "[yellow]O HTML exige a matriz de correlação; use --modo matriz ou ambos.[/yellow]"
            )
        else:
            from eleitor.render.html import render_correlacao

            html = render_correlacao(montar_relatorio(dados, resultado, pares_covot))
            alvo = Path(args.html)
            if not alvo.suffix:
                alvo = alvo / f"{base}.html"
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_text(html, encoding="utf-8")
            caminho_html = alvo
            escritos.append(alvo)

    meta = dados.meta
    console.print(
        f"[bold]{meta.get('municipio') or 'município'}[/bold] — "
        f"{dados.n_urnas} urna(s), {dados.n_locais} local(is), "
        f"{len(indices)} candidato(s) selecionado(s), "
        f"{fmt_int(int(dados.comparecimento.sum()))} comparecimento(s)."
    )
    if dados.agregadas:
        console.print(
            f"[dim]{len(dados.agregadas)} urna(s) agregada(s) (ex.: {dados.agregadas[0]}); "
            "os votos já vêm somados no BU.[/dim]"
        )
    console.print(
        f"[dim]Filtro: ≥{args.min_votos * 100:.2f}% dos válidos e "
        f"≥{args.min_cobertura:.0%} das urnas. Para a matriz literalmente completa, "
        "use --min-votos 0 --min-cobertura 0.[/dim]"
    )
    if args.min_votos <= 0 or args.min_cobertura <= 0:
        console.print(
            "[yellow]Aviso: a matriz completa inclui candidatos com poucos votos; "
            "correlações altas podem ser instáveis. Prefira o filtro padrão para "
            "interpretar.[/yellow]"
        )

    if resultado is not None:
        pares = [p for p in resultado.pares if p.tipo_par != "mesmo_cargo"]
        if not pares:
            pares = list(resultado.pares)
        pares.sort(
            key=lambda p: (
                abs(p.r_bloco) if math.isfinite(p.r_bloco) else abs(p.r_dentro)
            ),
            reverse=True,
        )
        flags_curtas = {
            "associacao_forte": "forte",
            "associacao_residual": "residual",
            "substituto": "substituto",
        }
        console.print("\n[bold]Correlação ecológica[/bold] (top por |r| within-local+bloco):")
        for posicao, par in enumerate(pares[: args.top], start=1):
            console.print(
                f"[bold]{posicao:>2}.[/bold] {par.a.rotulo} × {par.b.rotulo}"
            )
            bloco_txt = (
                f"{par.r_bloco:+.3f}" if math.isfinite(par.r_bloco) else "—"
            )
            q_bloco_txt = (
                f"{par.q_bloco:.2g}" if math.isfinite(par.q_bloco) else "—"
            )
            console.print(
                f"    bruto {par.r_bruto:+.3f} | dentro {par.r_dentro:+.3f} | "
                f"bloco {bloco_txt} | IC95 dentro "
                f"[{par.ic95_dentro_inf:+.2f}; {par.ic95_dentro_sup:+.2f}] | "
                f"q dentro {par.q_dentro:.2g} | q bloco {q_bloco_txt} | "
                f"{flags_curtas.get(par.flag, par.flag)}"
            )
        texto_bloco = (
            "r bloco = PC1 dos demais candidatos (leave-one-pair-out)"
            if resultado.bloco_por_par
            else f"r bloco = índice fixo ({resultado.bloco_metodo}); "
            "use o filtro padrão para o PC1 por par"
        )
        console.print(
            f"[dim]n efetivo = {resultado.n_locais} locais; "
            f"p-valores/q usam esse n (não {resultado.n_urnas} urnas). "
            f"{texto_bloco}; IC95 por Fisher; o bootstrap, quando houver, está no CSV.[/dim]"
        )

    if pares_covot:
        contagem = resumo_covotacao(pares_covot)
        console.print(
            f"\n[bold]Co-votação[/bold] — {contagem['total']} pares entre cargos: "
            f"[green]{contagem['informativo']} informativo(s)[/green], "
            f"{contagem['parcial']} parcial(is), "
            f"[yellow]{contagem['indeterminado']} indeterminado(s)[/yellow]."
        )
        if contagem["informativo"] == 0:
            console.print(
                "[yellow]Nenhum par com limites estreitos: os dados não identificam "
                "co-votação individual para estes candidatos. A correlação ecológica "
                "continua válida como descrição.[/yellow]"
            )
        console.print("\n[bold]Limites de co-votação[/bold] (menores larguras):")
        for posicao, par in enumerate(pares_covot[: args.top], start=1):
            goodman = (
                f"{par.goodman_b_dado_a:+.2f}"
                if par.goodman_b_dado_a is not None
                else "—"
            )
            if par.goodman_flag:
                goodman += " !"
            console.print(
                f"[bold]{posicao:>2}.[/bold] {par.a.rotulo} × {par.b.rotulo}"
            )
            console.print(
                f"    P(B|A) {par.p_b_dado_a_inf:.0%}–{par.p_b_dado_a_sup:.0%} | "
                f"P(A|B) {par.p_a_dado_b_inf:.0%}–{par.p_a_dado_b_sup:.0%} | "
                f"largura {max(par.largura_a, par.largura_b):.0%} | "
                f"Goodman {goodman} | {par.flag}"
            )
        console.print(
            "[dim]P(B|A) e P(A|B) são limites exatos (não IC). "
            "“!” = Goodman com algum parâmetro fora de [0,1]; use como sensibilidade, "
            "não como verdade.[/dim]"
        )

    for caminho_escrito in escritos:
        rotulo = "HTML" if caminho_escrito.suffix.lower() == ".html" else "CSV"
        console.print(f"[green]{rotulo}:[/green] {caminho_escrito}")
    return 0


def cmd_mapa_google(client: CachedClient, args: argparse.Namespace) -> int:
    """Exporta KML (Google Earth) e CSV/KML (Google My Maps) por local."""

    from eleitor.services.exportar_google import ExportError, exportar_google
    from eleitor.services.mapa_urnas import conferir_planilha, construir_payload
    from eleitor.sources.planilha import PlanilhaError, ler_planilha

    caminho = Path(args.xlsx)
    try:
        with console.status("Lendo a planilha de BUs..."):
            planilha = ler_planilha(caminho)
    except PlanilhaError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    for aviso in conferir_planilha(planilha):
        console.print(f"[yellow]Atenção:[/yellow] {aviso}")

    if (args.a or args.b) and not args.cargo:
        console.print("[red]--a/--b exigem --cargo.[/red]")
        return 1

    with console.status("Agregando votos por local..."):
        payload = construir_payload(planilha)
    destino = Path(args.out_dir) if args.out_dir else caminho.parent / "google"
    try:
        with console.status("Gerando KML e CSV..."):
            arquivos = exportar_google(
                payload,
                destino,
                cargo=args.cargo,
                a=args.a,
                b=args.b,
                modo=args.modo,
                tamanho=args.tamanho,
            )
    except ExportError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    console.print(f"[green]Exportação Google gerada:[/green] {destino}")
    for arquivo in arquivos:
        tamanho_kb = arquivo.stat().st_size / 1024
        console.print(f"  [cyan]{arquivo.name}[/cyan] ({tamanho_kb:.0f} KB)")
    console.print(
        "[dim]Google Earth: abra o .kml. Google My Maps: importe o CSV "
        "(_my_maps.csv) ou o KML plano.[/dim]"
    )
    return 0


def cmd_selftest(client: CachedClient, args: argparse.Namespace) -> int:
    from eleitor.sources.resultados import url_ele_c, url_resultado

    console.print("[bold]Smoke test[/bold]")
    ele_c = client.get_json(url_ele_c(), ttl=TTL_LIVE)
    pleitos = [p for p in (ele_c or {}).get("pl", []) if p.get("c") == "ele2026"]
    if not pleitos:
        console.print("[red]ele-c.json não tem pleito ele2026[/red]")
        return 1
    eleicoes = [e.get("cd") for p in pleitos for e in p.get("e", [])]
    console.print(f"ele-c.json OK — eleições 2026: {eleicoes}")
    br = client.get_json(url_resultado(ELEICAO_FEDERAL, 1), ttl=TTL_LIVE)
    res = None
    if br:
        from eleitor.sources.resultados import parse_resultado

        res = parse_resultado(br)
    if res:
        console.print(
            f"Presidente BR OK — {len(res.candidatos)} candidatos, "
            f"seções {res.totalizacao.secoes_totalizadas}/{res.totalizacao.secoes_total}"
        )
    else:
        console.print("[red]Falha ao baixar resultado de Presidente BR[/red]")
        return 1
    console.print("[green]Tudo certo.[/green]")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eleitor", description="Resultados das Eleições 2026 (TSE)")
    sub = parser.add_subparsers(dest="comando")

    p_buscar = sub.add_parser("buscar", help="resultados de um município (somatório + zonas)")
    p_buscar.add_argument("municipio", help="nome do município (ex: Parauapebas)")
    p_buscar.add_argument("--uf", help="sigla da UF para desambiguar")
    p_buscar.add_argument("--cargo", type=parse_cargo, default=1, help="cargo (nome ou código)")
    p_buscar.add_argument("--turno", type=int, choices=[1, 2], default=1)
    p_buscar.add_argument("--zona", help="detalhar apenas uma zona")
    p_buscar.add_argument("--watch", type=int, metavar="SEG", default=0, help="atualiza a cada N segundos")
    p_buscar.add_argument("--todos", action="store_true", help="mostra todos os candidatos")
    p_buscar.set_defaults(func=cmd_buscar)

    p_uf = sub.add_parser("uf", help="resultados de um estado")
    p_uf.add_argument("uf")
    p_uf.add_argument("--cargo", type=parse_cargo, default=3)
    p_uf.add_argument("--turno", type=int, choices=[1, 2], default=1)
    p_uf.add_argument("--watch", type=int, metavar="SEG", default=0)
    p_uf.add_argument("--todos", action="store_true")
    p_uf.set_defaults(func=cmd_uf)

    p_br = sub.add_parser("br", help="resultado nacional (Presidente)")
    p_br.add_argument("--cargo", type=parse_cargo, default=1)
    p_br.add_argument("--turno", type=int, choices=[1, 2], default=1)
    p_br.add_argument("--watch", type=int, metavar="SEG", default=0)
    p_br.add_argument("--todos", action="store_true")
    p_br.set_defaults(func=cmd_br)

    p_gov = sub.add_parser("governadores", help="todos os governadores do Brasil de uma vez")
    p_gov.add_argument("--turno", type=int, choices=[1, 2], default=1)
    p_gov.add_argument("--watch", type=int, metavar="SEG", default=0)
    p_gov.set_defaults(func=cmd_governadores)

    p_html = sub.add_parser("html", help="gera artefato HTML offline (snapshot estilo TSE)")
    p_html.add_argument("--municipio", action="append", metavar="NOME[/UF]", help="município a incluir (pode repetir)")
    p_html.add_argument("--uf", help="UF padrão para --municipio sem /UF")
    p_html.add_argument("--out", default="resultado-2026.html", help="arquivo de saída")
    p_html.add_argument("--sem-fotos", action="store_true", help="não embutir fotos (arquivo menor)")
    p_html.add_argument("--sem-secoes", action="store_true", help="não incluir votos por seção (BU)")
    p_html.add_argument("--sem-mapa", action="store_true", help="não embutir o mapa do Brasil (estados)")
    p_html.add_argument(
        "--mapa-municipios",
        default="br",
        metavar="br|UFS|none",
        help="municípios no mapa: br (todos, padrão), pa,mg ou none",
    )
    p_html.add_argument(
        "--refazer-mapa",
        action="store_true",
        help="ignora o cache do líder por município e baixa tudo de novo",
    )
    p_html.add_argument(
        "--sem-mundo",
        action="store_true",
        help="não embutir o mapa mundial (votação para presidente no exterior)",
    )
    p_html.add_argument(
        "--refazer-mundo",
        action="store_true",
        help="ignora o cache do mapa mundial e baixa as cidades do exterior de novo",
    )
    p_html.add_argument(
        "--sem-mundo-bu",
        action="store_true",
        help="não incluir a prévia do 2º turno pelos boletins de urna (BU)",
    )
    p_html.add_argument(
        "--refazer-mundo-bu",
        action="store_true",
        help="ignora o cache incremental dos BUs do exterior e baixa tudo de novo",
    )
    p_html.add_argument(
        "--sem-financas",
        action="store_true",
        help="não incluir o ranking de gastos de campanha (prestação de contas)",
    )
    p_html.add_argument(
        "--refazer-financas",
        action="store_true",
        help="ignora o cache das contas do TSE e lê os arquivos de novo",
    )
    p_html.set_defaults(func=cmd_html)

    p_mapa = sub.add_parser("mapa", help="calcula o líder por município para o mapa (cache)")
    p_mapa.add_argument(
        "--cargo",
        type=parse_cargo,
        action="append",
        default=None,
        help="cargo (pode repetir); padrão: governador e presidente",
    )
    p_mapa.add_argument(
        "--turno",
        type=int,
        choices=[1, 2],
        action="append",
        default=None,
        help="turno (pode repetir); padrão: 1 e 2",
    )
    p_mapa.add_argument("--mapa-municipios", default="br", metavar="br|UFS", help="br (padrão) ou lista de UFs")
    p_mapa.add_argument("--refazer", action="store_true", help="ignora o cache e baixa de novo")
    p_mapa.set_defaults(func=cmd_mapa)

    p_conf = sub.add_parser(
        "conferir-mundo",
        help="compara a prévia BU do 2º turno no exterior com o resultado oficial",
    )
    p_conf.add_argument(
        "--refazer",
        action="store_true",
        help="ignora os caches dos BUs e do resultado oficial e baixa de novo",
    )
    p_conf.set_defaults(func=cmd_conferir_mundo)

    p_fin = sub.add_parser("financas", help="ranking de gastos de campanha (prestação de contas do TSE)")
    p_fin.add_argument("--cargo", type=parse_cargo, default=None, help="filtra por cargo")
    p_fin.add_argument("--uf", help="filtra por UF (ex: PA)")
    p_fin.add_argument("--ordenar", choices=["gasto", "receita", "fundos", "bens"], default="gasto")
    p_fin.add_argument("--limite", type=int, default=30, help="0 = todos")
    p_fin.add_argument("--out", help="grava o ranking em JSON")
    p_fin.add_argument("--refazer", action="store_true", help="ignora o cache das contas e lê tudo de novo")
    p_fin.set_defaults(func=cmd_financas)

    for parser_ in (p_html, p_mapa):
        parser_.add_argument(
            "--ritmo",
            type=float,
            default=None,
            metavar="SEG",
            help="intervalo mínimo entre requisições (padrão 0,15; use 0.04 para o bake nacional)",
        )
        parser_.add_argument(
            "--workers", type=int, default=None, help="requisições simultâneas (padrão 4)"
        )

    p_urnas = sub.add_parser(
        "mapa-urnas",
        help="gera mapa eleitoral por local de votação a partir de uma planilha de BUs",
    )
    p_urnas.add_argument(
        "--xlsx",
        required=True,
        metavar="ARQUIVO",
        help="planilha com as abas Locais de votação, Índice das urnas e Dados completos",
    )
    p_urnas.add_argument(
        "--out",
        help="arquivo HTML de saída (padrão: ao lado da planilha)",
    )
    p_urnas.add_argument(
        "--sem-fundo-offline",
        action="store_true",
        help="não baixar/embutir o mosaico; o padrão vira Ruas (Esri)",
    )
    p_urnas.add_argument(
        "--refazer-fundo",
        action="store_true",
        help="ignora o cache do fundo offline e baixa de novo",
    )
    p_urnas.add_argument(
        "--zoom-fundo", type=int, default=12, help="zoom do município inteiro (padrão: 12)"
    )
    p_urnas.add_argument(
        "--zoom-detalhe", type=int, default=15, help="zoom do detalhe urbano (padrão: 15)"
    )
    p_urnas.add_argument(
        "--raio-detalhe",
        type=float,
        default=8.0,
        metavar="KM",
        help="raio em km do detalhe urbano (padrão: 8)",
    )
    p_urnas.add_argument(
        "--qualidade", type=int, default=85, help="qualidade JPEG do fundo (padrão: 85)"
    )
    p_urnas.add_argument(
        "--google-dir",
        help="pasta dos KML/CSV (padrão: pasta 'google' ao lado do HTML)",
    )
    p_urnas.set_defaults(func=cmd_mapa_urnas)

    p_corr = sub.add_parser(
        "correlacao",
        help="correlação ecológica e limites de co-votação entre candidatos (BUs)",
    )
    p_corr.add_argument("--xlsx", required=True, metavar="ARQUIVO")
    p_corr.add_argument(
        "--modo",
        choices=["matriz", "covotacao", "ambos", "focado"],
        default="ambos",
        help="matriz, co-votação, os dois ou relatório focado de pares (padrão: ambos)",
    )
    p_corr.add_argument(
        "--min-votos",
        type=float,
        default=0.005,
        help="fração mínima dos válidos do cargo (padrão: 0,005 = 0,5%%)",
    )
    p_corr.add_argument(
        "--min-cobertura",
        type=float,
        default=0.9,
        help="fração mínima de urnas com voto > 0 (padrão: 0,9)",
    )
    p_corr.add_argument(
        "--bloco",
        choices=["presidente", "pc1", "none"],
        default="presidente",
        help="referência de sinal/fallback do bloco; o controle efetivo é o PC1 dos demais candidatos (padrão: presidente)",
    )
    p_corr.add_argument(
        "--bootstrap",
        type=int,
        default=1000,
        help="réplicas de bootstrap por cluster de local (0 desliga; padrão: 1000)",
    )
    p_corr.add_argument(
        "--goodman-top",
        type=int,
        default=50,
        help="quantos pares recebem estimativa de Goodman (padrão: 50)",
    )
    p_corr.add_argument(
        "--top", type=int, default=20, help="linhas nas tabelas do terminal (padrão: 20)"
    )
    p_corr.add_argument("--seed", type=int, default=42)
    p_corr.add_argument(
        "--out",
        help="diretório ou arquivo CSV de saída (padrão: ao lado da planilha)",
    )
    p_corr.add_argument("--html", help="arquivo HTML de saída (opcional)")
    p_corr.add_argument(
        "--pares",
        action="append",
        metavar="PAR",
        help="par focado: 'Cargo:numero; Cargo:numero' (repita ou separe por |)",
    )
    p_corr.add_argument(
        "--pares-arquivo",
        metavar="ARQUIVO",
        help="arquivo com um par por linha (padrão: In Put/pares.txt)",
    )
    p_corr.add_argument(
        "--permutacoes",
        type=int,
        default=5000,
        help="permutações within-local para o p focado (padrão: 5000)",
    )
    p_corr.add_argument(
        "--benchmark",
        choices=["fed-est", "same-party", "todos", "none"],
        default="fed-est",
        help="grupo de referência do benchmark (padrão: fed-est)",
    )
    p_corr.add_argument(
        "--fdr",
        choices=["focado", "global", "ambos"],
        default="ambos",
        help="quais q-FDR exibir no resumo (padrão: ambos)",
    )
    p_corr.add_argument(
        "--sem-loo",
        action="store_true",
        help="não calcular leave-one-local-out",
    )
    p_corr.set_defaults(func=cmd_correlacao)

    p_google = sub.add_parser(
        "mapa-google",
        help="exporta KML (Google Earth) e CSV/KML (Google My Maps) por local",
    )
    p_google.add_argument(
        "--xlsx",
        required=True,
        metavar="ARQUIVO",
        help="planilha com as abas de locais, urnas e dados completos",
    )
    p_google.add_argument(
        "--out-dir",
        help="pasta de saída (padrão: pasta 'google' ao lado da planilha)",
    )
    p_google.add_argument(
        "--cargo",
        help="cargo único (padrão: todos os cargos); ex.: governador",
    )
    p_google.add_argument("--a", help="número do candidato A (exige --cargo)")
    p_google.add_argument("--b", help="número do candidato B (exige --cargo)")
    p_google.add_argument(
        "--modo",
        choices=["vencedor", "diferenca"],
        default="vencedor",
        help="cor do pino: vencedor ou escala de diferença (padrão: vencedor)",
    )
    p_google.add_argument(
        "--tamanho",
        choices=["aptos", "votos"],
        default="aptos",
        help="tamanho do pino: eleitores aptos ou votos de A/B (padrão: aptos)",
    )
    p_google.set_defaults(func=cmd_mapa_google)

    p_sec = sub.add_parser("secoes", help="seções/urnas de um município")
    p_sec.add_argument("municipio")
    p_sec.add_argument("--uf")
    p_sec.add_argument("--zona")
    p_sec.add_argument("--limite", type=int, default=200, help="0 = todas")
    p_sec.set_defaults(func=cmd_secoes)

    p_secao = sub.add_parser("secao", help="votos de uma seção (boletim de urna)")
    p_secao.add_argument("municipio")
    p_secao.add_argument("--uf")
    p_secao.add_argument("--zona", required=True)
    p_secao.add_argument("--secao", required=True, dest="numero_secao")
    p_secao.add_argument("--cargo", type=parse_cargo, default=1)
    p_secao.add_argument("--turno", type=int, choices=[1, 2], default=1)
    p_secao.set_defaults(func=cmd_secao)

    p_votos = sub.add_parser("votos", help="votos por seção em uma zona (todos os BUs)")
    p_votos.add_argument("municipio")
    p_votos.add_argument("--uf")
    p_votos.add_argument("--zona", required=True)
    p_votos.add_argument("--cargo", type=parse_cargo, default=1)
    p_votos.add_argument("--turno", type=int, choices=[1, 2], default=1)
    p_votos.set_defaults(func=cmd_votos)

    p_mun = sub.add_parser("municipios", help="lista municípios e zonas de uma UF")
    p_mun.add_argument("uf")
    p_mun.set_defaults(func=cmd_municipios)

    p_selftest = sub.add_parser("selftest", help="testa conectividade com a API do TSE")
    p_selftest.set_defaults(func=cmd_selftest)

    sub.add_parser("atualizar", help="limpa o cache local").set_defaults(func=None)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = build_parser()
    args = parser.parse_args(argv)

    ritmo = getattr(args, "ritmo", None)
    workers = getattr(args, "workers", None)
    with CachedClient(
        min_interval=ritmo if ritmo is not None else DEFAULT_MIN_INTERVAL,
        workers=workers or 4,
    ) as client:
        if args.comando is None:
            try:
                menu(client)
            except (TTSError, RateLimited) as exc:
                console.print(f"[red]{exc}[/red]")
                return 1
            return 0

        if args.comando == "atualizar":
            removidos = client.clear_cache()
            console.print(f"Cache limpo ({removidos} arquivos).")
            return 0

        try:
            return args.func(client, args)
        except (TTSError, RateLimited) as exc:
            console.print(f"[red]{exc}[/red]")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
