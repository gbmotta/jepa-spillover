---
license: mit
language:
  - pt
  - en
tags:
  - biology
  - genomics
  - virology
  - bioinformatics
  - self-supervised-learning
  - jepa
  - zoonotic-spillover
library_name: pytorch
pipeline_tag: feature-extraction
---

# JEPA-Spillover — Model Card

Modelo **JEPA genômico** auto-supervisionado que aprende representações latentes de genomas virais
para apoiar a **priorização de vírus com potencial zoonótico** (spillover).

## Descrição

- **Arquitetura:** Joint Embedding Predictive Architecture (codificador de contexto + codificador-alvo
  por EMA + preditor latente), adaptada a sequências genômicas tokenizadas por k-mers.
- **Objetivo de treino:** prever, no espaço latente, embeddings de blocos-alvo a partir de um bloco de
  contexto (sem reconstrução de nucleotídeos).
- **Saída:** embedding por genoma viral (extração de atributos) + cabeça de classificação para risco
  de spillover (fine-tuning).

## Usos pretendidos

- Geração de embeddings virais para clustering, busca de vizinhança e visualização (UMAP/t-SNE).
- Priorização de vírus pouco caracterizados para vigilância genômica.

## Limitações e riscos

- **Prova de conceito** — não é ferramenta diagnóstica nem decisão de saúde pública.
- Rótulos de risco zoonótico são **incompletos e enviesados**; "não zoonótico" ≈ "sem evidência".
- Requer **validação experimental**. Vieses de amostragem das bases públicas podem se propagar.

## Dados de treino

Genomas virais públicos (NCBI Virus, VirusHostDB e afins). **GISAID não é redistribuído.**
Ver `docs/data_sources.md`.

## Avaliação

AUROC, AUPRC, F1, precisão, recall, especificidade e Brier, com validação cruzada estratificada por
família e **validação entre famílias** (holdout) para simular vírus emergentes.

## Como citar

Ver `README.md` (seção "Como citar").
