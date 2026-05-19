"""
Normalização campo-a-campo da base de busca pra alinhar com o CNEFE.

Premissa (confirmada na sondagem da base de busca):
  - A base já vem em colunas separadas (consulta_logradouro,
    consulta_numero, consulta_bairro, consulta_cep, consulta_complemento,
    consulta_municipio).
  - O CNEFE vem em ASCII MAIÚSCULAS sem acento, separador ';'.
  - Município na busca tem 6 dígitos; no CNEFE são 7 (DV no fim).
    Filtro: COD_MUNICIPIO do CNEFE truncado em [:6].

Esta função NÃO faz fuzzy matching — só limpeza. O fuzzy fica pro
Elasticsearch (que faz nativo via `fuzziness: AUTO`).
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
    """Lowercase + sem acento + sem pontuação extra + espaços colapsados.

    Aceita None/NaN e retorna string vazia. Trata "None" literal (NaN
    serializado pelo exportador da base de busca) como vazio.
    """
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
    """Logradouro normalizado.

    Trata casos especiais da base de busca:
    - 'None EVILASIO FIRMATO' → 'evilasio firmato' (remove None literal)
    - '10R FAZENDA BOA ESPERANCA' → 'fazenda boa esperanca' (remove prefixo lixo)
    """
    s = norm_text(s)
    if not s:
        return ""
    # Remove "none" prefix literal
    s = re.sub(r"^none\s+", "", s)
    # Remove prefixos numéricos curtos como "10r " (sigla de quadra/lote)
    s = re.sub(r"^\d+[a-z]?\s+(?=(rua|avenida|fazenda|sitio|travessa|estrada|rodovia|praca|alameda|distrito|conjunto|comunidade|via|loteamento))", "", s)
    return s


def norm_numero(s) -> Optional[str]:
    """Número do endereço. Retorna None se for 'sem número' em qualquer
    variação (SN, S/N, vazio, ou texto não numérico tipo 'BR101').

    Por que: o CNEFE guarda número como string, e 'SN'/0 são lá usados
    pra zona rural. Tratar como None deixa a query do ES ignorar o
    campo quando não há número confiável.
    """
    s = norm_text(s)
    if s in SEM_NUMERO:
        return None
    # Se for puramente numérico, é número de porta
    if s.isdigit():
        return s
    # 'BR101', '10A' etc — não vira número, mas pode entrar no logradouro
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
    """Normaliza uma linha da base de busca pra entrada do ES.

    Espera dict com chaves: consulta_logradouro, consulta_numero,
    consulta_bairro, consulta_cep, consulta_complemento, consulta_municipio.

    Retorna dict pronto pra montar a query ES.
    """
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
