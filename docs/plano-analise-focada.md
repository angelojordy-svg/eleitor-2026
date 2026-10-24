# Plano e método estatístico — análise focada de pares

**Status:** fase 1 implementada e executada em 2026-10-24. Fases 2 (EI) e 3 (painel 2022) pendentes.
**Data:** 2026-10-24
**Escopo:** correlação ecológica e co-votação entre candidatos a partir da planilha de BUs,
com ênfase em pares Deputado Federal × Deputado Estadual e no par
**Hipólito (Est 22100) × Delegado Caveira (Fed 2200)**.

---

## 1. Objetivo

Criar um “espaço aberto” para escolher pares depois, sem hardcode:

- a lista fica em `In Put/pares.txt` (editável, com comentários);
- o comando lê esse arquivo e produz um relatório focado;
- se a lista estiver vazia, o comando explica o formato e não executa;
- o relatório separa claramente o que é **medido** do que é **modelado**.

O plano cobre:

1. a estatística descritiva e inferencial da associação ecológica;
2. os limites determinísticos de co-votação;
3. o modelo de Goodman como sensibilidade;
4. a inferência ecológica de King como fase opcional, com suas suposições;
5. desenhos alternativos mais fortes (painel 2022→2026 e survey individual);
6. critérios de aceite, poder estatístico, diagnósticos e referências.

---

## 2. Dados e unidades

- Fonte: planilha de boletins de urna (BU) do TSE, 1º turno de 2026.
- Unidade de observação: **urna**.
- Cluster: **local de votação** (combinação zona + código do local).
- Em Parauapebas/PA: 586 urnas, 55 locais, 156.468 comparecimentos.
- Cargos: Presidente, Governador, Senador (2 votos por eleitor), Deputado Federal,
  Deputado Estadual.
- Votos usados: **nominais**. Votos de legenda entram no denominador de válidos,
  mas não são atribuídos a um candidato.
- Denominador:
  - cargos de 1 voto: `n_{io} = votos válidos do cargo na urna i`;
  - Senador: `n_{io} = soma dos votos válidos de Senador` (≈ 2 por eleitor);
  - comparecimento: `N_i`.
- Para comparações entre cargos, preferir **votos por eleitor** `v_{ij}/N_i`
  ou o log-ratio; não comparar “share de Senador” com “share de Governador”
  como se tivessem o mesmo denominador.

### 2.1 Qualidade dos dados

- Auditoria já feita: `nominais + legenda = válidos` e
  `válidos + brancos + nulos = total` em todas as 2.930 linhas de resumo.
- Há 1 urna agregada (75-637, `agrega=723`); a seção 723 não aparece separada,
  então não há dupla contagem. Em sensibilidade, excluir essa urna.
- Nomes de candidatos podem vir com `�` (encoding). Usar `cargo + número`
  como chave e exibir o nome apenas como rótulo.
- Os dados são o **censo das urnas do município**, não uma amostra aleatória.
  ICs e p-valores não medem erro amostral; medem incerteza sobre o processo
  gerador/transportabilidade e sobre o comportamento individual não observado.

---

## 3. O que é identificável

### 3.1 Associação ecológica

É a co-variação entre **lugares** (urnas/locais):

\[
\text{urnas onde A é forte} \leftrightarrow \text{urnas onde B é forte}.
\]

É estimável diretamente dos BUs. Pode ser positiva porque o mesmo eleitor votou
nos dois, mas também por composição geográfica, bloco partidário, campanha
conjunta, coattail etc. **Correlação ecológica não é transferência individual.**

### 3.2 Co-votação individual

Pergunta: “dos eleitores que votaram em A, quantos também votaram em B?”.

A tabela 2×2 (A/não A × B/não B) **não é observada**. O voto é secreto e os BUs
entregam apenas as marginais. Sem dados individuais, a resposta é um **problema
de inferência ecológica**: no melhor caso, limites; no pior, nada identificado.

### 3.3 Falácia ecológica

Robinson (1950) mostrou que a correlação agregada pode ter sinal oposto à
correlação individual. Portanto:

