"""Sondagem do CNEFE Bahia antes da indexação.

Roda em chunks pra caber na memória. Mostra contagens, taxa de
preenchimento dos campos, presença de acento, tamanho do COD_SETOR
e os tipos de logradouro mais comuns.
"""

from collections import Counter
from pathlib import Path
import pandas as pd

CSV = Path(__file__).parent.parent / "data" / "raw" / "29_BA.csv"

USECOLS = [
    "COD_SETOR",
    "CEP",
    "DSC_LOCALIDADE",
    "NOM_TIPO_SEGLOGR",
    "NOM_TITULO_SEGLOGR",
    "NOM_SEGLOGR",
    "NUM_ENDERECO",
    "LATITUDE",
    "LONGITUDE",
]


def has_accent(s: str) -> bool:
    if not isinstance(s, str):
        return False
    return any(ord(c) > 127 for c in s)


def main():
    total = 0
    tipos = Counter()
    accent_logr = 0
    accent_local = 0
    cep_present = 0
    num_present = 0
    cep_unique = set()
    municipios = Counter()
    setor_sample = []
    setor_len = Counter()
    localidade_sample = set()

    print(f"Lendo {CSV.name}...")
    for chunk in pd.read_csv(
        CSV,
        sep=";",
        usecols=USECOLS,
        dtype=str,
        chunksize=500_000,
        encoding="latin-1",
        low_memory=False,
    ):
        total += len(chunk)
        tipos.update(chunk["NOM_TIPO_SEGLOGR"].dropna().tolist())
        accent_logr += chunk["NOM_SEGLOGR"].apply(has_accent).sum()
        accent_local += chunk["DSC_LOCALIDADE"].apply(has_accent).sum()
        cep_present += chunk["CEP"].notna().sum()
        num_present += chunk["NUM_ENDERECO"].notna().sum()
        cep_unique.update(chunk["CEP"].dropna().unique())

        # primeiros 7 do COD_SETOR ≈ código IBGE do município
        muni = chunk["COD_SETOR"].dropna().str[:7]
        municipios.update(muni.tolist())

        if len(setor_sample) < 5:
            setor_sample.extend(chunk["COD_SETOR"].dropna().head(5).tolist())
        setor_len.update(chunk["COD_SETOR"].dropna().str.len().tolist())

        if len(localidade_sample) < 30:
            for v in chunk["DSC_LOCALIDADE"].dropna().head(30).tolist():
                localidade_sample.add(v)

        print(f"  ... {total:,} linhas processadas")

    print("\n=== RESUMO ===")
    print(f"Total de linhas:           {total:,}")
    print(f"Com CEP preenchido:        {cep_present:,} ({100 * cep_present / total:.1f}%)")
    print(f"CEPs únicos:               {len(cep_unique):,}")
    print(f"Com numero preenchido:     {num_present:,} ({100 * num_present / total:.1f}%)")
    print(f"NOM_SEGLOGR com acento:    {accent_logr:,} ({100 * accent_logr / total:.1f}%)")
    print(f"DSC_LOCALIDADE com acento: {accent_local:,} ({100 * accent_local / total:.1f}%)")
    print(f"Municipios distintos:      {len(municipios):,}")

    print("\n=== Tamanho do COD_SETOR ===")
    for length, n in sorted(setor_len.items()):
        print(f"  {length} chars: {n:,}")
    print(f"  amostras: {setor_sample[:3]}")

    print("\n=== Top 15 tipos de logradouro ===")
    for t, n in tipos.most_common(15):
        print(f"  {t:25s} {n:>10,}")

    print("\n=== 10 localidades (amostra) ===")
    for v in list(localidade_sample)[:10]:
        print(f"  {v}")


if __name__ == "__main__":
    main()
