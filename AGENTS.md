# AGENTS.md

## Visão geral
CLI Python (`eleitor`) para acompanhar as Eleições 2026 do TSE em tempo real: resultado por
município/zona/seção (BU binário ASN.1) e site HTML offline (resultados, mapa e finanças).
Stack: Python >=3.10, `httpx`, `rich`, `asn1tools`. Código em `src/eleitor/`; testes em `tests/`.

## Comandos
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest                    # ~0,4s, sem rede
.venv\Scripts\eleitor                             # menu interativo
.venv\Scripts\eleitor buscar Parauapebas --uf pa --cargo governador
.venv\Scripts\eleitor secoes Parauapebas --uf pa --zona 75
.venv\Scripts\eleitor secao Parauapebas --uf pa --zona 75 --secao 1 --cargo governador
.venv\Scripts\eleitor votos Parauapebas --uf pa --zona 75 --cargo governador
.venv\Scripts\eleitor governadores --watch 60
.venv\Scripts\eleitor html --municipio Ananindeua/PA --out resultado-2026.html
.venv\Scripts\eleitor mapa --cargo governador --turno 1 --ritmo 0.04 --workers 10
.venv\Scripts\eleitor financas --cargo governador --ordenar gasto
.venv\Scripts\eleitor selftest                    # smoke test com a API real
```
Publicar o site: duplo clique em `publicar.bat` (gera o HTML e faz push na branch `gh-pages`).

## Mapa do código
- `config.py` — códigos de 2026, cargos, TTLs (fonte de verdade).
- `http.py` — `CachedClient`: cache em disco com ETag/304, throttle 0,15s, `get_json`/`get_bytes`/`get_urls`.
- `sources/resultados.py` — URLs + parsers EA12/EA16/EA20.
- `sources/bu.py` — BU (ASN.1 BER; specs em `spec/`; tenta v2 depois v1).
- `sources/urna.py` — nomes/URLs de arquivos de urna (aux -> hash -> BU).
- `sources/geo.py` — malhas do IBGE (retry/backoff, cache `%LOCALAPPDATA%\eleitor\geo`), projeção Albers, `geo_para_paths`.
- `sources/contas.py` — prestação de contas + cadastro + bens (CSV ISO-8859-1); download com impressão digital
  (`Last-Modified`/tamanho) em `%LOCALAPPDATA%\eleitor\contas`, leitura em streaming; só a variante `_BRASIL`.
  `parse_receitas` devolve a ponte `SQ_PRESTADOR_CONTAS → SQ_CANDIDATO` usada por `parse_despesas_pagas`.
- `services/financas.py` — `bake_financas()` agrega por `SQ_CANDIDATO` (cache `financas\contas-{ano}.json`).
  Só candidatos com receita/gasto > 0. `fundos` = FP (`FUNDO PARTIDARIO`) + FEFC (`FUNDO ESPECIAL`); `gasto` = despesas pagas.
- `services/mapa.py` — resumo por UF + `bake_resultado_municipios` (cache retomável `mapa\res-{cargo}-t{turno}.json`;
  `VERSAO_BAKE` força recálculo; guarda `ufs` p/ não confundir bake parcial com nacional).
- `services/snapshot.py` — dados do HTML offline (Brasil/estados/municípios/seções/fotos/mapa/geometria e finanças).
  Finanças = vetores alinhados (`colunas`+`itens`); votos por `SQ_CANDIDATO` da EA20 (Presidente = nacional, estaduais = por UF).
- `render/` — `html.py` + `template.html` (artefato único, navegação por hash, página de candidato, botão "Atualizar online",
  aba `#/ranking` de gastos via `viewRanking()`, balão do mapa via `ligarMapa()`).
- `cli.py` — argparse + menus rich. `models.py` — dataclasses.

## Fatos do TSE (não redescobrir)
- Base: `https://resultados.tse.jus.br/oficial`, ciclo `ele2026`, pleito de urna `3220`.
- Eleições: 6257 = Presidente; 6259 = Governador/Senador/Dep. Federal/Estadual/Distrital; 6261 = Conselheiro
  Distrital; 2º turno = 6258/6260. **Dep. Federal NÃO está em 6257.**
- EA20: `.../{eleicao}/dados/{br|uf}/{prefixo}-c{cargo:04d}-e{eleicao:06d}-u.json`; prefixo `br`, `{uf}`,
  `{uf}{mun:05d}` (município = somatório) ou `{uf}{mun:05d}-z{zona:04d}`.
- EA16: `.../arquivo-urna/3220/config/{uf}/{uf}-p003220-cs.json` (`da`/`ha` indicam se o aux da seção existe;
  só baixar aux com `da` evita 404 em massa).
