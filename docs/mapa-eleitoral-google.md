# Mapa eleitoral por local — detalhamento (OSM + Google Earth/My Maps)

Este documento descreve as duas fases do mapa eleitoral de Parauapebas/PA:
correção do mapa base (Fase 1) e exportação para Google Earth/Google My Maps
(Fase 2). Ele é a referência de implementação e de aceite.

## 1. Contexto e decisões

- A planilha de BUs já contém 55 locais, 586 urnas e votos por urna/cargo/votável.
- O HTML interativo (`mapa_eleitoral_parauapebas_2026.html`) usa Leaflet embutido.
- **CARTO não será mais usado**: desde 25/09/2026 os tiles raster do CARTO exigem
  chave e, sem ela, retornam HTTP 200 com a marca d'água “API KEY REQUIRED”
  (tile fixo de ~2 KB). O detector de `tileerror` não pega esse caso.
- **OSM** e **Esri World Imagery** funcionam sem chave e serão as bases do HTML.
- Google Earth/Maps não executam JavaScript: a comparação A×B será “congelada”
  nos arquivos exportados. Para trocar candidatos, regenera-se o arquivo.
- Google Maps (site/app comum) não importa KML. O caminho é **Google My Maps**
  (`mymaps.google.com`), que importa CSV/KML. Para My Maps, o CSV é o formato
  mais confiável; o KML pode perder pastas e balões HTML.

## 2. Fase 1 — mapa base do HTML

### 2.1 Mudanças

Arquivo: `src/eleitor/render/mapa_urnas.html`.

- `estado.base` passa de `"carto"` para `"osm"`.
- Remover `carto` do objeto `BASES` e do `<select id="sel-base">`.
- Opções restantes, nesta ordem:
  1. `osm` — Ruas (OpenStreetMap), padrão;
  2. `satelite` — Satélite (Esri);
  3. `nenhum` — Sem mapa base (offline).
- Hash antigo (`base=carto`) ou inválido cai no padrão OSM.
- O aviso de `tileerror` continua: após 4 erros em 4 s, mostra o banner
  “As imagens do mapa não carregaram” e sugere trocar a base.
- A URL do CARTO não pode aparecer no HTML gerado.

### 2.2 Validação

- `pytest` completo.
- Teste do HTML: sem `basemaps.cartocdn.com`; com `tile.openstreetmap.org`.
- Chrome headless:
  - 55 círculos;
  - requisições de tiles ao OSM;
  - nenhuma requisição ao CARTO;
  - Esri e “Sem mapa base” funcionando;
  - 403 simulado no OSM mostra o banner.

## 3. Fase 2 — exportação Google

### 3.1 Arquivos gerados

Pasta padrão: `In Put/google/` (ou `--out-dir`).

Para todos os cargos (sem `--cargo`):

- `mapa_eleitoral_parauapebas_2026_todos.kml` — Google Earth, com uma pasta por
  cargo (Presidente, Governador, Senador, Deputado Federal, Deputado Estadual).
  Cada pasta usa o top 2 do próprio cargo. Apenas **Governador** começa visível;
  as demais ficam desmarcadas para não sobrepor os pinos.
- `mapa_eleitoral_parauapebas_2026_<cargo>.kml` — um por cargo, **sem pastas**
  (placemarks diretos no Document), para Google Earth e importação no My Maps.
- `mapa_eleitoral_parauapebas_2026_<cargo>_my_maps.csv` — um por cargo, para
  importação no Google My Maps.

Com `--cargo <cargo>`:

- gera apenas o KML plano e o CSV daquele cargo;
- não gera o KML combinado.

`<cargo>` é o slug: `presidente`, `governador`, `senador`,
`deputado-federal`, `deputado-estadual`.

### 3.2 CLI

Novo subcomando:

```powershell
eleitor mapa-google --xlsx "In Put\boletim_urna_parauapebas_2026_z75_z106_com_locais.xlsx" `
  [--out-dir "In Put\google"] `
  [--cargo governador] `
  [--a 20] [--b 15] `
  [--modo vencedor|diferenca] `
  [--tamanho aptos|votos]
