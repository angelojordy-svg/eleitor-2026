BASE_URL = "https://resultados.tse.jus.br/oficial"
CICLO = "ele2026"
PLEITO = 3220
PLEITO_SEGUNDO = 3221

ELEICAO_FEDERAL = 6257
ELEICAO_ESTADUAL = 6259
ELEICAO_DISTRITAL = 6261
ELEICAO_CONFIG_MUNICIPIOS = 6259

SEGUNDO_TURNO = {6257: 6258, 6259: 6260}

CARGO_NOMES = {
    1: "Presidente",
    3: "Governador",
    5: "Senador",
    6: "Deputado Federal",
    7: "Deputado Estadual",
    8: "Deputado Distrital",
    25: "Conselheiro Distrital",
}

CARGO_ELEICAO = {
    1: ELEICAO_FEDERAL,
    3: ELEICAO_ESTADUAL,
    5: ELEICAO_ESTADUAL,
    6: ELEICAO_ESTADUAL,
    7: ELEICAO_ESTADUAL,
    8: ELEICAO_ESTADUAL,
    25: ELEICAO_DISTRITAL,
}

CARGO_POR_NOME = {nome.lower(): codigo for codigo, nome in CARGO_NOMES.items()}

UF_SIGLAS = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG",
    "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR",
    "RS", "SC", "SE", "SP", "TO", "ZZ",
]

UF_NOMES = {
    "AC": "Acre",
    "AL": "Alagoas",
    "AM": "Amazonas",
    "AP": "Amapá",
    "BA": "Bahia",
    "CE": "Ceará",
    "DF": "Distrito Federal",
    "ES": "Espírito Santo",
    "GO": "Goiás",
    "MA": "Maranhão",
    "MG": "Minas Gerais",
    "MS": "Mato Grosso do Sul",
    "MT": "Mato Grosso",
    "PA": "Pará",
    "PB": "Paraíba",
    "PE": "Pernambuco",
    "PI": "Piauí",
    "PR": "Paraná",
    "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte",
    "RO": "Rondônia",
    "RR": "Roraima",
    "RS": "Rio Grande do Sul",
    "SC": "Santa Catarina",
    "SE": "Sergipe",
    "SP": "São Paulo",
    "TO": "Tocantins",
    "ZZ": "Exterior",
}

# Código IBGE da UF (usado nas malhas do IBGE) -> sigla.
IBGE_UF_CODIGO = {
    "11": "RO",
    "12": "AC",
    "13": "AM",
    "14": "RR",
    "15": "PA",
    "16": "AP",
    "17": "TO",
    "21": "MA",
    "22": "PI",
    "23": "CE",
    "24": "RN",
    "25": "PB",
    "26": "PE",
    "27": "AL",
    "28": "SE",
    "29": "BA",
    "31": "MG",
    "32": "ES",
    "33": "RJ",
    "35": "SP",
    "41": "PR",
    "42": "SC",
    "43": "RS",
    "50": "MS",
    "51": "MT",
    "52": "GO",
    "53": "DF",
}

# Cargos majoritários (um vencedor por recorte) que fazem sentido no mapa.
CARGOS_MAPA = (1, 3)

# Faixa de força da maioria usada no degradê do mapa: 30% -> tom claro,
# 70% ou mais -> tom cheio do partido. Fixa para o mapa continuar
# comparável enquanto a apuração do 2º turno avança.
MAPA_ESCALA = (30.0, 70.0)
MAPA_LARGURA = 1000
MAPA_ALTURA = 1000

TTL_LIVE = 10.0
TTL_CONFIG = 300.0
TTL_SECOES = 60.0
TTL_AUX = 120.0
# Bake do líder por município: 1º turno já é definitivo (reusa por 24h),
# 2º turno é ao vivo (revalida sempre).
TTL_MAPA_RES = 86400.0
TTL_MAPA_RES_2T = 60.0
