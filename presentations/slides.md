---
marp: true
theme: default
paginate: true
size: 16:9
header: "JEPA-Spillover · PDJ/Fiocruz · Instituto Aggeu Magalhães"
footer: "Gabriel Bezerra Motta Câmara · 2026"
style: |
  section { font-size: 26px; }
  h1 { color: #1565c0; }
  h2 { color: #2e7d32; }
  table { font-size: 22px; }
---

<!-- _class: lead -->
<!-- _paginate: false -->

# JEPA-Spillover

## Aprendizado preditivo em espaço latente para vigilância genômica de vírus com potencial zoonótico

**Gabriel Bezerra Motta Câmara**
Pós-Doutorado Júnior — PDJ/Fiocruz
Instituto Aggeu Magalhães — Fiocruz Pernambuco

---

## O problema

- **Spillover zoonótico** = principal origem de doenças infecciosas emergentes (SARS-CoV-2, Ebola, Nipah, Influenza aviária).
- Genomas virais crescem rápido (vigilância, metagenômica, viroma)...
- ...mas a maioria dos vírus **não tem rótulo confiável de risco zoonótico**.
- Modelos supervisionados sofrem: "não zoonótico" muitas vezes = **"não estudado"**.

> Precisamos **priorizar vírus de risco** antes dos surtos — com poucos rótulos.

---

## A ideia: por que JEPA?

**Joint Embedding Predictive Architecture** — prevê *representações latentes*, não nucleotídeos.

| Abordagem | Limitação |
|---|---|
| Supervisionada | Depende de rótulos escassos/enviesados |
| Reconstrução (autoencoder/MLM) | Gasta capacidade modelando ruído de baixo nível |
| **JEPA** | Aprende semântica funcional **sem reconstrução** e com **baixa dependência de rótulos** |

Ideal para **vírus pouco caracterizados**.

---

## Como funciona a JEPA genômica

![w:1000](../docs/flowcharts/02_jepa_genomica.md)

- **Codificador de contexto** vê parte do genoma.
- **Codificador-alvo (EMA)** gera o embedding de outras regiões.
- **Preditor** prevê o embedding-alvo → perda **no espaço latente**.

*(diagrama Mermaid em `docs/flowcharts/02_jepa_genomica.md`)*

---

## Pipeline de ponta a ponta

```
Bases públicas → Curadoria → Representações (k-mers/embeddings)
   → JEPA genômica → JEPA vírus-hospedeiro → Fine-tuning
   → Avaliação (UMAP/SHAP) → Ranking → Dashboard / GitHub / HF
```

- Configuração única e reprodutível (`config/config.yaml`).
- Roda com **dados reais** (NCBI, VirusHostDB) ou **dados sintéticos** (demo/CI).
- *(diagrama completo em `docs/flowcharts/01_pipeline_geral.md`)*

---

## Dados

| Base | Conteúdo |
|---|---|
| NCBI Virus / Entrez | Genomas + metadados |
| VirusHostDB | Relações vírus–hospedeiro |
| VirHostNet / P-HIPSTer | Interações moleculares |
| NCBI Taxonomy / ICTV | Padronização taxonômica |
| GBIF / WAHIS | Contexto ecológico |

Famílias-foco: **Coronaviridae, Filoviridae, Paramyxoviridae, Orthomyxoviridae, Arenaviridae**.

---

## Avaliação rigorosa

- **Validação cruzada** estratificada por família.
- **Validação entre famílias** (holdout de famílias inteiras) → simula vírus emergentes.
- Métricas: **AUROC, AUPRC, F1, precisão, recall, especificidade, Brier**.
- Baselines: **k-mers, LSTM, Transformer supervisionado**.
- Interpretabilidade: **UMAP/t-SNE, clustering, SHAP, ablação**.

---

## Entregáveis (12 meses)

1. Base integrada e documentada de vírus + hospedeiros + metadados.
2. JEPA genômica treinada + embeddings.
3. Extensão vírus-hospedeiro / multimodal.
4. Modelo de risco de spillover + comparação com baselines.
5. **Ranking de vírus prioritários** para vigilância.
6. Repositório aberto (GitHub + Hugging Face) + manuscrito.

---

## Relevância para o SUS

- Apoia **vigilância genômica** e **preparação para emergências**.
- Prioriza amostras e orienta estudos laboratoriais.
- Solução **aberta, reprodutível e adaptável** ao contexto brasileiro.
- Fortalece **soberania tecnológica** em IA aplicada à saúde.

> Ferramenta de **apoio à priorização** — não substitui validação experimental.

---

<!-- _class: lead -->

# Obrigado!

**Repositório:** github.com/gbmotta/jepa-spillover
**Modelos/dados:** huggingface.co/gbmotta/jepa-spillover

*Instituto Aggeu Magalhães · Fiocruz Pernambuco · PDJ/Fiocruz · 2026*