```

Regras:

- `--xlsx` obrigatório.
- `--out-dir` padrão: pasta `google` ao lado da planilha.
- Sem `--cargo`: todos os cargos.
- `--a`/`--b` só podem ser usados com `--cargo`; são **números** de candidato.
- Sem `--a`: candidato A = 1º colocado do cargo.
- Sem `--b`: candidato B = 2º colocado (ou o primeiro diferente de A).
- Se o número não existir no cargo, erro claro listando os candidatos do cargo.
- `--modo` padrão `vencedor`; `diferenca` usa escala divergente.
- `--tamanho` padrão `aptos`; `votos` usa `max(votos A, votos B)` no local.
- O comando lê a planilha, roda `conferir_planilha()` e avisa divergências.
- Ao final, imprime os arquivos gerados e instruções curtas.

### 3.3 KML — Google Earth

#### Estrutura

```xml
<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Mapa eleitoral — Parauapebas/PA — 2026</name>
    <description><![CDATA[...legenda e fonte...]]></description>
    <LookAt>...</LookAt>
    <Folder>...</Folder>   <!-- só no KML combinado -->
  </Document>
</kml>
```

- `LookAt`: centro do município e `range` aproximado (diagonal do bounding box
  × 1,4, mínimo 2 km).
- KML combinado: `Folder` por cargo, com `visibility` 1 só em Governador.
- KML por cargo: sem `Folder`; `Placemark` direto no `Document`.
- Cada `Placemark`:
  - `name`: nome do local;
  - `Snippet`: `A 55,2% × B 30,1% · 6.368 aptos`;
  - `description`: HTML do balão (CDATA);
  - `ExtendedData`: campos para importação no My Maps;
  - `Style/IconStyle`: cor, escala e ícone;
  - `Style/LabelStyle`: escala 0 (sem rótulos);
  - `Point/coordinates`: `longitude,latitude,0`.

#### Ícone e cores

- Ícone: `https://maps.google.com/mapfiles/kml/shapes/placemark_circle.png`
  (círculo do Google, tintável).
- Escala: `0.8 + 1.2 * sqrt(valor / máximo)`, em que `valor` é aptos do local
  (padrão) ou `max(votos A, votos B)`.
- Cor KML: `aabbggrr` (alpha, azul, verde, vermelho), derivada do hex do partido.
- Modo **Vencedor**:
  - cor = partido do vencedor entre A e B;
  - alpha = `0x66 + 0x99 * min(1, |margem| / escala)`;
  - `escala = clamp(maior margem do cargo, 12, 40)` p.p.
- Modo **Diferença**:
  - cor = mistura do neutro `#cbd5e1` com a cor do lado vencedor;
  - `t = (|margem| / escala)^0.65`;
  - alpha fixo `0xee`;
  - empate usa o neutro.
- A/B são sempre do mesmo cargo.

#### Balão HTML

Conteúdo, em HTML/CSS inline (Google Earth WebKit):

- zona, código e cargo;
- nome, endereço, bairro e CEP;
- aptos, comparecimento (%), abstenções e número de urnas;
- A × B: nome, partido, votos, %, barras e margem em p.p.;
- top 5 candidatos do local (nome, partido, votos, %);
- tabela das urnas/seções do local (seção, urna, aptos, comp., abst.);
- link `https://www.google.com/maps/search/?api=1&query=<lat>,<lon>`;
- nota: “1 pino = 1 local; urnas do mesmo local agregadas”.

Texto sempre escapado; descrição em CDATA. Nada de JavaScript.

#### ExtendedData

Campos: `Zona`, `Codigo`, `Local`, `Bairro`, `Endereco`, `Aptos`,
`Comparecimento`, `Abstencao`, `Cargo`, `CandidatoA`, `PartidoA`, `VotosA`,
`PercentualA`, `CandidatoB`, `PartidoB`, `VotosB`, `PercentualB`, `Vencedor`,
`CandidatoVencedor`, `PartidoVencedor`, `Margem`, `Faixa`, `Urnas`.

### 3.4 CSV — Google My Maps

- Separador vírgula, UTF-8 com BOM (`utf-8-sig`), uma linha por local.
- Cabeçalho:

```text
Latitude,Longitude,Local,Zona,Codigo,Bairro,Endereco,Aptos,Comparecimento,Abstencao,
Cargo,Candidato A,Partido A,Votos A,Percentual A,Candidato B,Partido B,Votos B,
Percentual B,Vencedor,Candidato vencedor,Partido vencedor,Margem (p.p.),Faixa,Urnas,
Link Google Maps
```

- Percentuais e margem com 2 casas decimais e ponto (numérico).
- `Vencedor`: `A`, `B` ou `Empate`.
- `Faixa` para estilização por categoria:
  - `Empate` se `|margem| < 3` p.p.;
  - `A forte` se `margem >= 10`; `A` se `3 <= margem < 10`;
  - `B forte` se `margem <= -10`; `B` se `-10 < margem <= -3`.
