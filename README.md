# Eleitor 2026

CLI em Python para acompanhar, em tempo real, os resultados das Eleições 2026 do TSE, com foco em:

- busca por município (somatório oficial) e detalhe por zona eleitoral;
- lista de seções/urnas de um município com status da apuração;
- menu interativo no terminal (rich) e subcomandos.

## Site publicado

Versão web (celular e desktop): **https://angelojordy-svg.github.io/eleitor-2026/**

Publicado via GitHub Pages a partir da branch `gh-pages`. Para atualizar o site com
dados novos (inclusive votos por seção), dê duplo clique em **`publicar.bat`**.
No próprio site, o botão **"Atualizar online"** atualiza os totais na hora (Brasil,
estados, municípios e zonas) sem republicar.

O site tem ainda:
- **Mapa do Brasil**: Governador e Presidente por estado **e por município** (clique no
  estado para abrir o mapa municipal), colorido pelo **partido mais votado** com
  intensidade pelo **tamanho da maioria** (% do líder sobre os votos válidos, escala
  fixa 30% → 70%+), com alternador de **1º/2º turno**. Estados **hachurados** são os que
  vão ao **2º turno** (com a contagem de quantos já elegeram no 1º turno). A paleta tem
  matizes espaçados de propósito, para PL/PSD/PSDB e PP/PODE/MDB não se confundirem.
  Todos os 5.571 municípios vêm embutidos (funciona offline).
- **Apuração mundial**: nova aba `#/mundo` com a votação para presidente **no exterior**
  (186 cidades em 134 países), colorida pelo candidato mais votado e pela força da
  maioria, com abas **1º/2º turno**, balão ao vivo (soma as cidades do país no TSE) e
  tabela pesquisável "Como cada país votou". O Brasil aparece em cinza: este recorte é
  só do exterior. Funciona offline; a geometria Natural Earth vem embutida.
  No **2º turno**, antes das 17h, o mapa usa uma **prévia dos boletins de urna (BU)**
  do pleito 3221, com selo "Preliminar — BU" e cobertura (`N de 1.282 urnas eletrônicas`);
  após a totalização oficial, o próprio build troca para o resultado do TSE.
- **Balão + rótulos de apuração**: passar o mouse (ou tocar, no celular — o primeiro
  toque informa e o segundo abre) mostra líder, votos, % dos válidos, 2º colocado e o
  **% de apuração** (seções totalizadas), com o status ("apuração em andamento",
  "eleito com X%", "vai ao 2º turno"). Há também uma opção para **mostrar o % de
  apuração escrito no mapa**; onde a contagem está em andamento os rótulos aparecem
  sozinhos. Com internet o número é buscado de novo no TSE na hora — e **para de buscar
  quando a apuração daquela área encerra (100%)**. No 1º turno, que já está totalizado,
  isso significa zero requisições.
- **Busca ao vivo**: qualquer município do Brasil (ex.: Niterói, Rio de Janeiro) é
  buscado na hora no TSE (Brasil, estado, município e zonas). Votos por seção/urna
  ficam disponíveis apenas para os municípios embutidos no arquivo.
- **Painel do Congresso**: Câmara (513), Senado (54 novos + 27 antigos de 2022),
  assembleias estaduais e distrital, com gráfico de parlamento (hemiciclo) por
  partido e tabela. Preenche conforme os estados finalizam.

Fontes oficiais (JSON públicos):

- Resultados (EA20): `https://resultados.tse.jus.br/oficial/ele2026/{eleicao}/dados/{abr}/...-u.json`
- Config. de municípios (EA12): `.../6259/config/mun-e006259-cm.json`
- Config. de seções (EA16): `.../arquivo-urna/3220/config/{uf}/{uf}-p003220-cs.json`
- Auxiliar de seção (EA18): `.../arquivo-urna/3220/dados/{uf}/{mun}/{zona}/{secao}/p003220-{uf}-m{mun}-z{zona}-s{secao}-aux.json`

Códigos 2026: Presidente = 6257; Governador/Senador/Dep. Federal/Dep. Estadual/Distrital = 6259; 2º turno = 6258/6260.

