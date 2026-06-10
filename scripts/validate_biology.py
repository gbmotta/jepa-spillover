"""Validação biológica do ranking e labels contra conhecimento estabelecido.

Três camadas:
  1. Sanidade: vírus de referência com risco humano conhecido
  2. Label audit: detecta sequências com label=0 mas vírus sabidamente humanos
  3. Comparação com SpillOver (EcoHealth Alliance) se disponível
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

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
    rank = pd.read_csv(ROOT / "results" / "rankings" / "virus_priority_ranking.csv")
    df   = pd.read_parquet(ROOT / "data" / "processed" / "dataset.parquet",
                           columns=["accession", "description", "host", "source"])
    return rank.merge(df, on="accession", how="left"), df


def validate_known_pathogens(merged: pd.DataFrame) -> pd.DataFrame:
    """Camada 1: verifica posição e label dos vírus de referência."""
    n = len(merged)
    rows = []
    for virus, info in KNOWN_HUMAN_PATHOGENS.items():
        hits = merged[merged["description"].str.contains(virus, case=False, na=False)]
        if hits.empty:
            rows.append({"virus": virus, "family": info["family"], "risco_real": info["risk"],
                         "n_seqs": 0, "melhor_rank": None, "pct_top": None,
                         "label_correto": None, "label_obtido": None, "status": "❌ NÃO ENCONTRADO"})
            continue
        best = hits.sort_values("priority_score", ascending=False).iloc[0]
        rank_pos = int((merged["priority_score"] >= best["priority_score"]).sum())
        pct = 100 * rank_pos / n
        label_obtido = best["spillover_label"]
        label_correto = 1  # todos os KNOWN_HUMAN_PATHOGENS devem ser 1
        # Avaliar
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
    return pd.DataFrame(rows)


def audit_label_errors(merged: pd.DataFrame) -> pd.DataFrame:
    """Camada 2: detecta sequências com label=0 mas vírus sabidamente humanos."""
    errors = []
    for virus, info in KNOWN_HUMAN_PATHOGENS.items():
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
    return pd.DataFrame(errors)


def compute_ranking_quality(result: pd.DataFrame) -> dict:
    """Métricas resumo da qualidade do ranking."""
    found = result[result["n_seqs"] > 0]
    ok    = found[found["status"].str.startswith("✅")]
    warn  = found[found["status"].str.startswith("⚠️")]
    err   = found[found["status"].str.startswith("❌")]

    # Recall@20%: fração dos vírus de referência no top 20%
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


def main():
    print("Carregando dados...")
    merged, _ = load_data()

    print("\n" + "=" * 70)
    print("CAMADA 1 — Sanidade: vírus de referência vs ranking/label")
    print("=" * 70)
    result = validate_known_pathogens(merged)
    print(result[["virus", "family", "risco_real", "n_seqs", "pct_top",
                   "label_obtido", "status"]].to_string(index=False))

    quality = compute_ranking_quality(result)
    print(f"\nResumo: {quality['status_ok']} ✅ | {quality['status_aviso']} ⚠️  | {quality['status_erro']} ❌")
    print(f"Recall@20%: {quality['recall_at_20pct']:.1%} (fração de vírus de referência no top 20% do ranking)")
    print(f"Mediana posição no ranking: top {quality['mediana_rank_pct']:.1f}%")

    print("\n" + "=" * 70)
    print("CAMADA 2 — Auditoria de labels incorretos")
    print("=" * 70)
    errors = audit_label_errors(merged)
    if errors.empty:
        print("Nenhum erro de label detectado.")
    else:
        print(f"{len(errors)} sequências com label=0 mas vírus sabidamente humanos:")
        print(errors[["accession", "virus_ref", "risco_real", "host_descricao", "causa_provavel"]].to_string(index=False))

    print("\n" + "=" * 70)
    print("CAMADA 3 — O que precisamos para validação formal")
    print("=" * 70)
    print("""
  A. SpillOver Risk Tool (EcoHealth Alliance, 2020 — DOI: 10.1371/journal.pntd.0008487)
     → Compara ranking do nosso modelo vs score publicado para ~900 vírus mamíferos
     → Pearson r e Spearman rho entre nossos scores e os deles

  B. PREDICT zoonotic virus database (USAID)
     → Lista de ~160 vírus confirmados como zoonóticos
     → Calcular precision@K e recall@K do nosso ranking

  C. Validação retrospectiva
     → Treinar com dados pré-2019, avaliar se SARS-CoV-2 ficaria no top 5%
     → Treinar com dados pré-2013, avaliar se MERS ficaria no top 5%

  D. Comparação com GenBank host annotation
     → Para cada TaxID viral, verificar se alguma sequência GenBank tem [host=Homo sapiens]
     → Se sim → label deve ser 1 (independente do host da sequência específica)
    """)

    # Salvar resultados
    out = ROOT / "results" / "validation"
    out.mkdir(parents=True, exist_ok=True)
    result.to_csv(out / "known_pathogens_audit.csv", index=False)
    errors.to_csv(out / "label_errors.csv", index=False)
    (out / "ranking_quality.json").write_text(json.dumps(quality, indent=2))
    print(f"Resultados salvos em {out}")


if __name__ == "__main__":
    main()
