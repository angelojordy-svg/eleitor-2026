# Projeto — Aba "Gastos de Campanha" (Ranking)

**Status:** Fases 1 e 2 concluídas · Fase 3 (refinos) pendente · **Data:** 17/10/2026
**Resposta curta:** sim, dá para fazer. Os dados abertos do TSE para 2026 já existem e
estão frescos (arquivo de contas atualizado hoje). O que falta é **agregar 186 MB de CSV
num único bake** e ligar isso ao artefato HTML que já existe.

---

## 1. Objetivo

Adicionar uma **aba nova** ao artefato (`#/ranking`) com um ranking de candidatos por
dinheiro de campanha, pesquisável por **Brasil / estado / cargo**, com opção
**Geral** ou **por cargo**.

## 2. Perguntas que a aba responde

- Quem mais **gastou** na campanha (e em qual cargo/estado)?
- Quanto cada candidato recebeu de **Fundo Partidário** e do **FEFC** (Fundo Especial)?
- **Patrimônio declarado** x **votos** x **gasto** — visão lado a lado.
- **Custo por voto** (ronaldo derivado).
- Situação: **eleito / suplente / não eleito / 2º turno**.

## 3. Fontes de dados (verificadas em 17/10/2026)

| Dado | URL | Tamanho | Observação |
|---|---|---|---|
| Prestação de contas — candidatos 2026 | `https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2026.zip` | 186 MB | Atualizado **17/10/2026 07:26 GMT**. Receitas, despesas pagas e contratadas, por UF + BRASIL. |
| Candidatos 2026 | `https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2026.zip` | 3,2 MB | Situação (`DS_SIT_TOT_TURNO`), turno, cargo, partido. |
| Bens (patrimônio) 2026 | `https://cdn.tse.jus.br/estatistica/sead/odsele/bem_candidato/bem_candidato_2026.zip` | 3,7 MB | `VR_BEM_CANDIDATO` por `SQ_CANDIDATO`. |
| Votos | já no projeto (EA20) | — | Join por `SQ_CANDIDATO` (`sqcand`). |

Encoding **ISO-8859-1**, separador `;` (igual ao resto dos CSVs do TSE).

## 4. Campos → origem

| Coluna da aba | Origem |
|---|---|
| Receita total | `Σ VR_RECEITA` por candidato (`receitas_candidatos_2026`) |
| Fundos (Fundo Partidário + FEFC) | `Σ VR_RECEITA` onde `DS_FONTE_RECEITA` ∈ {`FUNDO PARTIDARIO`, `FUNDO ESPECIAL`} — **coluna única**; a quebra FP/FEFC fica guardada no dado para o detalhe |
| Total gasto | `Σ VR_PAGTO_DESPESA` (`despesas_pagas_candidatos_2026`) — **somente pagas** |
| Patrimônio declarado | `Σ VR_BEM_CANDIDATO` por candidato (`bem_candidato_2026`) |
| Votos | EA20 (`cand.sqcand` → votos) |
| Situação | `DS_SIT_TOT_TURNO` do cadastro + `eleito`/`suplente` já calculado |

## 5. Achados técnicos (o que decide o desenho)

Medido nos arquivos reais de hoje:

- **20.989 candidatos** no cadastro (arquivos por UF **e** um BRASIL — é preciso
  deduplicar por `SQ_CANDIDATO`; se ler os dois, conta em dobro: 42.034 linhas).
- **19.249** candidatos já têm receitas; **13.824** têm despesas pagas; **12.943** têm bens.
- **`despesas_pagas` NÃO traz `SQ_CANDIDATO`** — só `SQ_PRESTADOR_CONTAS`.
  É preciso a **ponte `SQ_PRESTADOR_CONTAS → SQ_CANDIDATO`** que existe em receitas.
  100% dos prestadores de despesa casaram (13.824 de 13.824). Limitação: quem gastou
  e **não** tem receita registrada ainda não aparece no gasto.