## Instalação

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

## Uso

Atalho mais simples (funciona com duplo clique ou no terminal):

```powershell
.\eleitor.bat                # menu interativo
.\eleitor.bat buscar Ananindeua --uf pa --cargo governador
.\eleitor.bat governadores
.\eleitor.bat br --cargo presidente --watch 30
```

Ou diretamente o executável do venv:

```powershell
.venv\Scripts\eleitor                        # menu interativo
.venv\Scripts\eleitor buscar Parauapebas --uf pa --cargo deputado-federal
.venv\Scripts\eleitor buscar Parauapebas --uf pa --cargo governador --zona 75
.venv\Scripts\eleitor secoes Parauapebas --uf pa --zona 75
.venv\Scripts\eleitor secao Parauapebas --uf pa --zona 75 --secao 1 --cargo governador
.venv\Scripts\eleitor votos Parauapebas --uf pa --zona 75 --cargo governador
.venv\Scripts\eleitor governadores                  # todos os estados de uma vez
.venv\Scripts\eleitor html --municipio Parauapebas/PA --out resultado-2026.html
.venv\Scripts\eleitor uf pa --cargo governador --watch 30
.venv\Scripts\eleitor br --cargo presidente --watch 30
.venv\Scripts\eleitor selftest
```

O comando `secao` baixa o boletim de urna (BU, binário ASN.1) e mostra os votos
por candidato naquela urna. As especificações ASN.1 usadas estão em
`src/eleitor/spec/` (documentação pública do TSE, via projeto MIT `doccaz/urnas-br`).

O comando `html` gera um artefato único offline (snapshot estilo site do TSE) com
Brasil, 27 estados, o mapa do Brasil (estados e municípios) e os municípios informados,
incluindo navegação por zona e seção e página de candidato. Flags: `--sem-fotos`,
`--sem-secoes`, `--sem-mapa`, `--sem-mundo`, `--sem-mundo-bu`, `--mapa-municipios br|UF,UF|none`,
`--refazer-mapa`, `--refazer-mundo`, `--refazer-mundo-bu`, `--ritmo` e `--workers`.

O primeiro `html` com o mapa nacional baixa o líder por município dos 5.571 municípios
(~11 mil requisições; ~8 min com `--ritmo 0.04 --workers 10`). O cálculo fica em cache
em `%LOCALAPPDATA%\eleitor\mapa` e é **retomável**: se for interrompido, a próxima
execução continua de onde parou. Para recalcular antes do prazo (ex.: durante o 2º
turno) use `--refazer-mapa`, ou apenas rode:

```powershell
.venv\Scripts\eleitor mapa --cargo governador --turno 1 --ritmo 0.04 --workers 10
```

A geometria do mapa vem do IBGE (malhas) e é baixada uma única vez para
`%LOCALAPPDATA%\eleitor\geo` (pode ser alterada com `ELEITOR_GEO_DIR`); depois o mapa
é gerado offline sem novas consultas. O mapa mundial usa a Natural Earth 50m
(domínio público, `ISO_A2_EH`), projetada em Mollweide e cacheada como
`mundo-50m.json` na mesma pasta. Os votos por país são a soma das cidades do exterior
(`zz{mun:05d}`) e o 2º turno só baixa as 186 cidades quando o agregado `zz` já tem
votos. Antes das 17h, a prévia do 2º turno vem dos BUs do pleito **3221** (seções com
`da`), com cache incremental; `eleitor conferir-mundo` compara essa prévia com a
totalização oficial e mostra a cobertura por país.

O artefato tem o botão **"Atualizar online"** no topo: com internet, busca os
resultados mais recentes direto do TSE (Brasil, estados, municípios e zonas) sem
precisar regerar o arquivo. Os votos por seção/urna vêm do snapshot — para
atualizá-los, rode o comando `html` novamente (ou dê duplo clique em
`atualizar-html.bat`, que regenera `resultado-2026.html` com os dados atuais).

Importante: **F5 não atualiza** (o arquivo contém os dados embutidos). Use o botão
"Atualizar online" ou o `atualizar-html.bat`.

