# Fontes de dados — JEPA-Spillover

Curadoria de bases **públicas**. Cada fonte mantém sua própria licença e termos de uso; cite-as em
publicações. Este repositório **não redistribui** dados de acesso restrito (ex.: GISAID).

---

## 1. Sequências genômicas virais

### NCBI Virus / Entrez
- **Conteúdo:** genomas virais completos/quase completos + metadados (hospedeiro, país, data).
- **Acesso:** API Entrez (Biopython `Bio.Entrez`). Exige **e-mail** (`data_sources.ncbi_virus.email`)
  e, opcionalmente, **API key** (eleva o limite de 3 → 10 req/s).
- **Script:** `scripts/download_ncbi_virus.py`
- **Famílias priorizadas:** Coronaviridae, Filoviridae, Paramyxoviridae, Orthomyxoviridae, Arenaviridae.

### ViPR / BV-BRC
- **Conteúdo:** genomas e anotações de patógenos virais.
- **Acesso:** downloads e API REST do BV-BRC.

### GISAID *(restrito — credencial institucional)*
- **Conteúdo:** sequências de vírus com relevância zoonótica.
- **Acesso:** **credenciamento obrigatório**; redistribuição proibida. Use localmente conforme o DAA de cada banco.
- **Bancos utilizados:**
  - **EpiCoV** — SARS-CoV-2 e betacoronavírus (bat, MERS) → `downloads/GISAID/epicov_*/`
  - **EpiArbo** — Dengue, Zika, Chikungunya, Oropouche, West Nile → `downloads/GISAID/epiarbo_*/`
  - **EpiNiV** — Nipah → `downloads/GISAID/epiniv_*/`
- **Script de ingestão:** `scripts/download_gisaid.py` (lê os TSV exportados manualmente)
- **Status:** ✅ ~12k sequências baixadas (Jun 2026).

---

## 2. Relações e interações vírus–hospedeiro

### VirusHostDB
- **Conteúdo:** mapeamento vírus → hospedeiro(s) com taxonomia.
- **Acesso:** TSV direto — `https://www.genome.jp/ftp/db/virushostdb/virushostdb.tsv`
- **Script:** `scripts/download_virushostdb.py`

### IntAct (EMBL-EBI) *(substitui VirHostNet para download em lote)*
- **Conteúdo:** base canônica que integra **VirHostNet, MINT, DIP, HPIDb, BioGRID e UniProt** — interações moleculares proteína–proteína vírus–hospedeiro em PSI-MITAB 2.5.
- **Acesso:** download direto — `https://ftp.ebi.ac.uk/pub/databases/intact/current/psimitab/intact.zip` (~1.35 GB comprimido, ~8 GB descomprimido).
- **Script:** `scripts/download_intact_virushost.py` — baixa, extrai e filtra apenas interações vírus–hospedeiro.
- **Status:** ✅ Download em andamento (Jun 2026).

### VirHostNet
- **Conteúdo:** interações **moleculares** proteína–proteína vírus–hospedeiro (subconjunto curado do IntAct).
- **Acesso:** PSICQUIC REST na porta 9090 — `http://virhostnet.prabi.fr:9090/psicquic/webservices/current/search/query/*`
- **Status:** ⚠️ Servidor instável (timeouts frequentes em Jun 2026). Usar IntAct como alternativa.

### P-HIPSTer
- **Conteúdo:** interações vírus–humano preditas estruturalmente.
- **Status:** ⚠️ Download em lote indisponível no site (Jun 2026).

---

## 3. Taxonomia

### NCBI Taxonomy (taxdump)
- **Conteúdo:** hierarquia taxonômica para padronização de vírus e hospedeiros.
- **Acesso:** `https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz`
- **Script:** `scripts/download_taxonomy.py`

### ICTV
- **Conteúdo:** taxonomia oficial de vírus (Master Species List).

---

## 4. Contexto ecológico / ocorrência

### GBIF
- **Conteúdo:** ocorrências de espécies (hospedeiros/reservatórios).
- **Acesso:** API REST pública.

### WAHIS (WOAH)
- **Conteúdo:** notificações de doenças animais.

---

## 5. Convenções de armazenamento

```
data/
├── raw/        # downloads originais, imutáveis (FASTA, TSV, dumps)
├── interim/    # parciais (sequências filtradas, joins)
├── processed/  # prontos para modelar (parquet: sequências + metadados + rótulos)
└── external/   # taxonomia, ontologias, tabelas de apoio
```

- Formato tabular padrão: **Parquet** (`pyarrow`).
- Cada download grava um **manifesto** (`*.manifest.json`) com URL, data, contagem e checksum.
- Dados brutos/grandes **não são versionados** (ver `.gitignore`); versionamos código + manifestos.

---

## 6. Rótulos de risco zoonótico

Derivados (heurística documentada, sujeita a revisão de especialista):

| Sinal | Fonte |
|---|---|
| Infecção humana registrada | NCBI host = *Homo sapiens* / literatura |
| Amplitude de hospedeiros | VirusHostDB (nº de hospedeiros distintos) |
| Histórico de surto | Registros epidemiológicos / WAHIS |
| Transmissão interespécies | VirusHostDB + literatura |

> Rótulos são **incompletos por natureza** — daí a motivação auto-supervisionada. "Não zoonótico"
> é tratado como "sem evidência atual", não como negativo definitivo.
