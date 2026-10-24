# Mapa eleitoral — comparar candidatos (novo)

Arquivo do mapa: `mapa_eleitoral_parauapebas_2026.html`

Para abrir, dê **dois cliques** em `abrir_mapa_eleitoral.bat`. Aparece uma janela preta
escrita **“Servidor do mapa eleitoral - NAO FECHE”** e o navegador abre sozinho em
`http://127.0.0.1:8766/...`. A biblioteca do mapa (Leaflet) já vem **embutida no HTML**;
só as imagens do mapa base precisam de internet. Feche a janela preta para desligar o
servidor.

## Se aparecer erro 403 ou o mapa ficar sem ruas

O mapa abre com **fundo offline embutido** (mosaico do OpenStreetMap dentro do próprio
HTML), então não depende de internet para mostrar as ruas. O seletor **Mapa base** tem:

- **Mapa offline (embutido)** — padrão; ruas do OSM, sem requisições externas;
- **Ruas (Esri)** — ruas online (funciona na sua rede, como o satélite);
- **Satélite (Esri)** — imagem de satélite;
- **Sem mapa base** — só os círculos e os dados.

O **CARTO foi removido**: desde 25/09/2026 os tiles raster dele exigem chave e, sem
chave, mostram a marca d'água “API KEY REQUIRED”. O **OpenStreetMap online** também
foi removido do seletor porque a sua rede o bloqueia; o OSM continua no fundo embutido.

Se aparecer o aviso “As imagens do mapa não carregaram”, troque de base ou use o modo
offline. A biblioteca Leaflet **não** depende de CDN (unpkg), então um bloqueio ao
unpkg não afeta o mapa.

## Mapa publicado

Versão online: `https://angelojordy-svg.github.io/eleitor-2026/mapa/parauapebas/`

Para atualizar o site depois de mudar a planilha, dê dois cliques em
`publicar-mapa.bat` (na raiz do projeto). Ele regenera o fundo offline, o HTML,
os KML/CSV e publica na branch `gh-pages`.

## O que este mapa mostra

- Os **55 locais de votação** de Parauapebas (zonas 75 e 106) em um mapa de ruas real.
- **1 círculo = 1 local de votação**; o tamanho representa os eleitores aptos.
- Os votos das urnas do mesmo local são somados no círculo. Para ver as urnas/seções
  individuais, **clique no círculo**: abre um painel com a lista das urnas do local.
- Todos os cargos do 1º turno: Presidente, Governador, Senador, Deputado Federal e
  Deputado Estadual.

## Como comparar candidatos

1. Escolha o **cargo** no topo do painel.
2. Escolha os candidatos **A** e **B** (ou clique em A/B no ranking). O botão ⇄ troca os dois.
3. Escolha o modo:
   - **Vencedor** — cor do partido de quem venceu o local; quanto mais forte, maior a margem.
   - **Diferença** — escala de cores de B (uma ponta) a A (outra), neutro no empate.
   - **Lado a lado** — dois mapas sincronizados, um para cada candidato.
4. Opções: dimensionar o círculo pelo total de votos e mostrar rótulos.
5. **Ver tabela** lista os 55 locais com os votos de A e B, útil para conferência.

A comparação usa os **votos nominais** do local. Votos de legenda (partido) ficam fora
do confronto entre candidatos, mas entram no total de votos válidos usado no percentual.

## Regenerar o mapa

Depois de atualizar a planilha:

```powershell
.venv\Scripts\eleitor mapa-urnas --xlsx "In Put\boletim_urna_parauapebas_2026_z75_z106_com_locais.xlsx"
```

O comando gera de uma vez:
- o HTML com o fundo offline embutido;
- o fundo offline em cache (`%LOCALAPPDATA%\eleitor\fundo`);
- os KML/CSV do Google em `In Put\google`.

Para conferir os totais contra a aba **Resumo**, o comando imprime
“Conferência de totais: OK” quando tudo bate. Use `--sem-fundo-offline` para pular o
mosaico, `--refazer-fundo` para baixá-lo de novo e `--google-dir` para mudar a pasta
dos KML/CSV.

