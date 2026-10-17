# AGENTS.md

## Visão geral
CLI Python (`eleitor`) para acompanhar resultados das Eleições 2026 do TSE em tempo real:
busca por município (somatório oficial), detalhe por zona e votos por seção (BU binário ASN.1).
Stack: Python >=3.10, `httpx`, `rich`, `asn1tools`. Código em `src/eleitor/`.

## Comandos
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"   # instala o pacote + pytest
.venv\Scripts\python -m pytest                     # todos os testes (~0,4s, sem rede)
.venv\Scripts\python -m pytest tests/test_bu.py    # um arquivo
.venv\Scripts\eleitor                              # menu interativo (entrypoint)
.venv\Scripts\eleitor buscar Parauapebas --uf pa --cargo governador
.venv\Scripts\eleitor secoes Parauapebas --uf pa --zona 75
.venv\Scripts\eleitor secao Parauapebas --uf pa --zona 75 --secao 1 --cargo governador
.venv\Scripts\eleitor votos Parauapebas --uf pa --zona 75 --cargo governador
.venv\Scripts\eleitor governadores --watch 60      # todos os governadores do Brasil
.venv\Scripts\eleitor html --municipio Ananindeua/PA --out resultado-2026.html
.venv\Scripts\eleitor mapa --cargo governador --turno 1 --ritmo 0.04 --workers 10   # bake do mapa
.venv\Scripts\eleitor financas --cargo governador --ordenar gasto   # ranking de gastos de campanha
.venv\Scripts\eleitor selftest                     # smoke test com a API real
```

## Mapa do código
- `config.py` — códigos de 2026, cargos, TTLs (fonte de verdade).
- `http.py` — `CachedClient`: cache em disco com ETag/304, throttle de 0,15s, `get_json`/`get_bytes`/`get_urls`.
- `sources/resultados.py` — builders de URL + parsers EA12/EA16/EA20.
- `sources/bu.py` — parser do boletim de urna (ASN.1 BER, specs em `spec/`, tenta v2 depois v1).
- `sources/urna.py` — nomes/URLs de arquivos de urna (aux -> hash -> BU).
- `sources/geo.py` — malhas do IBGE (retry/backoff, cache em `%LOCALAPPDATA%\eleitor\geo`),
  projeção Albers e conversão da malha em paths SVG (`geo_para_paths`).
- `sources/contas.py` — **prestação de contas** (receitas/despesas pagas), cadastro e bens (CSV
  ISO-8859-1). Download com **impressão digital** (só rebaixa quando `Last-Modified`/tamanho mudam) em
  `%LOCALAPPDATA%\eleitor\contas` e leitura em *streaming* do ZIP. Lê só a variante `_BRASIL`.
  `parse_receitas` devolve a **ponte `SQ_PRESTADOR_CONTAS → SQ_CANDIDATO`** usada por `parse_despesas_pagas`.
- `services/financas.py` — `bake_financas()` junta cadastro+bens+receitas+despesas por `SQ_CANDIDATO`;
  cache do agregado caro em `%LOCALAPPDATA%\eleitor\financas\contas-{ano}.json` por impressão do ZIP.
  Só entram candidatos com receita/gasto > 0. `fundos` = Fundo Partidário (`FUNDO PARTIDARIO`) + FEFC
  (`FUNDO ESPECIAL`); `gasto` = despesas **pagas**.
- `services/mapa.py` — resumo por UF para o mapa: partido do mais votado + força da maioria.
  Também faz o **bake do líder por município** (`bake_resultado_municipios`), com cache
  retomável em `%LOCALAPPDATA%\eleitor\mapa\res-{cargo}-t{turno}.json` (só grava `completo`
  no fim; um bake interrompido continua de onde parou). O arquivo guarda `versao` (mudar
  `VERSAO_BAKE` força recalcular) e `ufs` (um bake parcial, ex.: só PA, não engana um bake
  nacional). Resultados saem como vetores alinhados por índice com a geometria, para não
  repetir a chave do município no payload.
- `services/snapshot.py` — coleta dados para o HTML offline (Brasil, estados, municípios, seções, fotos, mapa,
  geometria municipal e líder por município, e **finanças**). A seção `financas` sai como vetores alinhados
  (`colunas` + `itens`) e os **votos por `SQ_CANDIDATO`** vêm da EA20 já baixada (Presidente = total nacional,
  estaduais = por UF). Sem finanças (rede fora do ar), o artefato sai sem a aba.
- `render/` — `html.py` + `template.html` (artefato único, navegação por hash, página de candidato,
  botão "Atualizar online" que busca EA20 do TSE via fetch/CORS quando há internet, e a aba
  **Gastos de campanha** em `#/ranking` via `viewRanking()`/`atualizarRanking()`: filtra Brasil/UF +
  cargo, ordena por gasto/receita/fundos/patrimônio/votos/custo por voto e liga à página do candidato).
  O mapa usa um **balão próprio** (não o `<title>` nativo): mostra votação e apuração, busca o
  número ao vivo com *debounce* de 280 ms e **para quando a apuração da área chega a 100%**
  (`MAPA_ENCERROU`). Vale saber: os `<path>` não têm `onclick` inline — a navegação e o balão
  são tratados por delegação em `ligarMapa()`, e no toque o 1º tap informa, o 2º abre.
  A paleta (`CORES`) tem **matizes espaçados de propósito** (~40° no núcleo PL/PSD/PP/PODE/MDB/
  REPUBLICANOS/UNIÃO/PSDB/PT) porque o tom claro e o cheio mantêm a matiz — cores próximas
  (o antigo PL x PSD) ficavam indistinguíveis. Se mexer, confira a distância CIEDE2000.
  Estado que vai ao 2º turno leva **hachura** (padrão de dois tons, sobre a cor do partido).
