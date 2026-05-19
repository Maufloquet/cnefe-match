# cnefe-match

Solução para o teste de Engenharia de Dados Jr. do Cidacs/Fiocruz: dada uma
base de busca com 107 endereços de qualidade variável, localizar o setor
censitário de cada um na base CNEFE Bahia (Censo 2022, ~9M endereços).

## O que a solução faz

Carrega o CNEFE no Elasticsearch (1 índice, ~9M docs) e roda uma busca
em três camadas para cada endereço da base de busca. A camada 1 é a
mais estrita (filtra por município, CEP e número, e usa fuzzy só no
logradouro). Se não retornar nada com score razoável, cai pra camada
2 (sem número) e depois pra camada 3 (sem CEP exato, apenas prefixo).

A saída final é um CSV com as colunas originais mais três novas:
`setor_censitario_encontrado`, `match_layer` e `match_score`. Endereços
não localizados aparecem com o setor vazio e `match_layer = "none"`.

## Como rodar

Pré-requisitos: Docker Desktop, Python 3.9 ou superior, e ~3 GB livres
pra acomodar o índice do Elasticsearch.

```bash
git clone <repo> cnefe-match
cd cnefe-match

docker compose up -d
# espera o ES subir — ~30s. Pra conferir:
curl -s http://localhost:9200

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Os dados não estão versionados (pesados demais). Baixar e salvar em
`data/raw/`:

- `29_BA.csv` — CNEFE Bahia, do IBGE (1,4 GB)
- `base_busca.xlsx` — base com os 107 endereços, link do enunciado

Depois:

```bash
python scripts/04_index_cnefe.py    # ~45 a 70 min, indexa o CNEFE
python scripts/05_search.py         # processa a base de busca
```

A saída sai em `data/processed/resultado.csv`.

## Estrutura

```
cnefe-match/
├── docker-compose.yml
├── requirements.txt
├── README.md
├── scripts/
│   ├── 01_explore_cnefe.py     sondagem do CNEFE
│   ├── 02_normalize.py         normalização da base de busca
│   ├── 03_explore_busca.py     sondagem da base de busca
│   ├── 04_index_cnefe.py       indexação bulk
│   └── 05_search.py            busca em camadas + escrita do resultado
└── data/
    ├── raw/                    (não versionado)
    └── processed/
        └── resultado.csv
```

## Premissas

Algumas decisões adotadas que vale documentar:

O `consulta_municipio` da base de busca vem em 6 dígitos. O CNEFE traz
o `COD_MUNICIPIO` em 7 dígitos (com DV). Truncar os 7 nos 6 primeiros
faz o match — verifiquei amostralmente.

`SN`, `S/N`, vazio e strings não-numéricas (`BR101`) no campo
`consulta_numero` são tratadas como ausência de número. O CNEFE também
usa `SN` no campo de número pra zona rural, então deixar a query
ignorar o número quando não há um confiável evita falsos negativos.

A base de busca tem dois prefixos espúrios no campo `consulta_logradouro`:
`None ` (provavelmente NaN serializado pelo exportador) e `10R ` (sigla
de quadra/lote vinda solta). Os dois são removidos antes do match.

`consulta_complemento` não entra na query — o campo é muito ruidoso
(contém de "CASA" a "COELBA", além de "SN" repetido).

Os limites mínimos de score por camada (5.0, 3.0 e 1.0) são empíricos.
Podem ser ajustados em `05_search.py`.

## Limitações

A base tem 107 endereços, não 100 como diz o enunciado. Processo todos.

Endereços rurais com logradouro vazio ou genérico (`FAZENDA X`, `SITIO Y`)
dependem de bairro e município pra match — em zonas rurais grandes
isso pode ser ambíguo.

Logradouros de letra única (`RUA A`, `RUA D`, `RUA E`) são ambíguos
por natureza. O ES retorna o mais provável dado o CEP/município, mas
o resultado pode estar errado para esses casos.

A solução não faz validação cruzada com outras bases (OSM, Google).
O CNEFE é tratado como ground truth, conforme o enunciado.

## Métricas da execução

Rodando contra a base de busca fornecida (107 endereços):

- 107/107 endereços localizados
- 77 na camada 1 (município + CEP + número + logradouro fuzzy)
- 17 na camada 2 (sem número, CEP exato)
- 13 na camada 3 (sem CEP exato — prefixo de 5 dígitos)
- 0 não encontrados

Os scores variam de ~13 a ~46 (camada 1 e 2 ficam tipicamente entre
15 e 30; camada 3 entre 17 e 46). O log completo está em
`data/processed/execucao.log`.

Vale notar que a camada 3 é a menos confiável por construção — não
exige CEP exato. Os 13 casos que caíram lá são quase todos rodovias,
endereços sem número, ou logradouros de letra única (`RUA E`) que são
ambíguos por natureza. O `match_layer` e `match_score` ficam no CSV
de saída justamente pra deixar o avaliador identificar onde a
confiança é maior ou menor.

## Dependências

- pandas, pyarrow, openpyxl
- elasticsearch (cliente oficial 8.x)
- unidecode, tqdm
