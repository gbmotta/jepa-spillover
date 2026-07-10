#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
JEPA-Spillover — validação biológica do ranking e dos labels
=============================================================================
Projeto : JEPA-Spillover (PDJ / IAM — Fiocruz PE)
Módulo  : scripts/validate_biology.py

Propósito
---------
Audita o ranking de priorização e os ``spillover_label`` contra conhecimento
estabelecido (WHO/CDC/ICTV), em três camadas:

  1. Sanidade — posição/label de vírus de referência (SARS, Ebola, Nipah…)
  2. Auditoria — label=0 em vírus sabidamente humanos (erro de curadoria)
  3. Roadmap — SpillOver / PREDICT / validação retrospectiva (documentado)

Entradas
--------
- ``results/rankings/virus_priority_ranking.csv`` (após ``evaluate``)
- ``data/processed/dataset.parquet`` (após ``curate``)

Saídas
------
- ``results/validation/known_pathogens_audit.csv``
- ``results/validation/label_errors.csv``
- ``results/validation/ranking_quality.json``

Uso
---
    python scripts/validate_biology.py
    python scripts/validate_biology.py --debug
=============================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jepa_spillover.logger import get_logger, set_log_level  # noqa: E402

log = get_logger("scripts.validate_biology")

# ── Conhecimento a priori: vírus com risco humano CONFIRMADO ────────────────
# Fonte: WHO, CDC, ICTV, literatura (não é predição — é ground truth)
KNOWN_HUMAN_PATHOGENS: dict[str, dict] = {
    # Coronaviridae
    "SARS-CoV-2":         {"family": "Coronaviridae", "risk": "muito alto", "pandemic": True},
    "SARS-CoV":           {"family": "Coronaviridae", "risk": "muito alto"},
    "MERS-CoV":           {"family": "Coronaviridae", "risk": "alto"},
    "HCoV-229E":          {"family": "Coronaviridae", "risk": "baixo"},
    # Filoviridae
    "Ebola":              {"family": "Filoviridae",   "risk": "muito alto"},
    "Marburg":            {"family": "Filoviridae",   "risk": "muito alto"},
    # Paramyxoviridae
    "Nipah":              {"family": "Paramyxoviridae","risk": "muito alto"},
    "Hendra":             {"family": "Paramyxoviridae","risk": "alto"},
    "Measles":            {"family": "Paramyxoviridae","risk": "alto"},
    # Orthomyxoviridae
    "H5N1":               {"family": "Orthomyxoviridae","risk": "alto"},
    "H1N1":               {"family": "Orthomyxoviridae","risk": "alto", "pandemic": True},
    "H7N9":               {"family": "Orthomyxoviridae","risk": "alto"},
    # Arenaviridae
    "Lassa":              {"family": "Arenaviridae",  "risk": "alto"},
    "Junin":              {"family": "Arenaviridae",  "risk": "alto"},
    "Machupo":            {"family": "Arenaviridae",  "risk": "alto"},
    # Flaviviridae
    "Dengue":             {"family": "Flaviviridae",  "risk": "alto"},
    "Zika":               {"family": "Flaviviridae",  "risk": "alto"},
    "West Nile":          {"family": "Flaviviridae",  "risk": "moderado"},
    "Yellow fever":       {"family": "Flaviviridae",  "risk": "alto"},
    # Nairoviridae / Phenuiviridae
    "Crimean-Congo":      {"family": "Nairoviridae",  "risk": "muito alto"},
    "Rift Valley":        {"family": "Phenuiviridae", "risk": "alto"},
    # Togaviridae
    "Chikungunya":        {"family": "Togaviridae",   "risk": "alto"},
    "Eastern equine":     {"family": "Togaviridae",   "risk": "alto"},
    # Rhabdoviridae
    "Rabies":             {"family": "Rhabdoviridae", "risk": "muito alto"},
}

KNOWN_ANIMAL_ONLY: dict[str, dict] = {
    "Bat coronavirus RaTG13": {"family": "Coronaviridae",   "note": "reservatório, sem infecção humana"},
    "Canine distemper":        {"family": "Paramyxoviridae", "note": "cão, não infecta humanos"},
    "Equine influenza":        {"family": "Orthomyxoviridae","note": "equino, raro em humanos"},
}


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    rank_path = ROOT / "results" / "rankings" / "virus_priority_ranking.csv"
    ds_path = ROOT / "data" / "processed" / "dataset.parquet"
    if not rank_path.exists():
        raise FileNotFoundError(f"Ranking não encontrado: {rank_path} — rode 'evaluate' antes.")
    if not ds_path.exists():
        raise FileNotFoundError(f"Dataset não encontrado: {ds_path} — rode 'curate' antes.")
    log.info("Carregando ranking=%s dataset=%s", rank_path, ds_path)
    rank = pd.read_csv(rank_path)
    df = pd.read_parquet(ds_path, columns=["accession", "description", "host", "source"])
    merged = rank.merge(df, on="accession", how="left")
    log.info("Merge: %d linhas no ranking, %d no dataset", len(rank), len(df))
    return merged, df