- usar “associação”, “apoio compartilhado”, “co-movimento”;
- **não** usar “transferência”, “o eleitor de A votou em B”, “A transferiu para B”;
- qualquer afirmação individual exige dados individuais ou um modelo com
  suposições explícitas e testáveis.

---

## 4. Notação

- \(i = 1,\dots,n\): urnas; \(g(i)\): local da urna \(i\); \(G\): número de locais.
- \(o\): cargo.
- \(v_{ij}\): votos nominais do candidato \(j\) na urna \(i\).
- \(n_{io}\): votos válidos do cargo \(o\) na urna \(i\).
- \(N_i\): comparecimento na urna \(i\).
- \(p_{ij} = v_{ij}/n_{io}\): share do candidato \(j\) no cargo \(o\).
- \(e_{ij} = v_{ij}/N_i\): votos por eleitor.
- \(a = \sum_i v_{iA}\), \(b = \sum_i v_{iB}\), \(N = \sum_i N_i\).

Pesos padrão: \(w_i = N_i\). Em sensibilidade, usar \(w_i = n_{io}\) ou
\(w_i = \min(n_{iA}, n_{iB})\).

---

## 5. Transformação e correlação

### 5.1 Por que transformar

Shares do mesmo cargo somam 1 (fechamento composicional). Correlacionar shares
cruas impõe correlação negativa artificial entre candidatos do mesmo cargo.
Para reduzir esse problema, usar uma transformação log-ratio:

\[
x_{ij} = \log\!\left(\frac{v_{ij} + c}{n_{io} - v_{ij} + c}\right),
\qquad c = 0{,}5.
\]

Essa é uma transformação **ALR** (additive log-ratio) com “todos os outros votos
válidos” como referência. A pseudocontagem \(c\) estabiliza urnas com zero votos.
O resultado é interpretável como log-odds de votar em \(j\) contra os demais.

- Para cargos de 1 voto, a transformação é estritamente monotônica na share.
- Para Senador (2 votos), \(n_{io}\) é o total de votos válidos do cargo;
  a transformação continua válida, mas a interpretação é “share entre votos de
  Senador”, não “share entre eleitores”.
- Em sensibilidade, repetir com logit de votos por eleitor e com shares cruas.

### 5.2 Correlação ponderada

Pearson ponderada:

\[
r_w(x,y) =
\frac{\sum_i w_i (x_i-\bar x_w)(y_i-\bar y_w)}
{\sqrt{\sum_i w_i (x_i-\bar x_w)^2}\,
 \sqrt{\sum_i w_i (y_i-\bar y_w)^2}},
\quad
\bar x_w = \frac{\sum_i w_i x_i}{\sum_i w_i}.
\]

- `r_bruto`: \(r_w\) entre as urnas, sem controle.
- `r_dentro`: \(r_w\) entre resíduos within-local.
- `r_bloco`: \(r_w\) entre resíduos within-local + bloco.
- `r_local`: correlação entre os \(G=55\) locais (Pearson e Spearman),
  descritiva; não usar como se fosse \(n=586\).

### 5.3 Within-local (efeito fixo de local)

\[
\tilde x_i = x_i - \bar x_{w,g(i)},
\qquad
\tilde y_i = y_i - \bar y_{w,g(i)}.
\]

`r_dentro = r_w(\tilde x, \tilde y)`.

Isso remove diferenças fixas entre locais (perfil socioeconômico, localização,
histórico). Ainda pode haver confundimento por diferenças entre seções dentro do
mesmo local e por composição dos eleitores. Não é um experimento.

### 5.4 Bloco político (PC1 leave-one-pair-out)

Para o par \((A,B)\):

1. montar a matriz \(X_{-AB}\) com as log-odds dos **demais** candidatos
   selecionados;
2. padronizar cada coluna;
3. SVD: \(X_{-AB} = U S V^\top\);
4. escore do primeiro componente: \(z = U_{\cdot,1} S_{1}\);
5. alinhar o sinal com a diferença presidencial (ou com o índice fixo escolhido);
6. residualizar \(z\) no local;
7. residualizar \(x_A\) e \(x_B\) no local e em \(z\);
8. correlacionar os resíduos.