- Join do cadastro: **19.249/19.249 (100%)**.
- `DS_FONTE_RECEITA` só tem: `FUNDO PARTIDARIO`, `FUNDO ESPECIAL`, `OUTROS RECURSOS`, `#NULO`.
- `DS_FONTE_DESPESA` (pagas): Fundo Especial (FEFC), Fundo Partidário, Outros Recursos.
- Situações existentes: `ELEITO`, `ELEITO POR QP`, `ELEITO POR MÉDIA`, `SUPLENTE`,
  `NÃO ELEITO`, `2º TURNO` — e `#NULO` para quem ainda não tem resultado (ex.: os
  finalistas do 2º turno de Presidente aparecem como `#NULO` até a votação).
- **`DS_SITUACAO_CANDIDATURA` vem `#NE` para todos** em 2026 — não serve para
  impedido/impugnado. Então o status sai de `DS_SIT_TOT_TURNO` **+** `st`/`dvt` da
  EA20 (os votos "anulado sub judice" que o projeto já lê). Revisar quando o TSE preencher.
- Movimento de campanha até agora: **16.962 candidatos** com receita ou gasto > 0.
- `TP_PRESTACAO_CONTAS`: `RELATÓRIO FINANCEIRO`, `PARCIAL`, `FINAL` → hoje é
  majoritariamente parcial. **Os números vão crescer** até a prestação final.

## 6. Como entra no projeto (arquitetura)

Espelhando o que já existe no mapa:

- `sources/contas.py` — baixa/descompacta os 3 zips, parseia e agrega por `SQ_CANDIDATO`.
- `services/financas.py` — **bake com cache retomável** em
  `%LOCALAPPDATA%\eleitor\financas\` (mesmo padrão de `mapa.py`, com `versao`).
- `services/snapshot.py` — nova seção `financas` no payload.
- `render/template.html` — `viewRanking()` + rota `#/ranking` + card na home.
- `cli.py` — `eleitor financas` e flags `--sem-financas` / `--financas-refazer` no `html`.

**Tamanho estimado no artefato:** ~1,5–3 MB (arrays alinhados e chaves curtas, como no
mapa). Hoje o artefato tem 8,59 MB.

## 7. UX da aba

- Filtros: **escopo** (Brasil / UF), **cargo** (Geral ou cargo específico), **busca**
  (nome/partido/número), **ordenar por** (receita, FP, FEFC, gasto, patrimônio, votos,
  custo por voto).
- Tabela: `#`, candidato, partido, UF, cargo, situação, receita, **fundos**, gasto,
  patrimônio, votos, custo/voto.
- Selo de situação + aviso de **dados parciais** com a data do arquivo.

## 8. Escopo

**Dentro:** receitas, **fundos somados (FP + FEFC)**, despesas pagas, patrimônio, votos,
situação (inclui **impedido / impugnado**), ranking + filtros.
**Fora (fase 2):** despesas contratadas, doadores (doador originário), extratos
bancários, gráficos, export CSV.

## 9. Fases

1. Bake + CLI (agregar e validar os números).
2. Aba no HTML (ranking + filtros).
3. Refinos (custo por voto, download CSV, destaque de situação).

## 10. Riscos

- Parse de 186 MB: roda **só no bake**, nunca no navegador.
- Dados parciais: o ranking muda até a prestação final — deixar isso explícito na tela.
- Custo por voto com divisão por zero (candidato sem voto/dados).
- Identificar o candidato do gasto depende da ponte via receitas (cobertura atual 100%).

## 11. Decisões tomadas (travadas em 17/10/2026)

1. **Gasto** = despesas **pagas**.
2. **Fundos** = Fundo Partidário **+** FEFC **somados numa coluna**. (A quebra fica no dado.)
3. Ranking só com quem **aparece**; dados **atualizáveis** conforme o TSE for preenchendo.
4. Fica **no mesmo artefato** (offline), com **cadências de atualização separadas**.
5. Status inclui **impedido / impugnado** (`DS_SITUACAO_CANDIDATURA`), não só o resultado.

