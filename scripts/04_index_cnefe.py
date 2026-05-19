"""Indexa o CNEFE Bahia (9M docs) no Elasticsearch.

Lê o CSV em chunks de 100k e manda em bulks de 5k pro ES. Durante a
carga, desliga refresh e replicas pra ganhar velocidade — religa no
fim. Roda em ~45 min numa máquina típica."""

import sys
import time
from pathlib import Path

import pandas as pd
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from tqdm import tqdm

CSV = Path(__file__).parent.parent / "data" / "raw" / "29_BA.csv"
INDEX = "cnefe_ba"
ES_URL = "http://localhost:9200"

CHUNK_SIZE = 100_000
BULK_SIZE = 5_000

USECOLS = [
    "COD_SETOR",
    "COD_MUNICIPIO",
    "CEP",
    "DSC_LOCALIDADE",
    "NOM_TIPO_SEGLOGR",
    "NOM_TITULO_SEGLOGR",
    "NOM_SEGLOGR",
    "NUM_ENDERECO",
    "LATITUDE",
    "LONGITUDE",
]

# asciifolding+lowercase pra fuzzy bater queries com acento contra
# os dados (que já vêm em ASCII MAIÚSCULAS).
MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "refresh_interval": "-1",
        "analysis": {
            "analyzer": {
                "endereco_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                }
            }
        },
    },
    "mappings": {
        "properties": {
            "cod_setor": {"type": "keyword"},
            "cod_municipio_6": {"type": "keyword"},
            "cep": {"type": "keyword"},
            "numero": {"type": "keyword"},
            "logradouro_full": {
                "type": "text",
                "analyzer": "endereco_analyzer",
            },
            "bairro": {
                "type": "text",
                "analyzer": "endereco_analyzer",
            },
            "latitude": {"type": "float"},
            "longitude": {"type": "float"},
        }
    },
}


def build_logradouro(row) -> str:
    """TIPO + TITULO + NOME concatenados, ignorando vazios."""
    parts = []
    for col in ["NOM_TIPO_SEGLOGR", "NOM_TITULO_SEGLOGR", "NOM_SEGLOGR"]:
        v = row.get(col)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    return " ".join(parts)


def make_actions(df_chunk):
    for _, r in df_chunk.iterrows():
        cod_muni = r.get("COD_MUNICIPIO") or ""
        try:
            lat = float(r["LATITUDE"]) if pd.notna(r["LATITUDE"]) else None
        except (ValueError, TypeError):
            lat = None
        try:
            lng = float(r["LONGITUDE"]) if pd.notna(r["LONGITUDE"]) else None
        except (ValueError, TypeError):
            lng = None
        yield {
            "_index": INDEX,
            "_source": {
                "cod_setor": r.get("COD_SETOR"),
                "cod_municipio_6": str(cod_muni)[:6] if cod_muni else None,
                "cep": r.get("CEP"),
                "numero": r.get("NUM_ENDERECO"),
                "logradouro_full": build_logradouro(r),
                "bairro": r.get("DSC_LOCALIDADE"),
                "latitude": lat,
                "longitude": lng,
            },
        }


def main():
    es = Elasticsearch(ES_URL, request_timeout=120)
    if not es.ping():
        print("FATAL: Elasticsearch não responde em", ES_URL)
        sys.exit(1)

    if es.indices.exists(index=INDEX):
        print(f"indice '{INDEX}' ja existe, recriando do zero")
        es.indices.delete(index=INDEX)
    es.indices.create(index=INDEX, body=MAPPING)
    print(f"indice '{INDEX}' criado")

    t0 = time.time()
    total_indexed = 0
    total_errors = 0

    print(f"Lendo {CSV.name} e indexando em lotes de {BULK_SIZE}...")
    pbar = tqdm(total=9_047_296, unit="docs")
    for chunk in pd.read_csv(
        CSV,
        sep=";",
        usecols=USECOLS,
        dtype=str,
        chunksize=CHUNK_SIZE,
        encoding="latin-1",
        low_memory=False,
    ):
        success, errors = bulk(
            es,
            make_actions(chunk),
            chunk_size=BULK_SIZE,
            raise_on_error=False,
            raise_on_exception=False,
        )
        total_indexed += success
        if isinstance(errors, list):
            total_errors += len(errors)
        pbar.update(len(chunk))
    pbar.close()

    # Liga refresh e força flush
    es.indices.put_settings(
        index=INDEX,
        body={"refresh_interval": "1s"},
    )
    es.indices.refresh(index=INDEX)
    count = es.count(index=INDEX)["count"]

    elapsed = time.time() - t0
    print(f"\nindexacao concluida em {elapsed / 60:.1f} min")
    print(f"  indexados: {total_indexed:,}")
    print(f"  erros:     {total_errors:,}")
    print(f"  count ES:  {count:,}")


if __name__ == "__main__":
    main()
