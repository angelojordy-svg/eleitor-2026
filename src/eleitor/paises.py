"""Vínculo entre as localidades do exterior (UF ``ZZ``) e os países.

A lista de cidades é a do config do TSE para a eleição presidencial de 2026
(6257). O vínculo cidade -> país foi conferido com a relação pública das 186
localidades e é estático: o bake ignora (com aviso) códigos que não estejam
aqui, para não quebrar quando o TSE mudar a lista.

Formato de ``_DADOS``: ``ISO2|Nome em português|código1,código2,...``.
O Vaticano aparece com 0 eleitores e não está no config de 2026; o serviço
filtra as cidades pelo config antes de baixar qualquer coisa.
"""

from __future__ import annotations

_DADOS = """
AE|Emirados Árabes Unidos|29262
AG|Antígua e Barbuda|99147
AL|Albânia|99139
AM|Armênia|38989
AO|Angola|29998
AR|Argentina|29467,29602,39004,99155,30295
AT|Áustria|30767
AU|Austrália|30562,29491
AZ|Azerbaijão|39128
BA|Bósnia e Herzegovina|30988
BB|Barbados|29424
BD|Bangladesh|29629
BE|Bélgica|29432
BF|Burkina Faso|39284
BG|Bulgária|30546
BH|Barein|99473
BJ|Benin|38920
BO|Bolívia|30473,29904,29572,99236,99210
BS|Bahamas|99180
BW|Botsuana|30669
BZ|Belize|38881
CA|Canadá|30635,39063,30155,30252
CD|República Democrática do Congo|29874
CG|Congo|39187
CH|Suíça|30864,29700
CI|Costa do Marfim|29254
CL|Chile|30481
CM|Camarões|29815
CN|China|30848,30651,30317
CO|Colômbia|29408
CR|Costa Rica|30511
CU|Cuba|29777
CV|Cabo Verde|30368
CY|Chipre|39322
CZ|República Tcheca|30350
DE|Alemanha|29386,30180,29696
DK|Dinamarca|29599
DO|República Dominicana|30490
DZ|Argélia|29300
EC|Equador|30392
EE|Estônia|99317
EG|Egito|29483
ES|Espanha|30066,29351
ET|Etiópia|99325
FI|Finlândia|29785
FR|França|30287,99511
GA|Gabão|29939
GB|Reino Unido|29971,99503
GE|Geórgia|99104
GF|Guiana Francesa|29475,99333
GH|Gana|29270
GN|Guiné|38903
GQ|Guiné Equatorial|39263
GR|Grécia|29335
GT|Guatemala|98000
GW|Guiné-Bissau|29394
GY|Guiana|29718
HK|Hong Kong|29793
HN|Honduras|30600
HR|Croácia|39020
HT|Haiti|30333
HU|Hungria|29459
ID|Indonésia|29840
IE|Irlanda|29661
IL|Israel|30619
IN|Índia|30210,30171
IQ|Iraque|99171
IR|Irã|30597
IT|Itália|30120,30449
JM|Jamaica|99430
JO|Jordânia|29289
JP|Japão|30198,30627,29742
KE|Quênia|30201
KP|Coreia do Norte|99295
KR|Coreia do Sul|30538
KW|Kuwait|29882
KZ|Cazaquistão|39241
LB|Líbano|29360
LC|Santa Lúcia|99384
LK|Sri Lanka|30929
LY|Líbia|30686
MA|Marrocos|30406
ML|Mali|99350
MM|Mianmar|99376
MW|Malaui|99341
MX|México|30104
MY|Malásia|29890
MZ|Moçambique|30090
NA|Namíbia|30821
NG|Nigéria|29912,99198
NI|Nicarágua|30074
NL|Holanda|30457
NO|Noruega|30244
NP|Nepal|29173
NZ|Nova Zelândia|30805
OM|Omã|39102
PA|Panamá|30260
PE|Peru|29947,29823
PH|Filipinas|30082
PK|Paquistão|29831
PL|Polônia|30740
PS|Territórios Palestinos|30414
PT|Portugal|29955,30341,30961
PY|Paraguai|29556,29327,30465,30309,29670,29580
QA|Catar|29653
RO|Romênia|29440
RS|Sérvia|29378
RU|Rússia|30163
SA|Arábia Saudita|30422
SE|Suécia|29688
SG|Singapura|29548
SI|Eslovênia|39160
SK|Eslováquia|39209
SN|Senegal|29610
SR|Suriname|30279
ST|São Tomé e Príncipe|39225
SV|El Salvador|30520
SY|Síria|29637
TG|Togo|29963
TH|Tailândia|29343
TL|Timor-Leste|29645
TN|Tunísia|30708
TR|Turquia|39306,29297
TT|Trinidad e Tobago|30325
TW|Taiwan|30570
TZ|Tanzânia|38962
UA|Ucrânia|29858
US|Estados Unidos|29416,30112,30228,99490,29980,30783,29807,39080,30503,29513,30902
UY|Uruguai|30147,29319,30430,29521,99244
VA|Vaticano|99252
VE|Venezuela|29505,29564,99279
VN|Vietnã|29750
ZA|África do Sul|30376,29530
ZM|Zâmbia|99287
ZW|Zimbábue|29769
"""

PAISES: dict[str, dict[str, object]] = {}
for _linha in _DADOS.strip().splitlines():
    _iso, _nome, _cidades = _linha.split("|")
    PAISES[_iso] = {
        "nome": _nome,
        "cidades": [c for c in _cidades.split(",") if c],
    }

CIDADE_PAIS: dict[str, str] = {
    cidade: iso
    for iso, info in PAISES.items()
    for cidade in info["cidades"]  # type: ignore[union-attr]
}
