# ============================================================
# JEPA-Spillover — atalhos de execução
# Uso: make <alvo>   (ex.: make setup, make download, make pipeline)
# ============================================================
.DEFAULT_GOAL := help
PY := python
CONFIG := config/config.yaml

.PHONY: help
help:  ## Mostra esta ajuda
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: setup
setup:  ## Cria o ambiente conda e instala o pacote
	conda env create -f environment.yml || conda env update -f environment.yml
	$(PY) -m pip install -e .

.PHONY: setup-pip
setup-pip:  ## Instala dependências via pip (sem conda)
	$(PY) -m pip install -r requirements.txt && $(PY) -m pip install -e .

.PHONY: download
download:  ## Baixa todas as bases de dados públicas
	bash scripts/download_all.sh

.PHONY: curate
curate:  ## Curadoria e padronização dos dados
	$(PY) -m jepa_spillover.cli curate --config $(CONFIG)

.PHONY: features
features:  ## Gera k-mers e embeddings
	$(PY) -m jepa_spillover.cli features --config $(CONFIG)

.PHONY: train
train:  ## Pré-treina a JEPA genômica
	$(PY) -m jepa_spillover.cli train --config $(CONFIG)

.PHONY: finetune
finetune:  ## Fine-tuning supervisionado para risco de spillover
	$(PY) -m jepa_spillover.cli finetune --config $(CONFIG)

.PHONY: evaluate
evaluate:  ## Avalia, compara baselines e gera ranking
	$(PY) -m jepa_spillover.cli evaluate --config $(CONFIG)

.PHONY: pipeline
pipeline:  ## Executa o pipeline completo de ponta a ponta
	bash scripts/run_pipeline.sh

.PHONY: dashboard
dashboard:  ## Sobe o dashboard interativo (Streamlit)
	streamlit run dashboard/app.py

.PHONY: test
test:  ## Roda os testes
	pytest

.PHONY: lint
lint:  ## Verifica e formata o código com ruff
	ruff check src scripts tests && ruff format src scripts tests

.PHONY: clean
clean:  ## Remove artefatos intermediários (mantém data/raw)
	rm -rf data/interim/* data/processed/* results/figures/* results/metrics/* results/rankings/*

.PHONY: push-github
push-github:  ## Sobe o repositório para o GitHub
	bash scripts/push_to_github.sh

.PHONY: push-hf
push-hf:  ## Sobe modelos/dataset para o Hugging Face Hub
	bash scripts/push_to_huggingface.sh