- `Urnas`: quantidade de urnas do local.
- `Link Google Maps`: URL do ponto.

### 3.5 Regras de análise

- Percentual no local = `votos do candidato / votos válidos do cargo no local`.
- Votos válidos vêm do payload (soma nominal + legenda por urna).
- Margem = `pct A − pct B` em pontos percentuais.
- Vencedor = A/B/Empate conforme sinal da margem (tolerância 1e-9).
- Totais do município = soma dos totais dos candidatos no payload.
- `maxAptos` = maior aptos entre os 55 locais.
- Empates contam para os dois lados? Não: contam em `empates`.

### 3.6 Código

Novo módulo `src/eleitor/services/exportar_google.py`:

- `ExportError` — erro de cargo/candidato/arquivo.
- `comparar(payload, cargo, a=None, b=None) -> Comparacao`.
- `gerar_kml(payload, cargos=None, modo="vencedor", tamanho="aptos",
  a=None, b=None) -> str`.
- `gerar_csv(payload, cargo, a=None, b=None) -> str`.
- `exportar_google(payload, destino, cargo=None, a=None, b=None,
  modo="vencedor", tamanho="aptos") -> list[Path]`.
- Helpers: `cor_partido`, `kml_color`, `mix_hex`, `escala_icone`,
  `_slug`, `_cdata`, `_look_at`, `_descricao_html`, `_faixa`.

`cli.py`:

- `cmd_mapa_google(client, args)`.
- subparser `mapa-google` com as opções da seção 3.2.

Testes:

- `tests/fixtures_planilha.py` — fixture compartilhada com a planilha mínima
  (2 locais, 2 cargos) e gerador de XLSX.
- `tests/test_exportar_google.py`:
  - KML de um cargo: 2 placemarks, sem Folder, XML bem formado, cores válidas,
    ícone correto, descrição com A/B;
  - KML combinado: 2 Folders, 4 placemarks, só Governador visível;
  - CSV: cabeçalho, 2 linhas, `Vencedor` e `Faixa` corretos;
  - `exportar_google`: arquivos esperados em `tmp_path`;
  - candidato inexistente: `ExportError`.
- `tests/fixtures_planilha.py` é usada por `test_exportar_google.py`;
  `test_mapa_urnas.py` mantém a própria fixture local (autocontida) e teve a
  asserção do CARTO removida.

### 3.7 Critérios de aceite

1. `pytest` completo passa.
2. HTML gerado não contém `basemaps.cartocdn.com`.
3. KML gerado é XML bem formado; 55 placemarks no arquivo real; 5 pastas no
   combinado; só Governador visível.
4. Cores KML têm 8 dígitos hex; escala > 0; ícone presente.
5. CSV real tem 55 linhas + cabeçalho, 26 colunas, acentos corretos.
6. Google Earth abre o KML combinado e o de um cargo (validação manual, se
   disponível).
7. Google My Maps importa o CSV e permite estilizar por `Faixa` ou `Vencedor`.
8. Nenhum arquivo temporário fica em `In Put`.

## 4. Fase 3 — fundo offline, ruas Esri e publicação

### 4.1 Diagnóstico

- O HTML já embute o Leaflet; as únicas requisições externas são os tiles do mapa base.
- Na rede do usuário, **OpenStreetMap continua bloqueado**; **Esri (satélite) funciona**.
- O CARTO foi removido (tiles raster exigem chave desde 25/09/2026).
- Publicar no GitHub Pages **não desbloqueia** o OSM. Para garantir o fundo:
  1. embutir um mosaico OSM no HTML (offline);
  2. oferecer **Ruas (Esri)** online, do mesmo host que já funciona.

### 4.2 Ruas Esri (online)

Adicionar ao seletor:

- `offline` — Mapa offline (embutido), padrão;
- `ruas-esri` — `World_Street_Map` do ArcGIS;
- `satelite` — `World_Imagery` do ArcGIS;
- `nenhum` — sem mapa base.

Remover `osm` do seletor e do objeto `BASES` (o OSM continua no fundo offline).
URL: `https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}`.
Teste feito em Parauapebas: HTTP 200, tile JPEG de rua real.

### 4.3 Fundo offline embutido

Novo módulo `src/eleitor/services/fundo_offline.py`:

- Entrada: payload (locais com lat/lon), zooms e raio de detalhe.
- Área total: bounding box de todos os locais, zoom 12 (~60 tiles).
- Detalhe urbano: locais a até 8 km da mediana do centro, bbox + 1 km, zoom 15
  (~72 tiles).