## Abrir no Google Earth e no Google Maps

Os arquivos ficam na pasta `google/`:

- `mapa_eleitoral_parauapebas_2026_todos.kml` — Google Earth, com uma pasta por cargo.
  Só **Governador** começa visível; marque/desmarque as outras pastas no painel.
- `mapa_eleitoral_parauapebas_2026_<cargo>.kml` — um cargo, sem pastas.
- `mapa_eleitoral_parauapebas_2026_<cargo>_my_maps.csv` — para o Google My Maps.

### Google Earth

1. Dê dois cliques no `.kml` (ou abra no Google Earth: **Arquivo → Abrir**).
2. Clique em um pino para ver o balão: ficha do local, A × B, top 5 e as urnas.
3. O tamanho do pino representa os eleitores aptos (ou os votos, se gerado assim).
4. A comparação é **estática**: para trocar A/B, regenere o arquivo.

### Google My Maps

1. Acesse `https://mymaps.google.com` e crie um mapa.
2. **Importar** → envie o CSV `..._<cargo>_my_maps.csv`.
3. Escolha **Latitude** e **Longitude** como colunas de localização.
4. Estilize por **Faixa** (`A forte`, `A`, `Empate`, `B`, `B forte`) ou por **Vencedor**.
5. Também é possível importar o KML plano do cargo; se o My Maps ignorar estilos ou
   balões, use o CSV, que é o caminho mais confiável.

Limites do My Maps: 2.000 linhas por camada, 10 camadas e 5 MB para KML. Os arquivos
deste município ficam bem abaixo disso.

### Regerar os arquivos Google

```powershell
.venv\Scripts\eleitor mapa-google --xlsx "In Put\boletim_urna_parauapebas_2026_z75_z106_com_locais.xlsx"
```

Para um confronto específico:

```powershell
.venv\Scripts\eleitor mapa-google --xlsx "In Put\boletim_urna_parauapebas_2026_z75_z106_com_locais.xlsx" `
    --cargo governador --a 20 --b 15 --modo vencedor --tamanho aptos
```

`--a`/`--b` são os **números** dos candidatos e exigem `--cargo`. Sem eles, o arquivo
usa o 1º e o 2º colocados do cargo.

---

# Como abrir o mapa de locais de votação (material anterior)

> Observação: os arquivos `mapa_locais_votacao_parauapebas_2026.html`, o CSV, o KML
> e o `abrir_mapa.bat` citados abaixo não estão presentes nesta pasta. O mapa novo
> é o do topo deste arquivo (`mapa_eleitoral_parauapebas_2026.html`), gerado a partir
> da planilha.

Arquivo do mapa: `mapa_locais_votacao_parauapebas_2026.html`

Ele mostra os **55 locais de votação** de Parauapebas (zonas 75 e 106), com endereço,
seções, eleitores aptos, comparecimento e abstenções. O tamanho do círculo representa
os eleitores aptos.

O mapa usa **Leaflet** (biblioteca de mapas) e **OpenStreetMap** (imagens do mapa).
Por isso, ele precisa de internet e deve ser aberto em um navegador de verdade
(Chrome, Edge ou Firefox).

---

## Jeito mais fácil no Windows

1. Dê **dois cliques** em `abrir_mapa.bat`.
2. Vai abrir uma janela preta escrito **“Servidor do mapa - NAO FECHE”**.
3. O navegador abre sozinho no endereço `http://127.0.0.1:8765/...`.
4. Use o mapa normalmente.
5. Quando terminar, feche a janela preta para desligar o servidor.

Se o Windows perguntar se o Python pode acessar a rede, pode permitir apenas
**rede privada**. O servidor é local, no seu próprio computador.

---

## Jeito manual (se o .bat não funcionar)

Abra o **PowerShell** na pasta do arquivo e rode:

```powershell
python -m http.server 8765 --bind 127.0.0.1
```