- `services/` — busca de município (EA12) e orquestração de votos/seções.
- `cli.py` — argparse + menus rich. `models.py` — dataclasses.

## Fatos do TSE que não são óbvios (não redescobrir)
- Base: `https://resultados.tse.jus.br/oficial`, ciclo `ele2026`, pleito de urna `3220`.
- Eleições: **6257** = Presidente; **6259** = Governador/Senador/Dep. Federal/Dep. Estadual/Distrital;
  6261 = Conselheiro Distrital; 2º turno = 6258/6260. **Dep. Federal NÃO está em 6257.**
- Resultado EA20: `.../{eleicao}/dados/{br|uf}/{prefixo}-c{cargo:04d}-e{eleicao:06d}-u.json`,
  prefixo: `br`, `{uf}`, `{uf}{mun:05d}` (município = somatório) ou `{uf}{mun:05d}-z{zona:04d}`.
- Seções EA16: `.../arquivo-urna/3220/config/{uf}/{uf}-p003220-cs.json` (atributos `da`/`ha` indicam
  que o aux da seção existe; só baixar aux de seção com `da` evita 404 em massa).
- Aux EA18: `.../arquivo-urna/3220/dados/{uf}/{mun:05d}/{zona:04d}/{secao:04d}/p003220-{uf}-m{mun}-z{zona}-s{secao}-aux.json`.
- BU: `.../{hash}/{nome}` — formato v2 (`-bu.dat`) e v1 (`.bu`); nomes vêm de `arq[].nm` (v2) ou `nmarq` (v1).
- Fotos de candidato: `.../{eleicao}/fotos/{uf|br}/{sqcand}.jpeg` (uf `br` só para Presidente).
- `nsa`/`nsp` na EA16 = seções agregadas (compartilham urna): não contar duas vezes.
- **Limite 100 req/s por IP; 404s em excesso podem bloquear por 10 min.** URLs sempre com zero-padding
  (município 5, zona/seção 4, cargo 4, eleição/pleito 6). Nunca varrer IDs no chute.
- CSVs do TSE: ISO-8859-1, separador `;`, valor decimal com vírgula (`30000,00`).

## Fatos do TSE — prestação de contas (finanças)
- Base dos ZIPs: `https://cdn.tse.jus.br/estatistica/sead/odsele/` → contas em `prestacao_contas/`,
  cadastro em `consulta_cand/`, bens em `bem_candidato/` (arquivos `..._2026.zip`). Expoem `Content-Length`
  e `Last-Modified` no `HEAD`, então dá para saber se mudaram sem baixar.
- `prestacao_de_contas_eleitorais_candidatos_2026.zip` = **186 MB** (receitas, despesas pagas e contratadas,
  por UF + BRASIL). `consulta_cand_2026.zip` ~3,2 MB e `bem_candidato_2026.zip` ~3,7 MB.
- Cada ZIP tem variantes **por UF e uma `_BRASIL`**; ler as duas conta em dobro. Use `_BRASIL`.
  O cadastro ainda tem linhas repetidas por turno: **deduplicar por `SQ_CANDIDATO`**.
