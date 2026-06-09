# Cronograma e roadmap — JEPA-Spillover (12 meses)

```mermaid
gantt
    title Cronograma do subprojeto (PDJ/Fiocruz — 12 meses)
    dateFormat  YYYY-MM-DD
    axisFormat  M%m

    section Dados
    Levantamento de bases e pipeline        :a1, 2026-01-01, 30d
    Coleta e curadoria inicial              :a2, after a1, 30d
    Padronização e banco integrado v1       :a3, after a2, 30d

    section Representações
    k-mers, embeddings e baselines          :b1, after a3, 30d

    section JEPA genômica
    Implementação                           :c1, after b1, 30d
    Treinamento e ajuste                    :c2, after c1, 30d

    section Vírus-hospedeiro
    Extensão vírus-hospedeiro               :d1, after c2, 30d
    Integração ecológica/multimodal         :d2, after d1, 30d

    section Predição e validação
    Fine-tuning risco de spillover          :e1, after d2, 30d
    Validação e comparação                  :e2, after e1, 30d
    Interpretabilidade, ablação e ranking   :e3, after e2, 30d

    section Disseminação
    Repositório, manuscrito e relatório     :f1, after e3, 30d
```

| Mês | Atividades principais | Produtos esperados | Meta |
|----:|---|---|:--:|
| 1 | Levantamento de bases, critérios de inclusão, desenho do pipeline | Plano técnico + lista de bases | 1 |
| 2 | Coleta e curadoria inicial de genomas e metadados | Base preliminar curada | 1 |
| 3 | Padronização taxonômica, dedup, estruturação | Banco integrado v1 | 1 |
| 4 | k-mers, embeddings genômicos, baselines | Matrizes de atributos + baselines | 2 |
| 5 | Implementação da JEPA genômica | Protótipo funcional | 3 |
| 6 | Treinamento e ajuste da JEPA genômica | Embeddings virais preliminares | 3 |
| 7 | Extensão vírus-hospedeiro | Modelo JEPA vírus-hospedeiro | 4 |
| 8 | Integração ecológica/interacional exploratória | Espaço latente multimodal preliminar | 4 |
| 9 | Fine-tuning supervisionado para risco | Modelo preditivo + métricas iniciais | 5 |
| 10 | Validação e comparação (LSTM/Transformer/k-mers) | Relatório comparativo | 5 |
| 11 | Interpretabilidade, ablação, UMAP/t-SNE, ranking | Figuras, rankings, interpretação | 5 |
| 12 | Repositório, manuscrito, relatório final | Manuscrito + repositório + relatório | 6 |

## Marcos (milestones)

- **M3** — Banco integrado v1 disponível e documentado.
- **M6** — JEPA genômica treinada com embeddings preliminares avaliados.
- **M9** — Primeiro modelo de risco de spillover com métricas.
- **M12** — Repositório público + manuscrito em preparação/submissão.

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Rótulos escassos/enviesados | Núcleo auto-supervisionado; validação entre famílias |
| Dados ecológicos incompletos | Integração incremental; multimodal como exploratório |
| Custo computacional (Transformers) | Baseline k-mer/CNN; uso de GPU quando disponível; blocos menores |
| Vazamento de informação na avaliação | Particionamento estratificado + holdout de famílias inteiras |
