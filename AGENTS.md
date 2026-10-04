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
.venv\Scripts\eleitor selftest                     # smoke test com a API real
```

## Mapa do código
- `config.py` — códigos de 2026, cargos, TTLs (fonte de verdade).
- `http.py` — `CachedClient`: cache em disco com ETag/304, throttle de 0,15s, `get_json`/`get_bytes`/`get_urls`.
- `sources/resultados.py` — builders de URL + parsers EA12/EA16/EA20.
- `sources/bu.py` — parser do boletim de urna (ASN.1 BER, specs em `spec/`, tenta v2 depois v1).
- `sources/urna.py` — nomes/URLs de arquivos de urna (aux -> hash -> BU).
- `services/snapshot.py` — coleta dados para o HTML offline (Brasil, estados, municípios, seções, fotos).
- `render/` — `html.py` + `template.html` (artefato único, navegação por hash, página de candidato,
  botão "Atualizar online" que busca EA20 do TSE via fetch/CORS quando há internet).
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
- CSVs do TSE (fase candidatos/bens, ainda não implementada): ISO-8859-1, separador `;`.

## Estado atual
Implementado: resultados ao vivo (BR/UF/município/zona), seções com status via EA18, votos por seção via BU.
Pendente: módulo de candidatos/bens (CSV `consulta_cand_2026.zip`/`bem_candidato_2026.zip`), finanças,
dashboard web. Dados de produção podem ficar zerados até a totalização avançar; use `selftest`.