def validate_known_pathogens(merged: pd.DataFrame) -> pd.DataFrame:
    """Camada 1: verifica posição e label dos vírus de referência."""
    n = len(merged)
    rows = []
    for virus, info in tqdm(KNOWN_HUMAN_PATHOGENS.items(), desc="Sanidade", unit="vírus", ncols=90):
        hits = merged[merged["description"].str.contains(virus, case=False, na=False)]
        if hits.empty:
            rows.append({"virus": virus, "family": info["family"], "risco_real": info["risk"],
                         "n_seqs": 0, "melhor_rank": None, "pct_top": None,
                         "label_correto": None, "label_obtido": None, "status": "❌ NÃO ENCONTRADO"})
            log.debug("[%s] não encontrado no dataset", virus)
            continue
        best = hits.sort_values("priority_score", ascending=False).iloc[0]
        rank_pos = int((merged["priority_score"] >= best["priority_score"]).sum())
        pct = 100 * rank_pos / n
        label_obtido = best["spillover_label"]
        label_correto = 1  # todos os KNOWN_HUMAN_PATHOGENS devem ser 1
        if rank_pos <= 0.05 * n and label_obtido == 1:
            status = "✅ OK"
        elif rank_pos <= 0.20 * n and label_obtido == 1:
            status = "⚠️  Rank baixo"
        elif label_obtido != 1:
            status = "❌ Label errado"
        else:
            status = "❌ Rank muito baixo"
        rows.append({
            "virus": virus, "family": info["family"], "risco_real": info["risk"],
            "n_seqs": len(hits), "melhor_rank": rank_pos, "pct_top": round(pct, 1),
            "label_correto": label_correto, "label_obtido": label_obtido,
            "status": status,
        })
        log.debug("[%s] rank=%d (%.1f%%) label=%s status=%s", virus, rank_pos, pct, label_obtido, status)
    return pd.DataFrame(rows)


def audit_label_errors(merged: pd.DataFrame) -> pd.DataFrame:
    """Camada 2: detecta sequências com label=0 mas vírus sabidamente humanos."""
    errors = []
    for virus, info in tqdm(KNOWN_HUMAN_PATHOGENS.items(), desc="Audit labels", unit="vírus", ncols=90):
        wrong = merged[
            merged["description"].str.contains(virus, case=False, na=False) &
            (merged["spillover_label"] == 0)
        ]
        for _, row in wrong.iterrows():
            errors.append({
                "accession": row["accession"],
                "virus_ref": virus,
                "family": info["family"],
                "risco_real": info["risk"],
                "host_descricao": row.get("host", ""),
                "description": str(row.get("description", ""))[:80],
                "problema": "label=0 mas vírus reconhecidamente infecta humanos",
                "causa_provavel": "sequência de animal reservoir (label por host da sequência, não da espécie)",
            })
    log.info("Auditoria de labels: %d erros potenciais", len(errors))
    return pd.DataFrame(errors)


def compute_ranking_quality(result: pd.DataFrame) -> dict:
    """Métricas resumo da qualidade do ranking."""
    found = result[result["n_seqs"] > 0]
    ok    = found[found["status"].str.startswith("✅")]
    warn  = found[found["status"].str.startswith("⚠️")]
    err   = found[found["status"].str.startswith("❌")]

    recall_20 = len(found[found["pct_top"] <= 20]) / max(len(found), 1)

    return {
        "n_referencia": len(KNOWN_HUMAN_PATHOGENS),
        "encontrados_dataset": len(found),
        "status_ok": len(ok),
        "status_aviso": len(warn),
        "status_erro": len(err),
        "recall_at_20pct": round(recall_20, 3),
        "mediana_rank_pct": round(found["pct_top"].median(), 1) if len(found) else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validação biológica do ranking JEPA-Spillover")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    if args.debug:
        os.environ["JEPA_LOG_LEVEL"] = "DEBUG"
        set_log_level("DEBUG")

    log.info("=== Validação biológica ===")
    merged, _ = load_data()

    log.info("CAMADA 1 — Sanidade: vírus de referência vs ranking/label")
    result = validate_known_pathogens(merged)
    # Tabela humana no stdout (produto); detalhes no log
    print(result[["virus", "family", "risco_real", "n_seqs", "pct_top",
                   "label_obtido", "status"]].to_string(index=False))

    quality = compute_ranking_quality(result)
    log.info("Resumo: %d OK | %d aviso | %d erro | Recall@20%%=%.1f%% | mediana top %.1f%%",
             quality["status_ok"], quality["status_aviso"], quality["status_erro"],
             100 * quality["recall_at_20pct"], quality["mediana_rank_pct"] or float("nan"))

    log.info("CAMADA 2 — Auditoria de labels incorretos")
    errors = audit_label_errors(merged)
    if errors.empty:
        log.info("Nenhum erro de label detectado.")
    else:
        log.warning("%d sequências com label=0 mas vírus sabidamente humanos", len(errors))
        print(errors[["accession", "virus_ref", "risco_real", "host_descricao", "causa_provavel"]].to_string(index=False))

    log.info("CAMADA 3 — Próximos passos de validação formal (SpillOver/PREDICT/retrospectiva)")

    out = ROOT / "results" / "validation"
    out.mkdir(parents=True, exist_ok=True)
    result.to_csv(out / "known_pathogens_audit.csv", index=False)
    errors.to_csv(out / "label_errors.csv", index=False)
    (out / "ranking_quality.json").write_text(json.dumps(quality, indent=2), encoding="utf-8")
    log.info("Resultados salvos em %s", out)


if __name__ == "__main__":
    main()
