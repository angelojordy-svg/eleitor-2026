BASE_URL = "https://resultados.tse.jus.br/oficial"
CICLO = "ele2026"
PLEITO = 3220

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

TTL_LIVE = 10.0
TTL_CONFIG = 300.0
TTL_SECOES = 60.0
TTL_AUX = 120.0
