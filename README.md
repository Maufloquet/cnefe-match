# cnefe-match

Solução para o teste prático de Engenharia de Dados Jr. (Cidacs/Fiocruz):
**localizar o setor censitário** correspondente a cada endereço da base
de busca dentro da base CNEFE Bahia (Censo 2022).

## Abordagem

1. **Indexação** do CNEFE (9M endereços) no Elasticsearch, com campos
   chave em `keyword` (filtros exatos) e logradouro/bairro em `text`
   com analyzer `lowercase + asciifolding` (suporta fuzzy nativo).
2. **Normalização** campo-a-campo da base de busca (lowercase, sem
   acento, tratamento de `None`/`SN`/`S/N`, prefixos lixo tipo `10R `).
3. **Busca em 3 camadas**, da mais restritiva pra mais permissiva.
   Aceita o resultado da primeira camada cujo score passe o limiar.

### Camadas de busca

| Camada | Critérios |
|--------|-----------|
| 1 | município exato + CEP exato + número exato + logradouro fuzzy |
| 2 | município exato + CEP exato + logradouro/bairro fuzzy (sem número) |
| 3 | município exato + logradouro/bairro fuzzy + prefixo de CEP (5 dígitos) |

Endereços que não bateram em nenhuma camada saem com `setor_censitario_encontrado = ""` e `match_layer = "none"`.

## Pré-requisitos

- Docker Desktop
- Python 3.9+
- ~3 GB livres de disco para o índice ES

## Passo a passo

```bash
# 1. Clonar e entrar
git clone <repo> cnefe-match && cd cnefe-match

# 2. Subir Elasticsearch
docker compose up -d
# Espera ~30s. Verifica:
curl -s http://localhost:9200 | head

# 3. Python venv + dependências
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 4. Baixar dados (NÃO versionados — pesados)
# Salva em data/raw/:
#   - 29_BA.csv (do IBGE ou link alternativo Fiocruz)
#   - base_busca.xlsx (link Fiocruz no enunciado)

# 5. Indexar CNEFE no ES (~70 min, 9M docs)
python scripts/04_index_cnefe.py

# 6. Rodar busca dos 107 endereços
python scripts/05_search.py
# Saída em data/processed/resultado.csv
```

## Estrutura do repositório

```
cnefe-match/
├── README.md
├── docker-compose.yml          # Elasticsearch 8.15.3 single-node
├── requirements.txt
├── scripts/
│   ├── 01_explore_cnefe.py     # sondagem do CNEFE (tipos, acentos, contagens)
│   ├── 02_normalize.py         # normalização da base de busca
│   ├── 03_explore_busca.py     # sondagem da base de 107 endereços
│   ├── 04_index_cnefe.py       # indexação em bulk no ES
│   └── 05_search.py            # busca em 3 camadas + gera resultado.csv
├── data/
│   ├── raw/                    # (não versionado) 29_BA.csv, base_busca.xlsx
│   └── processed/
│       └── resultado.csv       # ENTREGÁVEL FINAL
```

## Saída

`data/processed/resultado.csv` — todas as 107 linhas originais da base
de busca + 3 colunas novas:

| coluna | conteúdo |
|--------|----------|
| `setor_censitario_encontrado` | código do setor (15 dígitos + 1 sufixo) ou vazio se não encontrado |
| `match_layer` | `1`, `2`, `3` ou `none` — qual camada produziu o match |
| `match_score` | score retornado pelo Elasticsearch (auditoria) |

## Premissas adotadas

- **CNEFE confiável como ground truth.** Não fazemos validação cruzada
  com OSM ou outras bases.
- **`consulta_municipio` (6 dígitos) corresponde aos primeiros 6 chars
  de `COD_MUNICIPIO` (7 dígitos) do CNEFE.** Validado com amostras.
- **`SN`, `S/N`, vazio e valores não-numéricos (ex: `BR101`) em
  `consulta_numero`** são tratados como ausência de número.
- **Prefixo "None " e "10R "** em `consulta_logradouro` são lixo de
  exportação e são removidos antes do match.
- **Score mínimo por camada** (5.0/3.0/1.0) calibrado empiricamente —
  ajustável em `05_search.py`.

## Limitações conhecidas

- **107 endereços** na base, não 100 (enunciado é aproximado).
- Setores rurais/zona rural costumam ter logradouro vazio ou genérico
  (`FAZENDA X`, `SITIO Y`) → match dependente de bairro+município.
- Endereços com logradouro de letra única (`RUA A`, `RUA D`) são
  ambíguos por natureza — o ES retorna o mais provável dado o CEP, mas
  pode haver falsos positivos.
- A busca não usa `consulta_complemento` (campo muito ruidoso —
  contém `SN`, `CASA`, `COELBA`, descrições variadas).

## Dependências

Ver `requirements.txt`. Resumo:
- `pandas`, `pyarrow`, `openpyxl` — leitura/escrita
- `elasticsearch` (cliente oficial)
- `unidecode` — normalização de acento
- `tqdm` — barra de progresso

## Métricas

Após rodar `05_search.py`, o terminal imprime:
- Total processado
- Encontrados / não encontrados
- Distribuição por camada (quantos vieram da camada 1, 2, 3)

Para análises adicionais, basta abrir `resultado.csv` em pandas e
filtrar por `match_layer == "none"` ou por `match_score < N`.
