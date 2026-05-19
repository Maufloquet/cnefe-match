"""
Sondagem da base de busca (100 endereços do Fiocruz).

O que queremos saber: quantas linhas, quais colunas exatas, taxa de
preenchimento por campo, padrões de "sem número" (SN, S/N, vazio),
relação entre consulta_municipio (6 dígitos do PDF) e COD_MUNICIPIO do
CNEFE (7 dígitos com DV).
"""

from collections import Counter
from pathlib import Path
import pandas as pd

XLSX = Path(__file__).parent.parent / "data" / "raw" / "base_busca.xlsx"


def main():
    df = pd.read_excel(XLSX, dtype=str)
    print(f"Linhas: {len(df)}")
    print(f"Colunas: {list(df.columns)}")
    print()

    for c in df.columns:
        n = df[c].notna().sum()
        unique = df[c].nunique()
        print(f"  {c:25s} preenchidos={n:>3} unicos={unique:>3}")

    print("\n=== consulta_numero — valores mais comuns ===")
    for v, n in Counter(df["consulta_numero"].fillna("(vazio)")).most_common(10):
        print(f"  {v!r:20s} {n}")

    print("\n=== consulta_complemento — valores mais comuns ===")
    for v, n in Counter(df["consulta_complemento"].fillna("(vazio)")).most_common(10):
        print(f"  {v!r:20s} {n}")

    print("\n=== consulta_municipio — formato ===")
    munis = df["consulta_municipio"].dropna().astype(str)
    print(f"  amostras: {munis.head(5).tolist()}")
    print(f"  tamanhos distintos: {Counter(munis.str.len())}")
    print(f"  municipios unicos: {munis.nunique()}")

    print("\n=== consulta_cep — formato ===")
    ceps = df["consulta_cep"].dropna().astype(str)
    print(f"  amostras: {ceps.head(5).tolist()}")
    print(f"  tamanhos distintos: {Counter(ceps.str.len())}")

    print("\n=== consulta_logradouro — primeiros tokens (tipo de via) ===")
    primeira = df["consulta_logradouro"].dropna().str.split().str[0]
    for v, n in Counter(primeira).most_common(15):
        print(f"  {v:15s} {n}")

    print("\n=== Endereços suspeitos / baixa qualidade ===")
    weird = df[
        df["consulta_logradouro"].fillna("").str.startswith("None")
        | df["consulta_logradouro"].fillna("").str.match(r"^\d")
        | df["consulta_logradouro"].fillna("").str.contains(r"\bRUA [A-Z]( |$)", regex=True)
    ]
    print(f"  total flagged: {len(weird)}")
    for _, r in weird.head(15).iterrows():
        logr = r["consulta_logradouro"]
        print(f"    {logr!r}")


if __name__ == "__main__":
    main()