- Baixa tiles do OSM com `httpx`:
  - `User-Agent: Mozilla/5.0 (compatible; eleitor-mapa/0.1; uso local)`;
  - `Accept` de imagem;
  - throttle de 0,1 s, 2 tentativas, timeout 30 s.
- Costura com **Pillow** (`Image.new`, `paste`), converte para RGB e salva JPEG
  (qualidade 85).
- Codifica como `data:image/jpeg;base64,...`.
- Cache em `%LOCALAPPDATA%\eleitor\fundo` (ou `ELEITOR_FUNDO_DIR`):
  - um JPEG + JSON de metadados por camada;
  - chave: município + zoom + bbox + qualidade;
  - TTL 30 dias; `--refazer-fundo` ignora.
- Fallback: se o OSM falhar, tenta `World_Street_Map` do Esri para o mosaico.
- Se ambos falharem, retorna `None`; o HTML usa `ruas-esri` como padrão e avisa.
- Atribuição: “© OpenStreetMap contributors” (ou Esri, no fallback).

Formato do objeto injetado no HTML:

```json
{
  "baixo": {"url": "data:image/jpeg;base64,...", "bounds": [[sul, oeste], [norte, leste]]},
  "alto":  {"url": "data:image/jpeg;base64,...", "bounds": [[sul, oeste], [norte, leste]]},
  "attr": "© OpenStreetMap contributors",
  "zoom": 15
}
```

No Leaflet:

- duas `L.imageOverlay` com `pane: "tilePane"` e `interactive: false`;
- baixa resolução primeiro, alta depois;
- ficam abaixo dos círculos (tilePane z-index 200 < overlayPane 400);
- atribuição no controle do Leaflet.

Tamanho esperado: 2–3 MB de HTML (um arquivo só), com JPEG.

### 4.4 Mudanças no HTML

- `const FUNDO = /*__FUNDO__*/;` (objeto ou `null`).
- `const BASE_PADRAO = FUNDO ? "offline" : "ruas-esri";`.
- Seletor com a opção offline; oculta se `FUNDO` for nulo.
- `aplicarBase("offline")` cria o `L.layerGroup` com as imagens.
- Hash `base=offline`; hash antigo com `base=osm`/`base=carto` cai no padrão.
- Rodapé com links relativos para:
  - `google/mapa_eleitoral_<municipio>_<ano>_todos.kml`;
  - `google/mapa_eleitoral_<municipio>_<ano>_governador_my_maps.csv`.
- Título/cabeçalho: “Mapa eleitoral — Parauapebas/PA”.
- Legenda: “Fundo offline: © OpenStreetMap contributors (embutido)”.

### 4.5 CLI

`eleitor mapa-urnas --xlsx ... [opções]` passa a gerar **HTML + Google de uma vez**:

- `--sem-fundo-offline` — não gera o mosaico; padrão vira `ruas-esri`.
- `--refazer-fundo` — ignora o cache.
- `--zoom-fundo 12` — zoom do município inteiro.
- `--zoom-detalhe 15` — zoom do detalhe urbano.
- `--raio-detalhe 8` — raio em km para o detalhe.
- `--qualidade 85` — qualidade JPEG.
- `--google-dir` — pasta dos KML/CSV (padrão: `google` ao lado do HTML).
- O comando imprime o status do fundo e resume os arquivos Google.

O `eleitor mapa-google` continua disponível para gerar um confronto específico
(`--cargo`, `--a`, `--b`, `--modo`, `--tamanho`).

### 4.6 Publicação no GitHub Pages

Estrutura publicada:

```text
mapa/index.html                       # índice de cidades (Parauapebas)
mapa/parauapebas/index.html           # o mapa
mapa/parauapebas/google/*.kml,*.csv   # arquivos Google
```

URL: `https://angelojordy-svg.github.io/eleitor-2026/mapa/parauapebas/`.

`publicar-mapa.bat`:

1. roda `eleitor mapa-urnas` (fundo offline + HTML + KML/CSV);
2. cria um worktree temporário de `origin/gh-pages` (detached);
3. copia o HTML para `mapa/parauapebas/index.html` e os Google para
   `mapa/parauapebas/google/`;
4. gera/atualiza `mapa/index.html` com o card “Parauapebas/PA”;
5. commita e faz `git push origin HEAD:gh-pages`;
6. remove o worktree e imprime a URL.

