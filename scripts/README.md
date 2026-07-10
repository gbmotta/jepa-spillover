# Scripts — JEPA-Spillover

Documentação dos utilitários em `scripts/`. Todos os módulos Python possuem
cabeçalho detalhado (propósito, entradas/saídas, uso, segurança). Os shells
seguem o mesmo padrão em comentários iniciais.

## Visão geral

| Script | Função |
|--------|--------|
| `_utils.py` | Download seguro, SHA-256, manifestos JSON |
| `download_all.sh` | Orquestra downloads públicos (lote 1) |
| `download_ncbi_virus.py` | NCBI Entrez — lote 1 (famílias do config) |
| `download_ncbi_batch2.py` | NCBI Entrez — lote 2 (famílias extras) |
| `download_virushostdb.py` | VirusHostDB (vírus–hospedeiro) |
| `download_taxonomy.py` | NCBI taxdump (+ extração segura) |
| `download_intact_virushost.py` | IntAct filtrado vírus–hospedeiro |
| `download_virhostnet.py` | VirHostNet via PSICQUIC / fallbacks |
| `download_gisaid.py` | Ingestão de FASTA GISAID (download **manual**) |
| `run_pipeline.sh` | Pipeline completo curate→…→evaluate |
| `resume.sh` | Retomada pós-reinício (train + pós-processamento) |
| `post_jepa.sh` | Monitora treino e dispara pós-pipeline |
| `kmer_sweep.py` | Benchmark de k (justifica k=4) |
| `validate_biology.py` | Auditoria biológica do ranking/labels |
| `gen_*_docx.py` | Documentos da submissão PDJ |
| `push_to_github.sh` | Publicação no GitHub |
| `push_to_huggingface.sh` | Publicação no Hugging Face Hub |

## Convenções

- **Logging:** `jepa_spillover.logger` (`JEPA_LOG_LEVEL`, `--debug` → `set_log_level`).
- **Segredos:** `config/secrets.yaml` (gitignored) ou `NCBI_API_KEY` / `NCBI_EMAIL`.
- **Progresso:** `tqdm` em loops longos (downloads, treino, sweeps).
- **Proveniência:** todo download grava `*.manifest.json` (URL, SHA-256, n_records).

## Fluxo típico de dados

```text
download_*.py  →  data/raw|external/
       ↓
cli curate     →  data/processed/dataset.parquet
       ↓
cli features   →  embeddings.npz
cli train      →  jepa_genomic.pt + jepa_embeddings.npz
       ↓
cli finetune / evaluate / validate_biology.py
```

## Documentos PDJ

```bash
python scripts/gen_subprojeto_docx.py
python scripts/gen_projeto_orientador_preenchido.py
python scripts/gen_carta_anuencia_docx.py
python scripts/gen_checklist_docx.py
# PDF (exemplo):
libreoffice --headless --convert-to pdf submissao_pdj/*.docx --outdir submissao_pdj
```

## Segurança (checklist rápido)

- [ ] Não versionar `config/secrets.yaml` nem tokens HF/GitHub
- [ ] Não redistribuir sequências GISAID
- [ ] Rotacionar API key NCBI se já foi commitada no passado
- [ ] Preferir `weights_only` / `load_npz` seguros (já no pacote `jepa_spillover.security`)
