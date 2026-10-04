from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import asn1tools

SPEC_DIR = Path(__file__).resolve().parent.parent / "spec"

CARGO_ASN1 = {
    "presidente": 1,
    "vicePresidente": 2,
    "governador": 3,
    "viceGovernador": 4,
    "senador": 5,
    "deputadoFederal": 6,
    "deputadoEstadual": 7,
    "deputadoDistrital": 8,
    "primeiroSuplenteSenador": 9,
    "segundoSuplenteSenador": 10,
    "prefeito": 11,
    "vicePrefeito": 12,
    "vereador": 13,
}


class BUInvalido(RuntimeError):
    pass


@lru_cache(maxsize=2)
def _conversor(versao: str) -> Any:
    spec = SPEC_DIR / f"bu_{versao}.asn1"
    return asn1tools.compile_files([str(spec)], codec="ber")


def _destacar_choice(valor: Any) -> Any:
    if isinstance(valor, tuple) and len(valor) == 2:
        return valor[1]
    return valor


def _codigo_cargo(valor: Any) -> int | None:
    nome = _destacar_choice(valor)
    if isinstance(nome, str):
        if nome in CARGO_ASN1:
            return CARGO_ASN1[nome]
        if nome.isdigit():
            return int(nome)
    if isinstance(nome, int):
        return nome
    return None


def _secao_do_bu(bu: dict[str, Any], env: dict[str, Any]) -> tuple[int, int, int]:
    sec = bu.get("identificacaoSecao")
    if sec is None:
        sec = env.get("identificacao")
    sec = _destacar_choice(sec)
    if not isinstance(sec, dict):
        raise BUInvalido("identificação de seção ausente no BU")
    mz = sec.get("municipioZona") or {}
    return int(mz.get("municipio", 0)), int(mz.get("zona", 0)), int(sec.get("secao", 0))


def parse_bu(raw: bytes) -> dict[str, Any]:
    erros: list[str] = []
    for versao in ("v2", "v1"):
        try:
            conv = _conversor(versao)
            envelope = conv.decode("EntidadeEnvelopeGenerico", bytearray(raw))
            conteudo = envelope.get("conteudo")
            if not conteudo:
                raise BUInvalido("envelope sem conteúdo")
            bu = conv.decode("EntidadeBoletimUrna", conteudo)
            municipio, zona, secao = _secao_do_bu(bu, envelope)

            cargos: dict[int, dict[str, Any]] = {}
            for rve in bu.get("resultadosVotacaoPorEleicao", []):
                aptos = int(rve.get("qtdEleitoresAptos", 0))
                for rv in rve.get("resultadosVotacao", []):
                    comparecimento = int(rv.get("qtdComparecimento", 0) or 0)
                    for tvc in rv.get("totaisVotosCargo", []):
                        cargo = _codigo_cargo(tvc.get("codigoCargo"))
                        if cargo is None:
                            continue
                        votos: list[dict[str, Any]] = []
                        for v in tvc.get("votosVotaveis", []):
                            tipo = _destacar_choice(v.get("tipoVoto"))
                            item: dict[str, Any] = {
                                "tipo": tipo,
                                "votos": int(v.get("quantidadeVotos", 0)),
                            }
                            ident = v.get("identificacaoVotavel")
                            if ident:
                                item["partido"] = int(ident.get("partido", 0))
                                item["codigo"] = int(ident.get("codigo", 0))
                            votos.append(item)
                        cargos[cargo] = {
                            "aptos": aptos,
                            "comparecimento": comparecimento,
                            "votos": votos,
                        }
            return {
                "versao": versao,
                "municipio": municipio,
                "zona": zona,
                "secao": secao,
                "cargos": cargos,
            }
        except Exception as exc:
            erros.append(f"{versao}: {exc}")
    raise BUInvalido("; ".join(erros) or "BU não decodificável")