Isso evita controlar o par por ele mesmo. No modo com muitos candidatos
(> 60), o cálculo por par é desativado por custo e usa-se um índice fixo
(presidencial); pares que definem o índice ficam com `r_bloco` indefinido.

**Importante:** `r_bloco` mede associação **residual** ao bloco comum. Não é
transferência e não é causal. O PC1 é uma proxy do bloco, não uma ideologia
medida.

---

## 6. Inferência

### 6.1 Bootstrap de clusters

- Reamostrar **locais** com reposição; manter todas as urnas do local sorteado.
- Recalcular within-local e \(r\) em cada réplica.
- IC95% percentil (2,5% e 97,5%).
- Esse é o IC preferido para os pares focados. Ele respeita a correlação
  intra-local; não corrige autocorrelação espacial entre locais.

### 6.2 Permutação within-local

- Para testar \(H_0\): nenhuma associação dentro do local.
- Em cada local, permutar os valores de \(y\) entre as urnas do local.
- Recalcular \(r\); repetir \(B\) vezes.
- \(p = \frac{1 + \#\{|r^*| \ge |r|\}}{B+1}\).
- Para o par focado, esse é o **p-pré-especificado**.
- Para todos os pares, aplicar BH-FDR.

### 6.3 Aproximação de Fisher (para a matriz)

Para a matriz completa, usar a aproximação de Fisher com \(n_{eff}\):

\[
z = \operatorname{artanh}(r), \quad
SE = \frac{1}{\sqrt{n_{eff}-3}}, \quad
p = 2\{1-\Phi(|z|/SE)\}.
\]

- `r_bruto`: \(n_{eff}=G\) (conservador; não usar \(n=586\)).
- `r_dentro`: \(n_{eff}=G-1\).
- `r_bloco`: \(n_{eff}=G-2\).
- A aproximação é só uma triagem; para os pares focados, usar bootstrap e
  permutação.

### 6.4 BH-FDR

Ordenar os \(m\) p-valores; para \(k=1,\dots,m\):

\[
q_{(k)} = \min_{l \ge k} \frac{m\,p_{(l)}}{l}.
\]

- Reportar **p focado** e **q-FDR** lado a lado.
- Se o par foi escolhido **antes** de olhar os dados, o p focado é a inferência
  principal; o q-FDR é transparência.
- Se o par foi escolhido **depois** de varrer todos os pares, o q-FDR é o
  critério relevante.

### 6.5 Benchmark de pares

Comparar o \(r\) do par alvo com uma distribuição de referência:

- pares do mesmo tipo (ex.: todos os Federal × Estadual);
- pares do mesmo partido/coligação;
- pares com totais de votos semelhantes (mesmo decil de \(a+b\)).

Reportar:

- percentil do alvo;
- média/mediana/quantis da referência;
- z-score robusto (mediana/MAD);
- número de pares de referência.

Isso responde “o par é especial?” sem fingir que responde “o eleitor votou nos
dois?”.

### 6.6 Leave-one-local-out

Para cada local \(g\), recalcular `r_dentro` sem \(g\). Reportar mínimo,
mediana e máximo. Se a associação desaparecer ao remover um local, ela é
frágil. Em Parauapebas, para Hipólito × Caveira, a faixa observada foi
0,366–0,392, indicando estabilidade.

### 6.7 Autocorrelação espacial

- Calcular Moran's I dos resíduos using centroides dos locais e pesos
  k-vizinhos.
- Se significativo, o bootstrap por local pode subestimar a incerteza.
- Alternativas: bootstrap por blocos espaciais, erros de Conley (1999) ou
  incluir vizinhança espacial no modelo.
- Reportar como diagnóstico, não como correção automática.

---

## 7. Co-votação: limites determinísticos

### 7.1 Tabela 2×2

Para um par \((A,B)\) de cargos diferentes (ou Senador × Senador):

|  | votou B | não votou B | total |
|---|---:|---:|---:|
| votou A | \(x\) | \(a-x\) | \(a\) |
| não votou A | \(b-x\) | \(N-a-b+x\) | \(N-a\) |
| total | \(b\) | \(N-b\) | \(N\) |

\(x\) é o número de eleitores que votaram nos dois. Só as marginais são
observadas.

### 7.2 Limites

\[
L = \max(0,\; a+b-N), \qquad U = \min(a,b).
\]

\[
P(B\mid A) \in \left[\frac{L}{a},\frac{U}{a}\right],
\qquad
P(A\mid B) \in \left[\frac{L}{b},\frac{U}{b}\right].
\]

Esses limites são **exatos**, sem suposições. A largura relativa é

\[
W_A = \frac{U-L}{a}, \qquad W_B = \frac{U-L}{b}.
\]

Critério de informatividade:

- \(W_A \le 0{,}2\) e \(W_B \le 0{,}2\): **informativo**;
- \(W_A \ge 0{,}5\) ou \(W_B \ge 0{,}5\): **indeterminado**;
- caso contrário: **parcial**.

### 7.3 Por que deputados são um caso difícil

Para deputados federal/estadual, cada candidato tem uma fração minoritária dos
votos. Em todos os 55 locais de Parauapebas, para Hipólito × Caveira,
\((a_g+b_g)/N_g\) ficou entre 0,005 e 0,43. Como \(a+b<N\), \(L=0\) em todos os
locais; o limite superior é \(\min(a,b)\). Logo, \(P(\text{Hipólito}\mid
\text{Caveira}) \in [0,1]\) e não há informação individual.

### 7.4 Limites por local

Calcular \(L_g,U_g,a_g,b_g,N_g\) em cada local. Sob a suposição forte de
**taxa comum** entre locais, a interseção é

\[
\left[\max_g \frac{L_g}{a_g},\; \min_g \frac{U_g}{a_g}\right].
\]

Isso **não** é uma identificação sem a suposição de taxa comum. Em
Hipólito × Caveira, a interseção é degenerada: um local com \(b_g=0\) força 0;
os demais vão até 1. Para a direção inversa, a interseção vai até 0,508, mas o
limite inferior continua 0.

### 7.5 Mesmo cargo

- Cargos de 1 voto: A e B são mutuamente exclusivos; a interseção é
  estruturalmente 0. Não calcular co-votação; apenas marcar “substituto”.
- Senador: cada eleitor tem 2 votos; A e B podem ser votados juntos. Os
  limites 2×2 continuam válidos, com \(N\) = eleitores.

---

## 8. Goodman: regressão ecológica

### 8.1 Modelo

Para cada urna \(i\):

\[
x_i = \frac{a_i}{N_i}, \qquad y_i = \frac{b_i}{N_i},
\]

\[
y_i = \alpha + \beta x_i + \varepsilon_i.
\]

Estimar por WLS com pesos \(N_i\). Interpretação:

\[
P(B\mid A) = \alpha+\beta, \qquad
P(B\mid \neg A) = \alpha.
\]

### 8.2 Suposições

- linearidade da relação entre as taxas;
- taxas \(P(B|A)\) e \(P(B|\neg A)\) constantes entre urnas (ou, ao menos,
  não correlacionadas com \(x_i\));
- erros com média zero e variância bem comportada;
- ausência de viés de agregação.

### 8.3 Diagnósticos

- estimativas fora de \([0,1]\): flag imediata;
- resíduos vs. ajustados; pontos influentes;
- comparar WLS com OLS, com agregação por local e com bootstrap por cluster;
- comparar com os limites determinísticos: se Goodman sai dos limites, o modelo
  é incompatível com os dados.

### 8.4 Resultado para Hipólito × Caveira

- \(P(\text{Hipólito}\mid\text{Caveira}) = 1{,}085\) — impossível;
- \(P(\text{Caveira}\mid\text{Hipólito}) = 0{,}483\) [0,422; 0,528];
- logo, Goodman não é uma base confiável para este par; usar somente como
  sensibilidade.

---

## 9. Inferência ecológica de King (fase opcional)

### 9.1 Modelo 2×2

Para cada unidade \(i\), sejam

\[
\beta_i^A = P(B\mid A), \qquad
\beta_i^B = P(B\mid \neg A).
\]

As marginais observadas são \(x_i=a_i/N_i\) e \(y_i=b_i/N_i\), com a restrição

\[
y_i = \beta_i^A x_i + \beta_i^B (1-x_i).
\]

King (1997) modela \((\beta_i^A,\beta_i^B)\) com uma normal bivariada truncada
no quadrado \([0,1]^2\), com médias \((\phi^A,\phi^B)\), covariância e
truncamento. A verossimilhança integra sobre a linha determinística acima.
O modelo estendido permite covariáveis para as médias, para reduzir viés de
agregação.

### 9.2 Suposições e diagnósticos

- forma distribucional (normal truncada);
- constância em média/mediana, ou modelagem explícita da heterogeneidade;
- truncamento e independência condicional;
- diagnósticos: tomography plot, viés de agregação, sensibilidade a priors,
  posterior predictive checks.

### 9.3 Por que não é o método principal aqui

- Os limites determinísticos são \([0,100\%]\); a verossimilhança é fraca.
- Goodman já produz estimativa impossível.
- O resultado dependeria de priors e da forma funcional, não dos dados.
- EI **estima sob suposições**; não **verifica** co-votação.

### 9.4 Implementação opcional

- R: pacote `ei` (King & Roberts) ou `eiCompare`.
- Python: `pyei` (MMGG), que depende de `pymc`, `jax`, `numba`, `netCDF4`;
  instalação pesada e não recomendada no ambiente atual.
- Alternativa: implementação própria 2×2 com MLE/MCMC e priors fracos;
  sempre reportar diagnósticos e comparar com os limites.
- Fase 2, desligada por padrão (`--ei`).

---

## 10. Desenhos alternativos mais fortes

### 10.1 Painel 2022→2026 por urna

Se as seções forem estáveis, calcular

\[
\Delta a_i = a_{i,2026}-a_{i,2022}, \qquad
\Delta b_i = b_{i,2026}-b_{i,2022}.
\]

Regredir \(\Delta b_i\) em \(\Delta a_i\) com efeito fixo de local e controles
de comparecimento/base. Isso remove confundidores fixos no tempo e testa
co-movimento de **mudanças**.

- Ainda é ecológico; não identifica o indivíduo.
- Requer BUs de 2022, seções compatíveis e candidatos comparáveis.
- É o próximo passo mais forte sem dados individuais.

### 10.2 Survey individual

Perguntar ao eleitor em quem votou para federal e estadual. Estimar diretamente
a tabela conjunta, com desenho amostral e pesos. É a única verificação real de
co-votação individual. Fora do escopo dos BUs.

### 10.3 MRP / modelos hierárquicos

Com microdados de survey e covariates demográficas, modelar o voto conjunto e
pós-estratificar por urna/local. Exige dados individuais; não disponíveis hoje.

### 10.4 Dados auxiliares

- distribuição conjunta de voto partidário (survey, tracking);
- dados de campanha, endorsements, coalizões;
- experimentos naturais (desistência/endosso de candidato) com
  diferenças-em-diferenças.

Podem apertar limites ou calibrar EI, mas não substituem dados individuais.

---

## 11. Poder estatístico e limitações

### 11.1 ICC e n efetivo

No diagnóstico inicial, a ICC das shares foi ≈ 0,98. Com \(m \approx 10{,}6\)
urnas por local:

\[
DE = 1+(m-1)\rho \approx 10{,}5, \qquad
n_{eff} = \frac{586}{DE} \approx 55.
\]

Portanto, os 586 urnas **não** são 586 observações independentes.

### 11.2 Poder

Com \(G=55\) clusters, o mínimo detectável aproximadamente (80% de poder,
\(\alpha=5\%\), dois lados) é \(|r| \approx 0{,}37\). Para detectar \(r=0{,}2\),
seriam necessários ≈ 190 clusters (vários municípios).

### 11.3 Limitações

- falácia ecológica; voto secreto;
- um município, \(G=55\); generalização fraca;
- confundimento por território, partido, coattail, comparecimento;
- autocorrelação espacial;
- candidatos com poucos votos geram correlações instáveis;
- nomes com encoding quebrado;
- dados de 1º turno; sem painel ou survey.

---

## 12. Robustez e diagnósticos

Para cada par focado:

1. `r_bruto`, `r_dentro`, `r_bloco`, `r_local`, Spearman local;
2. IC bootstrap por cluster;
3. p-permutação within-local;
4. q-FDR global e focado;
5. benchmark percentil (fed×est, same-party, mesmo decil de votos);
6. leave-one-local-out;
7. split-half por local (metade A/B);
8. limites agregados e por local; `(a+b)/N`;
9. Goodman + flag;
10. sensibilidade a pesos (turnout vs válidos);
11. excluir urnas pequenas e a urna agregada 75-637;
12. sensibilidade a pseudocontagem \(c=0,5\) vs \(1,0\);
13. Moran's I dos resíduos;
14. pares-placebo e controles negativos.

---

## 13. Múltiplas comparações e pré-registro

- Matriz padrão: 41 candidatos → 820 pares.
- Matriz completa: 573 candidatos → ~164 mil pares.
- Sem correção, 5% de 164 mil ≈ 8.200 falsos positivos.
- Estratégia:
  - **p focado** para pares pré-especificados;
  - **q-FDR** para o conjunto todo;
  - **benchmark** para contextualizar;
  - nunca varrer todos os pares e escolher o maior \(r\) sem reportar o FDR.
- O plano deve ser registrado antes de olhar os resultados do modo focado
  (este documento).

---

## 14. Especificação do modo focado

### 14.1 CLI

```powershell
.venv\Scripts\eleitor correlacao --xlsx "In Put\boletim_urna_parauapebas_2026_z75_z106_com_locais.xlsx" `
    --modo focado --pares-arquivo "In Put\pares.txt" `
    --bootstrap 2000 --permutacoes 5000 `
    --benchmark fed-est --fdr ambos --leave-one-local-out `
    --out "In Put" --html "In Put\focado_parauapebas_2026.html"
```

Pares diretos:

```powershell
--pares "Deputado Federal:2200; Deputado Estadual:22100"
```

`--pares` e `--pares-arquivo` podem ser combinados; duplicatas são removidas.
Sem lista, erro claro com o template.

### 14.2 Template `In Put/pares.txt`

```text
# Um par por linha: Cargo:numero ; Cargo:numero
# Deputado Federal:2200 ; Deputado Estadual:22100
# Deputado Federal:1500 ; Deputado Estadual:15112
# Deputado Federal:1321 ; Deputado Estadual:13500
```

### 14.3 Saídas

- `focado_<municipio>_<ano>.csv`: uma linha por par.
- `focado_<municipio>_<ano>_locais.csv`: uma linha por local.
- `focado_<municipio>_<ano>_benchmark.csv`: distribuição de referência.
- `focado_<municipio>_<ano>.html`: scatter local, resíduos, limites, benchmark.
- `In Put/pares.txt`: template.

### 14.4 Campos do CSV principal

`cargo_a, numero_a, nome_a, partido_a, cargo_b, numero_b, nome_b, partido_b,
r_bruto, r_dentro, r_bloco, r_local, spearman_local,
ic_boot_inf, ic_boot_sup, p_perm, p_fisher, q_fdr_global, q_fdr_focado,
benchmark_percentil, benchmark_n, loo_min, loo_mediana, loo_max,
a_votos, b_votos, n_eleitores, limite_inf, limite_sup,
p_b_a_inf, p_b_a_sup, p_a_b_inf, p_a_b_sup, largura_a, largura_b,
flag_covotacao, goodman_b_a, goodman_b_a_inf, goodman_b_a_sup,
goodman_a_b, goodman_a_b_inf, goodman_a_b_sup, goodman_flag`

### 14.5 HTML

- cartões com os totais;
- scatter dos 55 locais (share A × share B), com rótulos;
- scatter within-local dos resíduos;
- barras de limites por local;
- histograma do benchmark com o alvo marcado;
- tabela de métricas;
- caixa de cautelas fixa: “associação ecológica ≠ transferência individual”.

---

## 15. Plano de implementação

### 15.1 Fase 1 — relatório focado

- `services/correlacao.py`:
  - `ler_lista_pares`, `ParFocado`;
  - `analisar_pares_focados`;
  - `bootstrap_par`, `permutacao_par`, `leave_one_local_out`;
  - `limites_por_local`, `benchmark_pares`;
  - `goodman_par` público;
  - serializadores CSV.
- `cli.py`: `--modo focado`, `--pares`, `--pares-arquivo`,
  `--permutacoes`, `--benchmark`, `--fdr`, `--ei`.
- `render/correlacao.html`: seções focadas.
- `tests/test_correlacao.py`: parser, par inexistente, bootstrap reprodutível,
  benchmark, limites por local, HTML escapado.
- `AGENTS.md` / `README.md`: comando e template.

### 15.2 Fase 2 — EI opcional

- `--ei` para os pares escolhidos;
- 2×2 King/bayesiano com priors fracos;
- tomography/posterior;
- aviso explícito de que é modelo, não verificação;
- não instalar `pyei` por padrão; avaliar implementação própria ou dependência
  opcional.

### 15.3 Fase 3 — painel 2022→2026

- carregar BUs de 2022;
- alinhar seções;
- calcular diferenças e regressão com FE de local;
- plano separado.

---

## 16. Critérios de aceite

1. `pytest` passa.
2. O par Hipólito × Caveira reproduz o baseline:
   - `r_bruto ≈ 0,763`;
   - `r_dentro ≈ 0,379`;
   - bootstrap ≈ `[0,31; 0,45]`;
   - `r_bloco ≈ 0,344`;
   - `q_dentro ≈ 0,087`;
   - `q_bloco ≈ 0,330`;
   - `r_local ≈ 0,894`;
   - leave-one-local-out ≈ `0,366–0,392`;
   - `P(Hipólito|Caveira) = 0–100%`;
   - `max (a+b)/N ≈ 0,43`;
   - Goodman `P(Hipólito|Caveira) ≈ 1,085` (flag).
3. O HTML abre standalone, sem servidor e sem CDN.
4. O modo padrão (matriz) continua funcionando e não muda de comportamento.
5. Nenhuma conclusão causal/individual é emitida sem qualificação explícita.

---

## 17. Referências

### 17.1 Inferência ecológica e falácia ecológica

- Robinson, W. S. (1950). Ecological correlations and the behavior of
  individuals. *American Sociological Review*, 15(3), 351–357.
- Goodman, L. A. (1953). Ecological regressions and behavior of individuals.
  *American Sociological Review*, 18(6), 663–664.
- Freedman, D. A., Klein, S. P., Sacks, J., Smyth, M. J., & Everett, C. G.
  (1991). Ecological regression and voting rights. *Evaluation Review*, 15(6),
  673–711.
- King, G. (1997). *A Solution to the Ecological Inference Problem*.
  Princeton University Press.
- King, G., Rosen, O., & Tanner, M. A. (Eds.) (2004). *Ecological Inference:
  New Methodological Strategies*. Cambridge University Press.
- Greiner, D. J., & Quinn, K. M. (2009). R×C ecological inference: bounds,
  correlations, flexibility and transparency of assumptions. *Journal of the
  Royal Statistical Society: Series A*, 172(1), 67–81.
- Tam Cho, W. K., & Gaines, B. J. (2004). The limits of ecological inference:
  the case of split-ticket voting. *American Journal of Political Science*,
  48(1), 152–171.
- Burden, B. C., & Kimball, D. C. (1998). A new approach to the study of
  ticket splitting. *American Political Science Review*, 92(3), 533–544.

### 17.2 Dados composicionais

- Aitchison, J. (1986). *The Statistical Analysis of Compositional Data*.
  Chapman & Hall.
- Pawlowsky-Glahn, V., & Buccianti, A. (Eds.) (2011). *Compositional Data
  Analysis: Theory and Applications*. Wiley.

### 17.3 Inferência, bootstrap e múltiplas comparações

- Efron, B., & Tibshirani, R. J. (1993). *An Introduction to the Bootstrap*.
  Chapman & Hall.
- Cameron, A. C., Gelbach, J. B., & Miller, D. L. (2008). Bootstrap-based
  improvements for inference with clustered errors. *Review of Economics and
  Statistics*, 90(3), 414–427.
- Benjamini, Y., & Hochberg, Y. (1995). Controlling the false discovery rate:
  a practical and powerful approach to multiple testing. *Journal of the Royal
  Statistical Society: Series B*, 57(1), 289–300.
- Conley, T. G. (1999). GMM estimation with cross sectional dependence.
  *Journal of Econometrics*, 92(1), 1–45.
- Moran, P. A. P. (1950). Notes on continuous stochastic phenomena.
  *Biometrika*, 37(1/2), 17–23.

### 17.4 Modelos hierárquicos e dados individuais

- Gelman, A., & Hill, J. (2007). *Data Analysis Using Regression and
  Multilevel/Hierarchical Models*. Cambridge University Press.
- King, G., & Roberts, M. (2012). *ei: A Program for Ecological Inference*.
  R package.
- Knudson, K. C., Schoenbach, G., & Becker, A. (2021). PyEI: A Python package
  for ecological inference. Zenodo. https://github.com/mggg/ecological-inference

### 17.5 Dados eleitorais e boletins de urna

- Tribunal Superior Eleitoral (TSE). Resultados oficiais das Eleições 2026.
  https://resultados.tse.jus.br/oficial
- TSE. Boletim de Urna (BU): especificação e arquivos de urna.
- MIT Election Data and Science Lab (2023). *Precinct-Level Election Results:
  A Primer*.
- Documentação interna do projeto: `AGENTS.md` (URLs, zero-padding, limites de
  requisição, fatos do TSE).

---

## 18. Registro de decisões

- [x] A matriz completa já foi implementada e executada.
- [x] Os limites determinísticos já foram calculados: 628 pares, 0 informativos.
- [x] O baseline Hipólito × Caveira foi medido.
- [x] Implementar o modo focado (fase 1).
- [x] Criar o template `In Put/pares.txt`.
- [ ] Decidir se a fase 2 (EI) entra.
- [ ] Decidir se a fase 3 (painel 2022) entra.

## 19. Implementação da fase 1

Arquivos entregues:

- `src/eleitor/services/correlacao.py`: parser de pares, resolução de candidatos,
  bootstrap por cluster do par, permutação within-local, leave-one-local-out,
  limites por local, benchmark e serializadores CSV.
- `src/eleitor/cli.py`: `--modo focado`, `--pares`, `--pares-arquivo`,
  `--permutacoes`, `--benchmark`, `--fdr`, `--sem-loo`.
- `src/eleitor/render/focado.py` + `src/eleitor/render/focado.html`: relatório
  estático com SVG (dispersão local, resíduos within-local, histograma de
  benchmark) e tabela de limites por local.
- `tests/test_correlacao.py`: 19 testes do módulo, incluindo o baseline real.
- `In Put/pares.txt`: template do espaço aberto.
- `In Put/focado_parauapebas_2026.csv`, `_locais.csv`, `_benchmark.csv` e `.html`:
  execução de demonstração com Hipólito × Caveira.

Comando executado:

```powershell
.venv\Scripts\eleitor correlacao --xlsx "In Put\boletim_urna_parauapebas_2026_z75_z106_com_locais.xlsx" `
    --modo focado --pares "Deputado Federal:2200; Deputado Estadual:22100" `
    --bootstrap 2000 --permutacoes 5000 --out "In Put" `
    --html "In Put\focado_parauapebas_2026.html"
```

Resultado (Hipólito × Caveira):

- `r_bruto = 0,763`; `r_dentro = 0,379`; IC bootstrap `[0,31; 0,45]`;
  `r_bloco = 0,344`; `r_local = 0,894`; Spearman `0,762`.
- `p_perm = 0,0002`; `q_focado = 0,0002`; `q_global = 0,087`.
- Benchmark: 97º percentil de 194 pares fed×est.
- Leave-one-local-out: `0,366–0,392`.
- `P(Hipólito|Caveira) = 0–100%`; `P(Caveira|Hipólito) = 0–62,6%`;
  flag `indeterminado`; nenhum local com `(a+b)/N ≥ 100%`.
- Goodman `P(Hipólito|Caveira) = 1,085` (fora de [0,1]).

**Próximo passo:** decidir entre fase 2 (EI, opcional e não recomendada como prova)
e fase 3 (painel 2022→2026), ou apenas usar o espaço aberto `In Put/pares.txt`.