- `despesas_pagas` **não** tem `SQ_CANDIDATO` (só `SQ_PRESTADOR_CONTAS`). A ponte
  `SQ_PRESTADOR_CONTAS → SQ_CANDIDATO` sai das **receitas** (cobertura de 100% hoje).
- `DS_FONTE_RECEITA` só tem `FUNDO PARTIDARIO`, `FUNDO ESPECIAL` (FEFC), `OUTROS RECURSOS` e `#NULO`.
  `DS_FONTE_DESPESA` (pagas): Fundo Especial, Fundo Partidário, Outros Recursos.
- `DS_SITUACAO_CANDIDATURA` vem **`#NE` para todos** em 2026 (não serve p/ impedido/impugnado); o status
  sai de `DS_SIT_TOT_TURNO` (`ELEITO`, `ELEITO POR QP`/`MÉDIA`, `SUPLENTE`, `NÃO ELEITO`, `2º TURNO`, `#NULO`).
- Prestação **parcial** hoje (`TP_PRESTACAO_CONTAS` = RELATÓRIO FINANCEIRO/PARCIAL); os números crescem até a final.

## Fatos do IBGE (mapa)
- Malha das UFs: `https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=UF`
  (27 feições; `properties.codarea` = **código IBGE da UF**, 2 dígitos — tabela `IBGE_UF_CODIGO` no `config.py`).
  Custa ~96 KB e é a única consulta que o mapa de estados precisa.
- Malha dos municípios de uma UF: `.../malhas/estados/{UF}?...&intrarregiao=municipio`
  (`codarea` = 7 dígitos, **igual ao campo `cdi`/`Municipio.ibge` do EA12** — é a chave do join).
  Brasil inteiro em uma chamada: ~3,4 MB (mínima) / 11,7 MB (intermediária). Município individual: `.../malhas/municipios/{cdi}`.
- O IBGE **devolve 404 espúrio quando recebe requisições em rajada** (volta ao normal depois); por isso
  `sources/geo.py` só grava 200 no cache e repete com espera crescente. CORS é liberado (`Access-Control-Allow-Origin: *`).
- Resultado por município (para colorir) = EA20 por município (`{uf}{mun:05d}`), 1 requisição por município/cargo/turno.
- `paths_municipios(uf)` projeta **cada estado no próprio quadro 1000×1000** (mapa municipal enche a tela);
  por isso a geometria municipal final (~1,6 MB) é maior que a soma das malhas cruas simplificadas em um quadro só.
- Custo do mapa nacional embutido (medido): artefato 6,55 → 8,59 MB (geometria municipal 1,6 MB + líder por
  município 0,44 MB para 2 combos, incluindo o % de apuração). O `bake` do 1º turno é definitivo (TTL 24 h);
  o do 2º turno só roda quando a apuração começa (`combos_com_dados`) e revalida sempre.
- A entrada por área no mapa é `[partido, % válidos, votos, nome, apuração%]` (no 2º turno, uma lista com o
  top 2). O `apuracao%` vem do próprio EA20 (`s.pst`), então o balão informa apuração e votação sem
  requisição extra; o blob é atualizado ao vivo só enquanto `apuracao% < 100`.
- Boa Esperança do Norte/MT (IBGE 5101837) é novo e ainda não tem malha no IBGE: fica fora do mapa municipal.

## Estado atual
Implementado: resultados ao vivo (BR/UF/município/zona), seções com status via EA18, votos por seção via BU,
artefato HTML offline (Brasil/estados/municípios/seções/congresso) e **mapa do Brasil** com estados e
**municípios dos 5.571 municípios** (Governador e Presidente, 1º e 2º turno, cor pelo mais votado +
intensidade pela maioria, **hachura** onde vai ao 2º turno) e **balão + rótulos com votação e apuração**
(embutida + ao vivo, parando em 100%). **Gastos de campanha** (finanças): coleta/bake + CLI `eleitor financas`
e a aba `#/ranking` no artefato (receita, fundos FP+FEFC, gasto pago, patrimônio, votos e custo por voto;
~16.962 candidatos, 1,54 MB, dados parciais).
Pendente: refinos das finanças (export CSV, quebra FP/FEFC no detalhe do candidato), dashboard web.
Dados de produção podem ficar zerados até a totalização avançar; use `selftest`.
