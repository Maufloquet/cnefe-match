"""
Busca os 107 endereços da base de busca no índice cnefe_ba.

Estratégia em 3 camadas, da mais restritiva pra mais permissiva.
Mantém o resultado da PRIMEIRA camada que retorna um hit com score
acima do limite — assim o output prioriza match exato e só cai pra
fuzzy quando precisa.

Output: data/processed/resultado.csv com:
  - todas as colunas originais da base de busca
  - setor_censitario_encontrado  (None se não achou em nenhuma camada)
  - match_layer                  (1, 2, 3 ou 'none')
  - match_score                  (score do ES — útil pra auditoria)

Reprodutível: roda sempre na mesma ordem; queries são determinísticas
dado o índice.
"""

import sys
from pathlib import Path

import pandas as pd
from elasticsearch import Elasticsearch

sys.path.insert(0, str(Path(__file__).parent))
from importlib import import_module
_norm_mod = import_module("02_normalize") if False else None  # placeholder

# Importa normalize_row do módulo irmão
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "norm", Path(__file__).parent / "02_normalize.py"
)
_norm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_norm)
normalize_row = _norm.normalize_row

ES_URL = "http://localhost:9200"
INDEX = "cnefe_ba"

XLSX_IN = Path(__file__).parent.parent / "data" / "raw" / "base_busca.xlsx"
CSV_OUT = Path(__file__).parent.parent / "data" / "processed" / "resultado.csv"

# Limites de score pra aceitar um hit por camada. Calibrados depois
# que rodarmos a primeira vez e olharmos a distribuição.
MIN_SCORE_LAYER1 = 5.0
MIN_SCORE_LAYER2 = 3.0
MIN_SCORE_LAYER3 = 1.0


def query_layer1(n):
    """Município + CEP exatos + número exato (se houver) + logradouro fuzzy."""
    must = [
        {"term": {"cod_municipio_6": n["municipio_6"]}},
        {"term": {"cep": n["cep"]}},
    ]
    if n["numero"]:
        must.append({"term": {"numero": n["numero"]}})
    if n["logradouro"]:
        must.append({
            "match": {
                "logradouro_full": {
                    "query": n["logradouro"],
                    "fuzziness": "AUTO",
                }
            }
        })
    return {"bool": {"must": must}}


def query_layer2(n):
    """Município + CEP exatos + logradouro fuzzy + bairro fuzzy (sem número)."""
    must = [
        {"term": {"cod_municipio_6": n["municipio_6"]}},
        {"term": {"cep": n["cep"]}},
    ]
    should = []
    if n["logradouro"]:
        should.append({"match": {"logradouro_full": {"query": n["logradouro"], "fuzziness": "AUTO"}}})
    if n["bairro"]:
        should.append({"match": {"bairro": {"query": n["bairro"], "fuzziness": "AUTO"}}})
    q = {"bool": {"must": must}}
    if should:
        q["bool"]["should"] = should
        q["bool"]["minimum_should_match"] = 1
    return q


def query_layer3(n):
    """Município exato + logradouro/bairro fuzzy + prefixo de CEP.

    Pra quando o CEP está errado mas a região (5 dígitos iniciais) ainda
    bate. CEP no Brasil: 5 primeiros dígitos identificam município/bairro,
    3 últimos são face de quadra.
    """
    must = [
        {"term": {"cod_municipio_6": n["municipio_6"]}},
    ]
    should = []
    if n["logradouro"]:
        should.append({"match": {"logradouro_full": {"query": n["logradouro"], "fuzziness": "AUTO", "boost": 2.0}}})
    if n["bairro"]:
        should.append({"match": {"bairro": {"query": n["bairro"], "fuzziness": "AUTO"}}})
    if n["cep"]:
        should.append({"prefix": {"cep": {"value": n["cep"][:5], "boost": 1.5}}})
    q = {"bool": {"must": must}}
    if should:
        q["bool"]["should"] = should
        q["bool"]["minimum_should_match"] = 1
    return q


def search_one(es, n):
    """Tenta camada 1 → 2 → 3 e devolve (cod_setor, layer, score)."""
    if not n["municipio_6"]:
        return (None, "none", 0.0)

    layers = [
        (1, query_layer1, MIN_SCORE_LAYER1),
        (2, query_layer2, MIN_SCORE_LAYER2),
        (3, query_layer3, MIN_SCORE_LAYER3),
    ]
    for layer_num, builder, min_score in layers:
        try:
            resp = es.search(
                index=INDEX,
                query=builder(n),
                size=1,
                _source=["cod_setor"],
            )
            hits = resp["hits"]["hits"]
            if hits:
                score = hits[0]["_score"]
                if score >= min_score:
                    return (hits[0]["_source"]["cod_setor"], layer_num, score)
        except Exception as e:
            print(f"  ! erro camada {layer_num}: {e}")
    return (None, "none", 0.0)


def main():
    es = Elasticsearch(ES_URL, request_timeout=60)
    if not es.ping():
        print("FATAL: ES não responde")
        sys.exit(1)

    df = pd.read_excel(XLSX_IN, dtype=str)
    print(f"Lendo {len(df)} endereços da base de busca...\n")

    setores = []
    layers = []
    scores = []
    layer_counts = {1: 0, 2: 0, 3: 0, "none": 0}

    for i, row in df.iterrows():
        n = normalize_row(row.to_dict())
        setor, layer, score = search_one(es, n)
        setores.append(setor)
        layers.append(layer)
        scores.append(round(score, 2))
        layer_counts[layer] += 1
        status = "✓" if setor else "✗"
        print(f"  {i+1:3d}. {status} layer={layer} score={score:5.2f} → {setor}")

    df["setor_censitario_encontrado"] = setores
    df["match_layer"] = layers
    df["match_score"] = scores

    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CSV_OUT, index=False)

    total = len(df)
    encontrados = total - layer_counts["none"]
    print(f"\n=== RESUMO ===")
    print(f"Total:        {total}")
    print(f"Encontrados:  {encontrados} ({100 * encontrados / total:.1f}%)")
    for k in [1, 2, 3, "none"]:
        print(f"  camada {k}: {layer_counts[k]}")
    print(f"\nGravado em {CSV_OUT}")


if __name__ == "__main__":
    main()