Depois abra no navegador:

```text
http://127.0.0.1:8765/mapa_locais_votacao_parauapebas_2026.html
```

Para parar o servidor, volte ao PowerShell e aperte `Ctrl+C`.

---

## Por que não abrir com dois cliques direto no HTML?

Em muitos computadores até funciona, mas alguns navegadores bloqueiam scripts ou
recursos externos quando o arquivo é aberto como `file://` (arquivo local). O servidor
local evita esse bloqueio e é o jeito mais confiável.

Se você abriu o arquivo dentro do visualizador do OpenWork ou de outro app, o preview
pode bloquear o Leaflet/OpenStreetMap. Nesse caso, abra no navegador pelo `.bat`.

---

## Se a página abrir, mas o mapa ficar em branco ou cinza

1. Confirme que você tem internet.
2. Teste estes dois endereços no navegador:
   - `https://unpkg.com/leaflet@1.9.4/dist/leaflet.js`
   - `https://tile.openstreetmap.org/0/0/0.png`
3. Se os dois não abrirem, sua rede/firewall está bloqueando o CDN ou o OpenStreetMap.
   Nesse caso, use a alternativa do Google My Maps (abaixo) ou abra em outra rede.
4. Aperte `F12` → aba **Console** e veja se aparece erro como:
   - `L is not defined` → o Leaflet não carregou (CDN bloqueado).
   - `ERR_BLOCKED_BY_CLIENT` ou `net::ERR...` → rede/bloqueador.
5. O mapa abre no centro urbano. Para ver os locais rurais, clique em **“Ver todos”**.

---

## Se o arquivo abrir no Bloco de Notas, Excel ou outro programa

O Windows pode estar com outro programa como padrão para `.html`.

- Clique com o botão direito no arquivo → **Abrir com** → **Chrome** ou **Edge**.
- Ou arraste o arquivo para dentro de uma janela do navegador.
- Confira se o nome termina mesmo em `.html` (e não `.html.txt`).

---

## Alternativa sem HTML: Google My Maps ou Google Earth

Essa é a opção mais simples se você não quiser lidar com servidor.

### Google My Maps

1. Acesse `https://mymaps.google.com` com sua conta Google.
2. Crie um mapa novo.
3. Clique em **Importar**.
4. Envie o arquivo `locais_votacao_parauapebas_2026_google_my_maps.csv`.
5. Na importação, escolha as colunas **Latitude** e **Longitude**.
6. Dê um nome ao conjunto de pontos e finalize.

O CSV já tem nome do local, endereço, seções, aptos, comparecimento e abstenções.

### Google Earth

Abra o arquivo `locais_votacao_parauapebas_2026.kml` no Google Earth. Ele já traz
os 55 pontos com as mesmas informações.

---

## Se o problema for o mapa do site eleitor-2026

O mapa do site é outro. O site publicado é:

```text
https://angelojordy-svg.github.io/eleitor-2026/
```

Abra essa URL diretamente no navegador. Não abra o `template.html` do repositório
local: ele é só o modelo e não tem os dados gerados (`DADOS`), por isso não funciona
sozinho.

Se o mapa do site não abrir, tente:

1. Atualizar a página com `Ctrl+F5`.
2. Testar em outra aba anônima.
3. Testar em outro navegador (Chrome/Edge/Firefox).
4. Apertar `F12` → **Console** e ver o erro.
5. Testar em outra rede (o mapa pode depender de recursos externos).

---

## Observação sobre o conteúdo do mapa

Este mapa mostra **locais de votação**, não o resultado por candidato. Os votos por
urna estão na planilha:

- `boletim_urna_parauapebas_2026_z75_z106_com_locais.xlsx`

Se você quiser, o mapa pode ser adaptado para:

- colorir cada local pelo partido vencedor de um cargo;
- mostrar os votos de Presidente, Governador, Senador, Deputado Federal ou Estadual;
- mostrar apenas uma zona;
- gerar uma imagem/PDF do mapa.
