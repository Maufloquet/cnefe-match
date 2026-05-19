# cnefe-match

Solução para o teste prático da vaga "Bolsa de Pesquisa para Engenheiro
de Dados Júnior" do Cidacs/Fiocruz. Dada uma base de busca com endereços
de qualidade variável, localizar o setor censitário correspondente na
base CNEFE Bahia (Censo 2022, ~9M endereços).

Observação: o enunciado fala em 100 endereços; o arquivo entregue tem
107 linhas e a solução processa todas (não há truncagem manual).

## O que a solução faz

Carrega o CNEFE no Elasticsearch (1 índice, ~9M docs) e roda uma busca
em três camadas para cada endereço da base de busca. A camada 1 é a
mais estrita (filtra por município, CEP e número, e usa fuzzy só no
logradouro). Se não retornar nada com score razoável, cai pra camada
2 (sem número) e depois pra camada 3 (sem CEP exato, apenas prefixo).

A saída final é um CSV com as colunas originais mais quatro novas:

- `setor_censitario_encontrado` — código do setor, ou vazio.
- `match_status` — `encontrado`, `ambiguo` ou `nao_encontrado`.
- `match_layer` — qual camada produziu o match (1, 2, 3 ou `none`).
- `match_score` — score retornado pelo Elasticsearch.

Um endereço é marcado como `ambiguo` quando o segundo melhor hit tem
score muito próximo do primeiro (razão >= 0,85) e os setores diferem.
Mesmo nesses casos, devolvemos o melhor hit em `setor_censitario_encontrado`
— a flag serve pra que o avaliador saiba onde a confiança é menor.

## Tecnologias sugeridas e escolhas

O enunciado sugere quatro tecnologias: Docker, GitHub, Elasticsearch e
Spark. Abaixo, o que foi adotado e por quê.

**Docker.** Usado para subir o Elasticsearch via `docker-compose.yml`.
Garante reprodutibilidade do ambiente de busca sem depender de
instalação local do ES.

**GitHub.** Código versionado em https://github.com/Maufloquet/cnefe-match,
com histórico de commits coerente com a evolução do projeto.

**Elasticsearch.** Núcleo da solução. Aproveita o `fuzziness: AUTO`
nativo (BM25 + edit distance) para tolerar variações de escrita, e
expõe filtros exatos (`term`) e fuzzy (`match`) na mesma query —
combinação ideal pra busca de endereços com qualidade variável.

**Spark.** Não foi adotado nesta solução. A indexação dos ~9M endereços
do CNEFE Bahia roda em ~40 min com `pandas.read_csv(chunksize=)` +
bulk no Elasticsearch numa máquina local sem cluster, e a busca dos
107 endereços é uma operação I/O contra o ES (não paralelizável de
forma significativa). Introduzir Spark traria dependência adicional
(JVM) e overhead de configuração sem ganho mensurável no escopo
deste teste. Caso o volume cresça — por exemplo, indexar todas as
27 UFs do CNEFE simultaneamente, ou alimentar o índice a partir de
múltiplas fontes em pipeline contínuo — Spark passa a fazer sentido
na camada de leitura e transformação, mantendo o Elasticsearch como
camada de busca.

## Como rodar

Pré-requisitos: Docker Desktop, Python 3.9 ou superior, e ~3 GB livres
pra acomodar o índice do Elasticsearch.

```bash
git clone https://github.com/Maufloquet/cnefe-match.git
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
python scripts/index_cnefe.py    # ~45 min, indexa o CNEFE no ES
python scripts/search.py         # processa a base de busca e gera o CSV
```

A saída sai em `data/processed/resultado.csv` e também em
`data/processed/resultado.xlsx` — mesmos dados, dois formatos
pra facilitar inspeção. O CSV usa vírgula como separador (RFC 4180);
em Excel pt-BR (que assume `;`), use o XLSX ou o pandas direto.

## Estrutura

```
cnefe-match/
├── docker-compose.yml
├── requirements.txt
├── README.md
├── scripts/
│   ├── normalize.py            limpeza dos campos da base de busca
│   ├── index_cnefe.py          indexação bulk no Elasticsearch
│   ├── search.py               busca em camadas e escrita do resultado
│   ├── explore_cnefe.py        sondagem inicial do CNEFE (opcional)
│   └── explore_busca.py        sondagem inicial da base de busca (opcional)
└── data/
    ├── raw/                    (não versionado)
    └── processed/
        ├── resultado.csv       saída final em CSV
        ├── resultado.xlsx      saída final em XLSX (mesmo conteúdo)
        └── execucao.log        log da última execução
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

Não há etapa de processamento manual. Todos os ajustes (remoção de
prefixos lixo, tratamento de `SN`, truncagem de município) estão
implementados em código no `scripts/normalize.py` e podem ser
reexecutados por terceiros.

## Métricas da execução

Rodando contra a base de busca fornecida (107 endereços):

Por `match_status`:

- 70 encontrados (resposta única clara)
- 37 ambíguos (existe um segundo setor com score próximo)
- 0 não encontrados

Por `match_layer`:

- 77 na camada 1 (município + CEP + número + logradouro fuzzy)
- 17 na camada 2 (sem número, CEP exato)
- 13 na camada 3 (sem CEP exato — prefixo de 5 dígitos)

Os scores ficam tipicamente entre 13 e 46. O log completo está em
`data/processed/execucao.log`.

A camada 3 é a menos confiável por construção — não exige CEP exato.
Os 13 casos que caíram lá são quase todos rodovias, endereços sem
número, ou logradouros de letra única (`RUA E`).

Sobre os ambíguos: o CNEFE divide um mesmo CEP entre várias faces de
quadra (e portanto vários setores). Quando o endereço de entrada não
tem número confiável ou está em zona rural com bairro genérico, é
esperado que mais de um setor bata com score parecido. Marcamos
explicitamente esses casos pra o avaliador saber onde a resposta
única pode coincidentemente estar correta mas a confiança é menor.

## Dependências

Python:

- pandas, pyarrow
- openpyxl (leitura do `.xlsx`)
- elasticsearch (cliente oficial 8.x)
- unidecode, tqdm

Sistema:

- Docker Desktop (ou Docker Engine + Compose)
- Python 3.9+