O cache local fica em `%LOCALAPPDATA%\eleitor\cache` (pode ser alterado com `ELEITOR_CACHE_DIR`).
O cliente respeita o limite de 100 req/s do TSE com intervalo mínimo entre requisições e usa ETag/304.

## Mapa por local de votação (planilha de BUs)

A partir da planilha de BUs de um município, o comando `mapa-urnas` gera um HTML
interativo (Leaflet) com **um círculo por local de votação**, comparação A×B,
ranking, tabela e as urnas/seções de cada local. O fundo é um **mosaico OSM
embutido** (funciona sem internet); as opções online são **Ruas (Esri)**,
**Satélite (Esri)** e **Sem mapa base**.

```powershell
.venv\Scripts\eleitor mapa-urnas --xlsx "In Put\boletim_urna_parauapebas_2026_z75_z106_com_locais.xlsx"
```

Saídas: `mapa_eleitoral_<municipio>_<ano>.html`, `google/*.kml` (Google Earth) e
`google/*_my_maps.csv` (Google My Maps). Flags: `--sem-fundo-offline`,
`--refazer-fundo`, `--zoom-fundo`, `--zoom-detalhe`, `--raio-detalhe`, `--qualidade`,
`--google-dir`.

Para um confronto específico no KML/CSV:

```powershell
.venv\Scripts\eleitor mapa-google --xlsx "In Put\boletim_urna_parauapebas_2026_z75_z106_com_locais.xlsx" `
    --cargo governador --a 20 --b 15 --modo diferenca
```

Publicação: `publicar-mapa.bat` gera e publica em
`https://angelojordy-svg.github.io/eleitor-2026/mapa/parauapebas/`. Instruções
detalhadas para Google Earth/My Maps em `In Put\LEIA-ME_MAPA.md`.

## Correlação e co-votação (planilha de BUs)

A partir da planilha de boletins de urna, o comando `correlacao` mede a associação
ecológica entre candidatos (matriz de −1 a 1, por urna e por local) e calcula os
limites determinísticos de co-votação:

```powershell
.venv\Scripts\eleitor correlacao --xlsx "In Put\boletim_urna_parauapebas_2026_z75_z106_com_locais.xlsx" `
    --modo ambos --top 20 --bootstrap 1000 --out "In Put" --html "In Put\correlacao.html"
```

Saídas: `correlacao_<municipio>_<ano>.csv` (pares), `..._matriz.csv` (within-local),
`..._bruto.csv`, `..._bloco.csv`, `covotacao_<municipio>_<ano>.csv` e, com `--html`,
um relatório standalone com heatmap e tabelas. A correlação é **entre lugares**, não
entre pessoas: não prova transferência individual. A co-votação só é reportada como
identificada quando os limites são estreitos; caso contrário o resultado correto é
“não identificado”. O n efetivo é o número de locais (55 em Parauapebas), não o
número de urnas (586).

Para analisar pares específicos, use o modo focado e o “espaço aberto”
`In Put/pares.txt`:

```powershell
.venv\Scripts\eleitor correlacao --xlsx "In Put\boletim_urna_parauapebas_2026_z75_z106_com_locais.xlsx" `
    --modo focado --pares-arquivo "In Put\pares.txt" --bootstrap 2000 --permutacoes 5000 `
    --out "In Put" --html "In Put\focado_parauapebas_2026.html"
```

O arquivo `pares.txt` aceita uma linha por par, no formato
`Cargo:numero ; Cargo:numero` (linhas com `#` são ignoradas). O template vem com
exemplos comentados: descomente/ajuste antes de rodar. Também dá para passar
direto: `--pares "Deputado Federal:2200; Deputado Estadual:22100"`. Saídas:
`focado_<municipio>_<ano>.csv` (métricas), `..._locais.csv` (limites por local),
`..._benchmark.csv` e um HTML com dispersão local, resíduos within-local,
histograma de benchmark e limites por local. O relatório mostra p-permutação focado,
q-FDR global/focado, percentil de benchmark e leave-one-local-out; a co-votação
individual continua limitada pelos mesmos limites determinísticos.

## Testes

```powershell
.venv\Scripts\python -m pytest
```
