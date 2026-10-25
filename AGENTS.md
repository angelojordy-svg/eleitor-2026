# AGENTS.md

## Visão geral
CLI Python (`eleitor`) para acompanhar as Eleições 2026 do TSE em tempo real: resultado por
município/zona/seção (BU binário ASN.1) e site HTML offline (resultados, mapa e finanças).
Stack: Python >=3.10, `httpx`, `rich`, `asn1tools`, `openpyxl`, `Pillow`, `numpy`.
Código em `src/eleitor/`; testes em `tests/`.

## Comandos
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest                    # rápido, sem rede
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
.venv\Scripts\eleitor mapa-urnas --xlsx "In Put\boletim_urna_parauapebas_2026_z75_z106_com_locais.xlsx"
                                                  # HTML + fundo OSM offline + KML/CSV Google (In Put\google)
.venv\Scripts\eleitor mapa-google --xlsx "In Put\boletim_urna_parauapebas_2026_z75_z106_com_locais.xlsx"
                                                  # KML (Google Earth) + CSV/KML (Google My Maps) em In Put\google
publicar-mapa.bat                                 # gera e publica em /mapa/parauapebas/ (gh-pages)
.venv\Scripts\eleitor correlacao --xlsx "In Put\boletim_urna_parauapebas_2026_z75_z106_com_locais.xlsx" `
    --modo ambos --top 20 --bootstrap 1000 --out "In Put" --html "In Put\correlacao.html"
                                                  # matriz -1..1 + limites de co-votação + HTML
.venv\Scripts\eleitor correlacao --xlsx "In Put\boletim_urna_parauapebas_2026_z75_z106_com_locais.xlsx" `
    --modo focado --pares-arquivo "In Put\pares.txt" --bootstrap 2000 --permutacoes 5000 `
    --out "In Put" --html "In Put\focado_parauapebas_2026.html"
                                                  # relatório focado por par (p focado, FDR, benchmark, limites)
```
Publicar o site nacional: duplo clique em `publicar.bat` (gera o HTML e faz push na `gh-pages`).
Publicar o mapa por local: duplo clique em `publicar-mapa.bat` (gera fundo/HTML/Google e publica em `/mapa/parauapebas/`).

## Mapa do código
- `config.py` — códigos de 2026, cargos, TTLs (fonte de verdade).
- `http.py` — `CachedClient`: cache em disco com ETag/304, throttle 0,15s, `get_json`/`get_bytes`/`get_urls`.
- `paises.py` — tabela estática `CIDADE_PAIS`/`PAISES` (código TSE da cidade do exterior → ISO2/nome),
  usada pelo mapa mundial; 134 países com seção + Vaticano (sem cidade no config de 2026).
- `sources/resultados.py` — URLs + parsers EA12/EA16/EA20.
- `sources/bu.py` — BU (ASN.1 BER; specs em `spec/`; tenta v2 depois v1).
- `sources/urna.py` — nomes/URLs de arquivos de urna (aux -> hash -> BU).
- `sources/geo.py` — malhas do IBGE (retry/backoff, cache `%LOCALAPPDATA%\eleitor\geo`), projeção Albers,
  `geo_para_paths`; mapa mundial em Natural Earth 50m map units (`ISO_A2_EH`, cache `mundo-50m.json`) com
  projeção Mollweide e `mundo_para_paths`.
- `sources/contas.py` — prestação de contas + cadastro + bens (CSV ISO-8859-1); download com impressão digital
  (`Last-Modified`/tamanho) em `%LOCALAPPDATA%\eleitor\contas`, leitura em streaming; só a variante `_BRASIL`.
  `parse_receitas` devolve a ponte `SQ_PRESTADOR_CONTAS → SQ_CANDIDATO` usada por `parse_despesas_pagas`.
- `services/financas.py` — `bake_financas()` agrega por `SQ_CANDIDATO` (cache `financas\contas-{ano}.json`).
  Só candidatos com receita/gasto > 0. `fundos` = FP (`FUNDO PARTIDARIO`) + FEFC (`FUNDO ESPECIAL`); `gasto` = despesas pagas.
- `services/mapa.py` — resumo por UF + `bake_resultado_municipios` (cache retomável `mapa\res-{cargo}-t{turno}.json`;
  `VERSAO_BAKE` força recálculo; guarda `ufs` p/ não confundir bake parcial com nacional).
- `services/mundo.py` — mapa mundial: `bake_mundo` soma as cidades do exterior por país (1º/2º turno; o 2º
  turno só consulta as 186 cidades se o agregado `zz` tiver votos), `coletar_mundo` junta geometria +
  `res`/`validos`/`total`/`meta`; Brasil fica só como geometria (cinza).