- EA18: `.../arquivo-urna/3220/dados/{uf}/{mun:05d}/{zona:04d}/{secao:04d}/p003220-{uf}-m{mun}-z{zona}-s{secao}-aux.json`.
- BU: `.../{hash}/{nome}` — v2 (`-bu.dat`) e v1 (`.bu`); nomes de `arq[].nm` (v2) ou `nmarq` (v1).
- Fotos: `.../{eleicao}/fotos/{uf|br}/{sqcand}.jpeg` (`br` só para Presidente).
- `nsa`/`nsp` na EA16 = seções agregadas (compartilham urna): não contar duas vezes.
- **100 req/s por IP; 404s em excesso bloqueiam por 10 min.** URLs com zero-padding (município 5, zona/seção 4,
  cargo 4, eleição/pleito 6). Nunca varrer IDs no chute.
- CSVs do TSE: ISO-8859-1, separador `;`, decimal com vírgula (`30000,00`).

## Fatos do TSE — finanças
- Base dos ZIPs: `https://cdn.tse.jus.br/estatistica/sead/odsele/` → `prestacao_contas/`, `consulta_cand/`,
  `bem_candidato/` (`..._2026.zip`). HEAD expõe `Content-Length`/`Last-Modified` (saber se mudou sem baixar).
- Tamanhos: prestação 186 MB; cadastro ~3,2 MB; bens ~3,7 MB.
- Cada ZIP tem variantes por UF **e** `_BRASIL`: ler as duas conta em dobro — use `_BRASIL`. Cadastro repete linhas
  por turno: deduplicar por `SQ_CANDIDATO`.
- `despesas_pagas` não tem `SQ_CANDIDATO` (só `SQ_PRESTADOR_CONTAS`); a ponte sai das receitas (cobertura 100% hoje).
- `DS_FONTE_RECEITA`: `FUNDO PARTIDARIO`, `FUNDO ESPECIAL` (FEFC), `OUTROS RECURSOS`, `#NULO`.
- `DS_SITUACAO_CANDIDATURA` vem `#NE` para todos em 2026 (não serve p/ impedido/impugnado); status sai de
  `DS_SIT_TOT_TURNO` (`ELEITO`, `ELEITO POR QP`/`MÉDIA`, `SUPLENTE`, `NÃO ELEITO`, `2º TURNO`, `#NULO`).
- Prestação **parcial** hoje (`TP_PRESTACAO_CONTAS` = RELATÓRIO FINANCEIRO/PARCIAL): os números crescem até a final.

## Fatos do IBGE (mapa)
- Malha das UFs: `.../malhas/paises/BR?...&intrarregiao=UF` (27 feições; `properties.codarea` = código IBGE da UF,
  tabela `IBGE_UF_CODIGO` no `config.py`). Só o mapa de estados usa essa consulta.
- Malha dos municípios de uma UF: `.../malhas/estados/{UF}?...&intrarregiao=municipio` (`codarea` = 7 dígitos,
  igual a `cdi`/`Municipio.ibge` do EA12 — chave do join). Município individual: `.../malhas/municipios/{cdi}`.
- IBGE **devolve 404 espúrio em rajada** (normaliza depois): `geo.py` só grava 200 no cache e repete com espera
  crescente. CORS liberado (`Access-Control-Allow-Origin: *`).
- `paths_municipios(uf)` projeta **cada estado no próprio quadro 1000×1000** (por isso a geometria municipal ~1,6 MB).
- Custo do mapa no artefato (medido): 6,55 → 8,59 MB (geometria 1,6 MB + líder/município 0,44 MB p/ 2 combos).
  Bake do 1º turno é definitivo (TTL 24 h); o do 2º só roda quando a apuração começa (`combos_com_dados`) e revalida sempre.
- Entrada por área: `[partido, % válidos, votos, nome, apuração%]` (2º turno: lista com o top 2). `apuracao%` vem do
  EA20 (`s.pst`); o blob atualiza ao vivo só enquanto `apuracao% < 100`.
- Boa Esperança do Norte/MT (IBGE 5101837) é novo e sem malha no IBGE: fica fora do mapa municipal.

## Estado atual
Pronto: resultados ao vivo (BR/UF/município/zona), seções via EA18, votos por seção via BU, artefato HTML offline
(Brasil/estados/municípios/seções/congresso), mapa do Brasil (estados + 5.571 municípios, 1º/2º turno, cor por
partido + maioria, hachura no 2º turno, balão com votação/apuração) e **finanças** (CLI `eleitor financas` + aba
`#/ranking`; ~16.962 candidatos, dados parciais).
Pendente: refinos das finanças (export CSV, quebra FP/FEFC no detalhe do candidato), dashboard web.
Dados de produção podem ficar zerados até a totalização avançar; use `selftest`.