## 12. Atualização e cadências (decisão 4)

O artefato é estático; cada parte envelhece em ritmo diferente e isso fica visível na tela:

| Dado | Cadência | Como atualiza |
|---|---|---|
| Resultados (votos) | ao vivo | botão **Atualizar online** (EA20 via CORS), já existe |
| Contas / finanças | ~diária (arquivo do TSE) | **re-bake** + republicar |
| Cadastro / bens | esporádica | junto no re-bake |

- O bake de finanças guarda a **impressão digital da fonte** (`Last-Modified` +
  `Content-Length` do zip) e a `DT_GERACAO` de dentro do CSV. Se o arquivo não mudou,
  o `eleitor html` reaproveita o cache **sem re-baixar 186 MB**.
- A aba mostra sempre **"Contas: gerado em &lt;DT_GERACAO&gt; — parcial"**.
- Para publicar dados novos: `eleitor html` + `publicar.bat` (fluxo que já existe).

## 13. Plano de execução por fases

### Fase 1 — Coleta + bake + CLI (sem UI) — ✅ CONCLUÍDA

- `src/eleitor/sources/contas.py`: URLs das 3 fontes, download com **impressão digital**
  (só rebaixa quando o arquivo remoto muda), parsers em streaming e **ponte
  `SQ_PRESTADOR_CONTAS → SQ_CANDIDATO`** das despesas pagas. Lê só a variante `_BRASIL`.
- `src/eleitor/services/financas.py`: `bake_financas()` junta cadastro + bens + receitas +
  despesas; cache do agregado caro em `%LOCALAPPDATA%\eleitor\financas\contas-{ano}.json`
  por impressão do ZIP. Só entram candidatos com receita ou gasto > 0.
- `cli.py`: `eleitor financas [--cargo] [--uf] [--ordenar gasto|receita|fundos|bens]
  [--limite] [--out] [--refazer]` + item 7 no menu.
- Testes: `tests/test_contas.py` (10 casos) com ZIPs minúsculos em latin-1.
- **Validado contra dado real (17/10/2026):** 16.962 candidatos; top gasto
  (Flávio Bolsonaro) confere **exatamente** com a soma direta do CSV
  (R$ 67.556.449,40). 2ª execução reusa o cache em ~3 s em vez de reprocessar 186 MB.
- **Correção de bug pré-existente:** `main()` usava `args.ritmo`/`args.workers`, que só
  existiam em `html`/`mapa` — **todo comando** quebrava com `AttributeError`. Agora usa
  `getattr`.

### Fase 2 — Aba no artefato — ✅ CONCLUÍDA

- `snapshot.py`: seção `financas` com **vetores alinhados** (`colunas` + `itens`) e votos por
  `SQ_CANDIDATO` vindos da EA20 já baixada (Presidente = total nacional; estaduais = por UF).
  A coleta é tolerante a falha: sem finanças, o artefato sai sem a aba.
- `template.html`: `viewRanking()` + rota `#/ranking` + card na home, com filtros
  **Brasil/UF**, **cargo/todos**, busca por nome/número e ordenação (gasto, receita, fundos,
  patrimônio, votos, custo por voto). Selo de situação (eleito/suplente/não eleito) e aviso
  de **parcial** com a data do arquivo. Cada linha abre a **página do candidato**.
- `cli.py`: flags `--sem-financas` e `--refazer-financas` no `html`.
- Testes: `_financas_dict` (compactação + votos) e render da aba.
- **Validado:** artefato de 6,7 MB (sem mapa) com **1,54 MB** de finanças e **16.962**
  candidatos; votos conferem (Flávio 56,1 mi, Lula 53,9 mi).

### Fase 3 — Refinos
- Export CSV e destaque de situação (o **custo por voto** já entrou na Fase 2).
- Quebra FP/FEFC no detalhe do candidato.

**Estimativa:** Fase 1 é a mais pesada (parse de 186 MB); Fases 2 e 3 são incrementais.
