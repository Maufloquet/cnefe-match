"""Limpeza campo-a-campo da base de busca antes de mandar pro ES.

Não faz fuzzy aqui — isso fica pro ES via `fuzziness: AUTO`.
Município vira 6 dígitos pra bater com COD_MUNICIPIO[:6] do CNEFE.
"""

import re
from typing import Optional
from unidecode import unidecode

# Abreviações comuns. Aplica APÓS lowercase + unidecode.
ABBREV = [
    (r"\bav\.?(\s|$)", "avenida\\1"),
    (r"\br\.\s", "rua "),
    (r"\btrav\.?\s", "travessa "),
    (r"\bal\.?\s", "alameda "),
    (r"\best\.?\s", "estrada "),
    (r"\brod\.?\s", "rodovia "),
    (r"\bpc\.?\s", "praca "),
    (r"\bpca\.?\s", "praca "),
    (r"\blgo\.?\s", "largo "),
]

# Tokens que indicam "sem número". Maiores antes pra match correto.
SEM_NUMERO = {"sn", "s/n", "s\\n", "s n", ""}


def norm_text(s) -> str:
    """Lowercase, sem acento, sem pontuação extra. Trata None/NaN/'None'."""
    if s is None:
        return ""
    s = str(s).strip()
    if s.lower() == "nan" or s == "None":
        return ""
    s = unidecode(s).lower()
    s = re.sub(r"[.,;:!?\"']", " ", s)
    for pat, rep in ABBREV:
        s = re.sub(pat, rep, s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def norm_logradouro(s) -> str:
    s = norm_text(s)
    if not s:
        return ""
    # tira prefixos lixo do exportador: "None FOO" e "10R FOO"
    s = re.sub(r"^none\s+", "", s)
    s = re.sub(r"^\d+[a-z]?\s+(?=(rua|avenida|fazenda|sitio|travessa|estrada|rodovia|praca|alameda|distrito|conjunto|comunidade|via|loteamento))", "", s)
    return s


def norm_numero(s) -> Optional[str]:
    """Só dígitos vira número. SN/S/N/BR101 viram None."""
    s = norm_text(s)
    if s in SEM_NUMERO:
        return None
    if s.isdigit():
        return s
    return None


def norm_cep(s) -> Optional[str]:
    """CEP — só dígitos, deve ter 8."""
    if s is None:
        return None
    only_digits = re.sub(r"\D", "", str(s))
    if len(only_digits) != 8:
        return None
    return only_digits


def norm_municipio_6(s) -> Optional[str]:
    """Município em 6 dígitos (formato da base de busca)."""
    if s is None:
        return None
    only_digits = re.sub(r"\D", "", str(s))
    if len(only_digits) == 6:
        return only_digits
    if len(only_digits) == 7:
        # já veio com DV — trunca
        return only_digits[:6]
    return None


def normalize_row(row: dict) -> dict:
    """Aplica as norms acima nos campos consulta_* e devolve um dict
    pronto pra montar a query."""
    return {
        "logradouro": norm_logradouro(row.get("consulta_logradouro")),
        "numero": norm_numero(row.get("consulta_numero")),
        "bairro": norm_text(row.get("consulta_bairro")),
        "cep": norm_cep(row.get("consulta_cep")),
        "complemento": norm_text(row.get("consulta_complemento")),
        "municipio_6": norm_municipio_6(row.get("consulta_municipio")),
    }


# ----- Teste com casos reais da base de busca -----
TEST_CASES = [
    {  # endereço completo
        "consulta_logradouro": "RUA SERGIO BOMFIM",
        "consulta_numero": "332",
        "consulta_bairro": "BARREIRINHAS",
        "consulta_cep": "47800020",
        "consulta_complemento": None,
        "consulta_municipio": "290320",
    },
    {  # None literal no logradouro
        "consulta_logradouro": "None EVILASIO FIRMATO",
        "consulta_numero": "28",
        "consulta_bairro": "SOCRATES REZENDE",
        "consulta_cep": "45860000",
        "consulta_complemento": None,
        "consulta_municipio": "290630",
    },
    {  # SN no número
        "consulta_logradouro": "FAZENDA LAGOA GRANDE",
        "consulta_numero": None,
        "consulta_bairro": None,
        "consulta_cep": "46380000",
        "consulta_complemento": "SN",
        "consulta_municipio": "290660",
    },
    {  # prefixo lixo "10R "
        "consulta_logradouro": "10R FAZENDA BOA ESPERANCA",
        "consulta_numero": "S/N",
        "consulta_bairro": "RURAL",
        "consulta_cep": "45928000",
        "consulta_complemento": "KM 87",
        "consulta_municipio": "292300",
    },
    {  # número como nome de via (BR101)
        "consulta_logradouro": "RODOVIA BR 101",
        "consulta_numero": "BR101",
        "consulta_bairro": None,
        "consulta_cep": "48030260",
        "consulta_complemento": "SN",
        "consulta_municipio": "290070",
    },
]


def _run_tests():
    for raw in TEST_CASES:
        out = normalize_row(raw)
        print(f"IN:  {raw['consulta_logradouro']!r}, num={raw['consulta_numero']!r}, cep={raw['consulta_cep']!r}")
        print(f"OUT: logr={out['logradouro']!r}")
        print(f"     numero={out['numero']!r} cep={out['cep']!r}")
        print(f"     bairro={out['bairro']!r} muni={out['municipio_6']!r}")
        print()


if __name__ == "__main__":
    _run_tests()