O worktree evita mexer nos arquivos não commitados da `main`.

### 4.7 Commit na `main`

Commit único com o trabalho atual de código, testes e docs:

- mapa: `sources/planilha.py`, `services/mapa_urnas.py`,
  `services/exportar_google.py`, `services/fundo_offline.py`,
  `render/mapa_urnas.html`, `render/vendor/leaflet/*`, `render/html.py`;
- CLI e dependências: `cli.py` (mapa + correlação, que já está no working tree),
  `pyproject.toml`;
- testes: `fixtures_planilha.py`, `test_mapa_urnas.py`,
  `test_exportar_google.py`, `test_fundo_offline.py` e os testes de correlação;
- docs: `docs/mapa-eleitoral-google.md`, `docs/plano-analise-focada.md`, `README.md`,
  `AGENTS.md`;
- script `publicar-mapa.bat`.

**Não entram no commit:** `In Put/` gerado e a planilha `.xlsx` (6 MB).
A planilha continua local; a página publicada é autocontida.

### 4.8 Expansão para o Brasil

- O mapa é **por município**, pois a unidade é o local/urna da planilha.
- Brasil no nível de local/urna: inviável como HTML estático (~96 mil locais,
  ~472 mil urnas, GBs de BUs). Exigiria backend/base de dados e bake por cidade.
- Brasil no nível de município (5.571 polígonos): viável e já existe no site
  nacional; pode ganhar comparação A×B por município numa fase futura.
- Arquitetura para várias cidades: `mapa/<cidade>/` + `mapa/index.html`;
  o gargalo é gerar a planilha/BUs de cada município.

### 4.9 Testes e aceite

- `tests/test_fundo_offline.py`:
  - matemática de tiles/bounds Web Mercator;
  - costura com fetcher falso (sem rede);
  - cache e fallback;
  - objeto `FUNDO` com bounds válidos.
- `tests/test_mapa_urnas.py`:
  - HTML com fundo: `const FUNDO` preenchido, opção offline, padrão offline;
  - HTML sem fundo: padrão `ruas-esri`, opção offline oculta;
  - sem OSM/CARTO no seletor.
- Playwright:
  - **bloqueando todo acesso externo**: fundo offline renderiza, 55 círculos,
    popup e gaveta funcionam;
  - Esri Street online: tiles 200, screenshot;
  - URL publicada: fundo visível e links Google respondendo 200.
- `pytest` completo.
- `git status` limpo dos arquivos gerados; `In Put/` permanece fora do commit.

## 5. Limitações e riscos

- Google Earth/Maps não executam JS: a comparação é estática.
- My Maps: 2.000 linhas por camada, 10 camadas, 5 MB para KML; pode ignorar
  pastas, HTML e estilos do KML — por isso o CSV é o caminho recomendado.
- O ícone do KML é hospedado pelo Google; sem internet o pino pode não aparecer
  (a imagem de satélite também não). Um KMZ com ícone embutido fica para uma
  fase futura.
- OSM é adequado para uso local/baixo volume. Publicação com muito tráfego
  pede provedor com chave ou tiles próprios.
- A planilha é a fonte da verdade; se ela mudar, regerar HTML/KML/CSV.

## 6. Ordem de execução

1. Este documento.
2. Fase 1 (OSM) + regenerar HTML + testes.
3. Módulo `exportar_google.py` + CLI `mapa-google`.
4. Fixture/testes.
5. Gerar KML/CSV reais em `In Put/google`.
6. Atualizar LEIA-ME e AGENTS.
7. `pytest` completo, validação estrutural dos arquivos e limpeza.

## 7. Status da implementação

- [x] Fase 1: OSM padrão, CARTO removido, HTML regenerado e validado no Chrome.
- [x] `services/exportar_google.py` + CLI `mapa-google`.
- [x] KML combinado (5 pastas, só Governador visível) e KML/CSV por cargo.
- [x] 89 testes passando (mapa, exportação, fundo offline e correlação).
- [x] Arquivos reais gerados em `In Put/google/`: 5 KMLs por cargo, 1 KML
  combinado e 5 CSVs (55 locais cada).
- [x] Fundo offline embutido validado com todo acesso externo bloqueado.
- [x] Ruas (Esri) validado no Chrome (25 tiles reais).
- [ ] Validação manual no Google Earth/My Maps (depende do aplicativo/conta).
- [ ] KMZ com ícone embutido (fase futura).
- [x] Publicado em https://angelojordy-svg.github.io/eleitor-2026/mapa/parauapebas/ (após o push).