- `services/snapshot.py` — dados do HTML offline (Brasil/estados/municípios/seções/fotos/mapa/mundo/geometria e finanças).
  Finanças = vetores alinhados (`colunas`+`itens`); votos por `SQ_CANDIDATO` da EA20 (Presidente = nacional, estaduais = por UF).
- `sources/planilha.py` — lê a planilha de BUs com `openpyxl` (Leia-me, Locais, Índice das urnas, Resumo por urna,
  Dados completos). Normaliza cabeçalhos sem acento; devolve dataclasses (`LocalVotacao`, `Urna`, `ResumoUrna`, `Voto`).
- `services/mapa_urnas.py` — agrega urna → local pela chave **zona + código** e monta a matriz `votos[local][candidato]`
  por cargo; `conferir_planilha()` valida resumo × linhas de votos; `render/mapa_urnas.html` é o mapa Leaflet.
- `services/exportar_google.py` — KML (Google Earth: pastas por cargo, balão HTML, ícone colorido/tamanho) e
  CSV/KML plano por cargo (Google My Maps: colunas A/B, vencedor, margem e `Faixa` para estilizar).
- `services/fundo_offline.py` — mosaico OSM (z12 município + z15 urbano) costurado com Pillow, cache em
  `%LOCALAPPDATA%\eleitor\fundo` e fallback para Esri Street; vira `L.imageOverlay` embutido no HTML.
- `docs/mapa-eleitoral-google.md` — detalhamento das fases OSM, Google e publicação.
- `mapa-index.html` + `publicar-mapa.bat` — índice de cidades e publicação em `gh-pages` via worktree.
- `services/correlacao.py` — matriz de correlação ecológica (log-ratio/ALR, within-local, PC1 dos demais
  candidatos como bloco), limites determinísticos de co-votação, Goodman, bootstrap de clusters por local e BH-FDR.
  Também tem o modo focado: `parse_par`/`ler_pares_arquivo`, `resolver_pares`, `analisar_pares_focados`,
  `bootstrap_par`, `permutacao_par`, `leave_one_local_out`, `_agregados_por_local`, `benchmark` e CSV/HTML.
- `render/correlacao.html` — relatório standalone (heatmap, top pares, tabela de limites); `render_correlacao()`.
- `render/focado.html` + `render/focado.py` — relatório focado estático (SVG de dispersão local, resíduos
  within-local, histograma de benchmark e limites por local); `render_focado()`.
- `In Put/pares.txt` — template do “espaço aberto” de pares (`Cargo:numero ; Cargo:numero`); criado pelo modo
  focado quando não há lista.
- `render/vendor/leaflet/` — Leaflet 1.9.4 (BSD-2) **embutido** no HTML por `render_mapa_urnas()` (sem CDN/unpkg).
  Mapa base: **offline embutido (padrão)**, **Ruas (Esri)**, **Satélite (Esri)** ou nenhum; `tileerror` avisa 403.
  **CARTO não usar** (chave desde 25/09/2026) e **OSM online não usar na rede do usuário** (bloqueado).
- `render/` — `html.py` + `template.html` (artefato único, navegação por hash, página de candidato, botão "Atualizar online",
  aba `#/ranking` de gastos via `viewRanking()`, aba `#/mundo` via `viewMundo()` com hover que soma as cidades do país,
  balão do mapa via `ligarMapa()`).
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

## Fatos do mundo (mapa)
- Votação no exterior = UF `zz` na eleição **6257** (1º turno) / **6258** (2º). O config de 6259 **não** tem `zz`.
  186 cidades em 134 países/territórios (918.876 eleitores aptos em 2026); o Vaticano tem 0 e não está no config.
- URL por cidade: `.../{eleicao}/dados/zz/zz{mun:05d}-c0001-e{eleicao:06d}-u.json`; agregado: `zz/zz-c0001-...`.
  O TSE **não** publica o total por país: `services/mundo.py` soma as cidades de cada país (`paises.py`).
- 1º turno de 2026 (final): 1.351/1.351 seções, 330.882 válidos; a soma das 186 cidades bate exatamente com o
  agregado `zz` (Lula 157.387 / Flávio 143.900). O 2º turno começa zerado; consultar o agregado antes evita 186 404s.
- Casos ambíguos de cidade→país já resolvidos: Concepción→PY, Rio Branco→UY, São José→CR, São Salvador→SV,
  São Domingos→DO, Puerto Iguazú→AR, Puerto Quijarro→BO, Santa Elena de Uairén→VE, St Georges de Loyapock→GF.
