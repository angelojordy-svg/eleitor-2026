# Eleitor 2026

CLI em Python para acompanhar, em tempo real, os resultados das Eleições 2026 do TSE, com foco em:

- busca por município (somatório oficial) e detalhe por zona eleitoral;
- lista de seções/urnas de um município com status da apuração;
- menu interativo no terminal (rich) e subcomandos.

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
.venv\Scripts\eleitor html --municipio Ananindeua/PA --municipio Parauapebas/PA --out resultado-2026.html
.venv\Scripts\eleitor uf pa --cargo governador --watch 30
.venv\Scripts\eleitor br --cargo presidente --watch 30
.venv\Scripts\eleitor selftest
```

O comando `secao` baixa o boletim de urna (BU, binário ASN.1) e mostra os votos
por candidato naquela urna. As especificações ASN.1 usadas estão em
`src/eleitor/spec/` (documentação pública do TSE, via projeto MIT `doccaz/urnas-br`).

O comando `html` gera um artefato único offline (snapshot estilo site do TSE) com
Brasil, 27 estados e os municípios informados, incluindo navegação por zona e
seção e página de candidato. Flags: `--sem-fotos`, `--sem-secoes`.

O artefato tem o botão **"Atualizar online"** no topo: com internet, busca os
resultados mais recentes direto do TSE (Brasil, estados, municípios e zonas) sem
precisar regerar o arquivo. Os votos por seção/urna vêm do snapshot — para
atualizá-los, rode o comando `html` novamente (ou dê duplo clique em
`atualizar-html.bat`, que regenera `resultado-2026.html` com os dados atuais).

Importante: **F5 não atualiza** (o arquivo contém os dados embutidos). Use o botão
"Atualizar online" ou o `atualizar-html.bat`.

O cache local fica em `%LOCALAPPDATA%\eleitor\cache` (pode ser alterado com `ELEITOR_CACHE_DIR`).
O cliente respeita o limite de 100 req/s do TSE com intervalo mínimo entre requisições e usa ETag/304.

## Testes

```powershell
.venv\Scripts\python -m pytest
```
