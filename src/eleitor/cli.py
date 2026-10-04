from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Sequence

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
from eleitor.http import CachedClient, RateLimited, TTSError
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
                "0. Sair",
                title="Menu",
                expand=False,
            )
        )
        opcao = Prompt.ask("Opção", choices=["1", "2", "3", "4", "5", "6", "0"], default="1")

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
            )
            try:
                cmd_html(client, args_html)
            except (TTSError, RateLimited) as exc:
                console.print(f"[red]{exc}[/red]")
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

    def progresso(msg: str) -> None:
        console.print(f"[dim]{msg}[/dim]")

    with console.status("Coletando dados para o snapshot..."):
        dados = coletar_snapshot(
            client,
            loc,
            municipios,
            com_fotos=not args.sem_fotos,
            com_secoes=not args.sem_secoes,
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
    p_html.set_defaults(func=cmd_html)

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

    with CachedClient() as client:
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