- Geometria: Natural Earth **50m map units** (domínio público; `ISO_A2_EH`) porque a 110m não tem 9 países com votos;
  a malha de países junta a Guiana Francesa na França, os map units não. Mollweide, `eps=0,35`, viewBox ~980×431,
  payload ~200 KB. Antártida/territórios inabitados (`AQ,TF,BV,HM,GS,IO`) ficam fora.
- Várias feições com o mesmo ISO/código são somadas (`geo_para_paths`); o nome do país é o da maior feição
  (Portugal continental > Açores > Madeira; Cisjordânia + Gaza = PS). Brasil entra só como geometria cinza.
- No hover o navegador busca as cidades do país (1–10 req; debounce de 280 ms) e agrega por número de candidato;
  o "Atualizar online" busca só o agregado `zz` do 2º turno (as cores por país atualizam no hover).

## Fatos estatísticos (correlação / co-votação)
- A unidade é a **urna**; o cluster é o **local** (55 em Parauapebas). A ICC das shares é ~0,98: o n efetivo é
  ~55, não 586. p-valores,q e ICs usam o n efetivo; nunca tratar urnas como independentes.
- **Correlação ecológica ≠ transferência individual.** O voto secreto só entrega marginais; a tabela conjunta
  “votou em A e em B” não é observada (falácia ecológica). Use “associação/apoio compartilhado”, não “transferência”.
- Co-votação: limites determinísticos `L=max(0,a+b−N)`, `U=min(a,b)`; `P(B|A)∈[L/a,U/a]`. Em Parauapebas 2026,
  **nenhum par** ficou informativo (larguras ≥81%); os dados não identificam co-votação individual.
- `r_bloco` controla o **PC1 dos demais candidatos calculado sem o próprio par** (leave-one-pair-out), com sinal
  alinhado ao voto presidencial. Não usar o próprio par para definir o bloco (gera correlação mecânica).
- Senador tem 2 votos por eleitor: não comparar “share de Senado” com “share de Governador”; use votos por eleitor
  ou o denominador de válidos do próprio cargo.
- Pares do mesmo cargo (fora Senador) são **substitutos** (a soma 1 força correlação negativa); não interpretar como
  transferência. Nomes da planilha podem vir com `�` (encoding); use número/partido como chave.
- Modo focado: p-permutação **within-local** para pares pré-especificados, q-FDR global/focado, benchmark de pares
  (fed×est, same-party ou todos), leave-one-local-out e limites por local. Em Hipólito (Est 22100) × Caveira
  (Fed 2200): `r_dentro≈0,379`, bootstrap [0,31;0,45], `p_perm≈0,0002`, `q_global≈0,087`; limites
  `P(Hipólito|Caveira)=0–100%`; nenhum local identifica co-votação.

## Estado atual
Pronto: resultados ao vivo (BR/UF/município/zona), seções via EA18, votos por seção via BU, artefato HTML offline
(Brasil/estados/municípios/seções/congresso), mapa do Brasil (estados + 5.571 municípios, 1º/2º turno, cor por
partido + maioria, hachura no 2º turno, balão com votação/apuração), **mapa mundial** (aba `#/mundo`: votação no
exterior por país, 1º/2º turno, hover que soma as cidades, tabela e Brasil cinza; geometria Natural Earth/Mollweide),
**finanças** (CLI `eleitor financas` + aba
`#/ranking`; ~16.962 candidatos, dados parciais), **mapa por local de votação** (CLI `eleitor mapa-urnas` +
`In Put/mapa_eleitoral_parauapebas_2026.html`: 55 locais, 586 urnas, comparação A×B por cargo em Leaflet com
fundo OSM offline embutido e ruas Esri online; publicado em
`https://angelojordy-svg.github.io/eleitor-2026/mapa/parauapebas/`), **exportação Google** (CLI
`eleitor mapa-google` + `In Put/google/`: KML combinado com 5 pastas, KML plano e CSV por cargo para Google
Earth/My Maps), **correlação/co-votação** (CLI `eleitor correlacao` + CSV +
`render/correlacao.html`: matriz -1..1, within-local, bloco PC1, limites determinísticos e Goodman) e
**relatório focado** (CLI `--modo focado` + `In Put/pares.txt` + `render/focado.html`: bootstrap,
permutação, benchmark, LOO e limites por local). Pendente: refinos das finanças (export CSV, quebra FP/FEFC
no detalhe do candidato), dashboard web, EI de King (fase 2, opcional) e painel 2022→2026 (fase 3, opcional).
Dados de produção podem ficar zerados até a totalização avançar; use `selftest`.
