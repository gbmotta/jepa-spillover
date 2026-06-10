"""Curadoria de sequências virais: QC, limpeza e padronização.

Lê FASTA de `data/raw/` (quando disponível) ou gera dados sintéticos, aplica
controle de qualidade e grava um dataset tabular em `data/processed/dataset.parquet`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from ..config import Config
from ..logger import get_logger

log = get_logger(__name__)
VALID_BASES = set("ACGTU")


def _read_fasta(path: Path):
    """Itera (header, sequência) de um arquivo FASTA sem dependências externas."""
    log.debug("Lendo FASTA: %s", path)
    header, chunks = None, []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip()
            if line.startswith(">"):
                if header is not None:
                    yield header, "".join(chunks)
                header, chunks = line[1:], []
            else:
                chunks.append(line.upper())
    if header is not None:
        yield header, "".join(chunks)


def ambiguous_fraction(seq: str) -> float:
    if not seq:
        return 1.0
    bad = sum(1 for c in seq if c not in VALID_BASES)
    return bad / len(seq)


def passes_qc(seq: str, *, min_length: int, max_ambiguous: float) -> bool:
    if len(seq) < min_length:
        log.debug("Sequência rejeitada por comprimento (%d < %d)", len(seq), min_length)
        return False
    frac = ambiguous_fraction(seq)
    if frac > max_ambiguous:
        log.debug("Sequência rejeitada por ambiguidade (%.3f > %.3f)", frac, max_ambiguous)
        return False
    return True


_HOST_PATTERNS: list[tuple[str, str]] = [
    # Explícito: [host=Homo sapiens]
    (r"\[host=([^\]]+)\]",                              "group1"),
    # Padrão NCBI Influenza: (A/human/...)
    (r"\([A-Z]/?(human|Homo[_ ]sapiens)/",              "human"),
    # SARS-CoV-2 / vírus com /human/ no nome
    (r"/human/",                                         "human"),
    # Humano por outros termos
    (r"\b(human|Homo sapiens|H\.?\s*sapiens|patient|clinical)\b", "human"),
    # Animais comuns
    (r"\b(bat|morcego|chiroptera)\b",                   "bat"),
    (r"\b(chicken|gallus|poultry|avian|duck|goose|bird)\b", "avian"),
    (r"\b(pig|swine|porcine|sus scrofa)\b",             "swine"),
    (r"\b(camel|dromedary|camelus)\b",                  "camel"),
    (r"\b(rodent|mouse|rat|murinae|rodentia)\b",        "rodent"),
    (r"\b(equine|horse|equus)\b",                       "equine"),
]


def _extract_host(header: str) -> str | None:
    """Extrai o hospedeiro do header FASTA do NCBI com múltiplos padrões."""
    h = header
    for pattern, result in _HOST_PATTERNS:
        m = re.search(pattern, h, re.IGNORECASE)
        if m:
            if result == "group1":
                return m.group(1).strip()
            return result
    return None


def load_raw_fastas(cfg: Config) -> pd.DataFrame:
    """Carrega FASTAs do NCBI Virus e do GISAID (quando disponível)."""
    all_dfs: list[pd.DataFrame] = []

    # --- NCBI Virus ---
    ncbi_dir = cfg.resolve("data_raw") / "ncbi_virus"
    fastas = sorted(ncbi_dir.glob("*.fasta"))
    log.info("NCBI FASTA encontrados em %s: %d arquivos", ncbi_dir, len(fastas))
    rows: list[dict] = []
    for fasta in tqdm(fastas, desc="NCBI FASTA", unit="arquivo", ncols=90):
        family = fasta.stem
        n_before = len(rows)
        for header, seq in _read_fasta(fasta):
            acc = header.split()[0]
            host = _extract_host(header)
            rows.append({
                "accession": acc,
                "family": family,
                "sequence": seq.replace("U", "T"),
                "length": len(seq),
                "host": host,
                "description": header,
                "source": "ncbi_virus",
            })
        log.debug("[NCBI/%s] %d sequências carregadas", family, len(rows) - n_before)
    if rows:
        all_dfs.append(pd.DataFrame(rows))

    # --- GISAID (EpiCoV, EpiArbo, EpiNiV, EpiFlu, EpiRSV) ---
    gisaid_dir = cfg.resolve("data_raw") / "gisaid"
    gisaid_fastas = sorted(gisaid_dir.glob("*.fasta")) if gisaid_dir.exists() else []
    if gisaid_fastas:
        log.info("GISAID FASTA encontrados em %s: %d arquivos", gisaid_dir, len(gisaid_fastas))

        # Mapeamento base GISAID → família taxonômica do pipeline
        _DB_FAMILY = {
            "EpiCoV":  "Coronaviridae",
            "EpiFlu":  "Orthomyxoviridae",
            "EpiRSV":  "Paramyxoviridae",
            "EpiNiV":  "Paramyxoviridae",
            "EpiArbo": "Flaviviridae",
        }
        g_rows: list[dict] = []
        for fasta in tqdm(gisaid_fastas, desc="GISAID FASTA", unit="arquivo", ncols=90):
            db = fasta.stem  # ex.: EpiCoV, EpiArbo
            family = _DB_FAMILY.get(db, db)
            n_before = len(g_rows)
            for header, seq in _read_fasta(fasta):
                parts = header.split("|")
                acc = parts[0].strip().split()[0]
                host = None
                if m := re.search(r"Human|Homo sapiens", header, re.I):
                    host = "Homo sapiens"
                elif m := re.search(r"\b(bat|morcego|chiroptera)\b", header, re.I):
                    host = "Chiroptera"
                elif m := re.search(r"\b(camel|dromedary)\b", header, re.I):
                    host = "Camelidae"
                g_rows.append({
                    "accession": acc,
                    "family": family,
                    "sequence": seq.replace("U", "T"),
                    "length": len(seq),
                    "host": host,
                    "description": header,
                    "source": f"gisaid_{db.lower()}",
                })
            log.debug("[GISAID/%s] %d sequências carregadas", db, len(g_rows) - n_before)
        if g_rows:
            all_dfs.append(pd.DataFrame(g_rows))
            log.info("GISAID: %d sequências carregadas de %d bases",
                     len(g_rows), len(gisaid_fastas))
    else:
        log.info("Nenhum FASTA GISAID encontrado em %s — usando apenas NCBI", gisaid_dir)

    if not all_dfs:
        return pd.DataFrame()
    return pd.concat(all_dfs, ignore_index=True)


def _subsample(df: pd.DataFrame, max_per_family: int, seed: int) -> pd.DataFrame:
    """Subsample para no máximo `max_per_family` sequências por família."""
    parts = []
    for fam, grp in df.groupby("family"):
        if len(grp) > max_per_family:
            grp = grp.sample(max_per_family, random_state=seed)
            log.info("[subsample] %s: %d → %d seqs", fam, len(grp) + (len(grp) - len(grp)), max_per_family)
        parts.append(grp)
    return pd.concat(parts, ignore_index=True).sample(frac=1, random_state=seed).reset_index(drop=True)


def label_spillover(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Gera `spillover_label` e `n_hosts` a partir de 3 fontes de evidência.

    Prioridade (maior → menor confiança):
      1. Campo `host` direto: "Homo sapiens" / "human" → label=1
      2. IntAct (EMBL-EBI): taxon_id com interação proteica confirmada com humano
      3. VirusHostDB: virus com humano listado como hospedeiro

    A coluna `spillover_confidence` indica quantas fontes confirmaram (0-3).
    """
    n = len(df)
    labels = pd.Series(0, index=df.index, dtype=int)
    confidence = pd.Series(0, index=df.index, dtype=int)
    n_hosts_col = pd.Series(1, index=df.index, dtype=int)

    # ── Fonte 0: extrair host da descrição se ainda nulo ──────────────────
    if "host" in df.columns and df["host"].isna().all() and "description" in df.columns:
        log.info("Host nulo: extraindo da coluna description...")
        df = df.copy()
        df["host"] = df["description"].apply(_extract_host)
        n_extracted = df["host"].notna().sum()
        log.info("Host extraído de %d / %d sequências", n_extracted, len(df))

    # ── Fonte 1: campo host direto ─────────────────────────────────────────
    if "host" in df.columns:
        human_host = df["host"].fillna("").str.contains(
            r"homo sapiens|human", case=False, regex=True
        )
        labels[human_host] = 1
        confidence[human_host] += 1
        log.info("Fonte 1 (host direto): %d sequências com host humano", human_host.sum())
        # Sequências de hospedeiros não-humanos confirmados → explicitamente 0
        nonhuman_pattern = r"bat|avian|swine|camel|rodent|equine|chicken|pig|duck|bird"
        nonhuman = df["host"].fillna("").str.fullmatch(
            nonhuman_pattern, case=False
        ) & ~human_host
        log.info("Fonte 1 (host direto): %d sequências com host não-humano confirmado", nonhuman.sum())

    # Se temos host-level info suficiente, usar só ela (mais precisa que família)
    n_with_host = (df["host"].fillna("") != "").sum() if "host" in df.columns else 0
    use_family_level = n_with_host < 0.1 * n  # só usa família se < 10% tem host info
    log.info("Sequências com host identificado: %d / %d (%.1f%%) — family-level: %s",
             n_with_host, n, 100 * n_with_host / max(n, 1), use_family_level)

    if not use_family_level:
        # Temos host-level info suficiente → usar apenas host direto
        # Sequências sem host → NaN (excluídas do fine-tuning, usadas só no pré-treino)
        no_host = df["host"].fillna("") == ""
        labels[no_host] = -1  # sentinela para NaN
        log.info("Sequências sem host (label=NaN): %d", no_host.sum())
        df_out = df.copy()
        df_out["spillover_label"] = labels.where(labels >= 0).astype("Int64")
        df_out["spillover_confidence"] = confidence
        pos = (df_out["spillover_label"] == 1).sum()
        neg = (df_out["spillover_label"] == 0).sum()
        unk = df_out["spillover_label"].isna().sum()
        log.info("spillover_label: %d positivos | %d negativos | %d desconhecidos", pos, neg, unk)
        return df_out

    # ── Fonte 2: IntAct ────────────────────────────────────────────────────
    intact_path = cfg.resolve("data_external") / "intact" / "intact_virus_host.parquet"
    # Fallback: resolver diretamente do root
    if not intact_path.exists():
        from ..config import PROJECT_ROOT
        intact_path = PROJECT_ROOT / "data" / "external" / "intact" / "intact_virus_host.parquet"
    if intact_path.exists():
        intact = pd.read_parquet(intact_path, columns=["taxA_id", "taxB_id", "taxA_name"])
        # Vírus (taxA) com interação confirmada com humano (taxB = 9606)
        virus_taxids_human = set(
            intact.loc[
                (intact["taxB_id"] == "9606") &
                (intact["taxA_id"] != "9606") &
                (intact["taxA_id"] != "-2"),
                "taxA_id",
            ].dropna().unique()
        )
        # Mapear famílias conhecidas pelos taxon IDs do IntAct
        # Coronaviridae: 694002 (SARS), 2697049 (SARS-CoV-2), 349342 (MERS)
        # Paramyxoviridae: 12234 (Nipah), 11234 (Measles), 11161 (Hendra)
        # Orthomyxoviridae: 11520 (Influenza A), 11520+
        # Filoviridae: 11266 (Ebola), 11269 (Marburg)
        # Arenaviridae: 11619 (Lassa), 11620 (Junin)
        # Flaviviridae: 11103 (HCV), 11234 (Dengue-like)
        FAMILY_TAXIDS: dict[str, set[str]] = {
            "Coronaviridae":    {"694002", "2697049", "349342", "1335626", "693996"},
            "Paramyxoviridae":  {"12234", "11234", "11270", "11916", "12461"},
            "Orthomyxoviridae": {"11520", "11521", "11552", "197911", "641501"},
            "Filoviridae":      {"11266", "11269", "186539", "1570291"},
            "Arenaviridae":     {"11619", "11620", "11621", "11623"},
            "Flaviviridae":     {"11103", "11082", "11053", "12227"},
            "Togaviridae":      {"11036", "11041", "62462"},
            "Rhabdoviridae":    {"11292", "11295", "11286"},
        }
        intact_families_with_human = set()
        for fam, taxids in FAMILY_TAXIDS.items():
            if taxids & virus_taxids_human:
                intact_families_with_human.add(fam)

        intact_mask = df["family"].isin(intact_families_with_human)
        labels[intact_mask] = 1
        confidence[intact_mask] += 1
        log.info("Fonte 2 (IntAct): %d famílias com interação humana → %d sequências",
                 len(intact_families_with_human), intact_mask.sum())
        log.info("  Famílias IntAct: %s", sorted(intact_families_with_human))
    else:
        log.warning("IntAct não encontrado em %s — pulando", intact_path)

    # ── Fonte 3: VirusHostDB ───────────────────────────────────────────────
    vhdb_path = cfg.resolve("data_external") / "virushostdb" / "virushostdb.tsv"
    if not vhdb_path.exists():
        from ..config import PROJECT_ROOT
        vhdb_path = PROJECT_ROOT / "data" / "external" / "virushostdb" / "virushostdb.tsv"
    if vhdb_path.exists():
        try:
            vhdb = pd.read_csv(vhdb_path, sep="\t", dtype=str, on_bad_lines="skip")
            # Colunas esperadas: virus name, virus tax id, host name, host tax id
            host_col  = next((c for c in vhdb.columns if "host" in c.lower() and "tax" not in c.lower() and "name" in c.lower()), None)
            vtax_col  = next((c for c in vhdb.columns if "virus" in c.lower() and "tax" in c.lower()), None)
            vname_col = next((c for c in vhdb.columns if "virus" in c.lower() and "name" in c.lower()), None)
            if host_col:
                human_vhdb = vhdb[vhdb[host_col].fillna("").str.contains(r"homo sapiens|human", case=False)]
                n_hosts_map: dict[str, int] = {}
                if vname_col:
                    for vname, grp in vhdb.groupby(vname_col):
                        n_hosts_map[str(vname).lower()] = len(grp)
                # Famílias com vírus humanos no VirusHostDB (heurística por lineage)
                if "virus lineage" in [c.lower() for c in vhdb.columns]:
                    lin_col = next(c for c in vhdb.columns if c.lower() == "virus lineage")
                    vhdb_families = set()
                    for _, row in human_vhdb.iterrows():
                        lineage = str(row.get(lin_col, ""))
                        for fam in df["family"].unique():
                            if fam.lower() in lineage.lower():
                                vhdb_families.add(fam)
                    vhdb_mask = df["family"].isin(vhdb_families)
                    labels[vhdb_mask] = 1
                    confidence[vhdb_mask] += 1
                    log.info("Fonte 3 (VirusHostDB): %d famílias → %d sequências",
                             len(vhdb_families), vhdb_mask.sum())
                # n_hosts: amplitude de hospedeiros (proxy de promiscuidade)
                if vname_col and vtax_col:
                    host_counts = vhdb.groupby(vtax_col)[host_col].nunique()
                    log.info("VirusHostDB: %d vírus com contagem de hospedeiros", len(host_counts))
        except Exception as e:
            log.warning("Erro ao processar VirusHostDB: %s", e)
    else:
        log.warning("VirusHostDB TSV não encontrado em %s", vhdb_path)

    df_out = df.copy()
    df_out["spillover_label"] = labels.values
    df_out["spillover_confidence"] = confidence.values

    pos = labels.sum()
    log.info(
        "spillover_label: %d positivos (%.1f%%) | %d negativos | confiança média=%.2f",
        pos, 100 * pos / max(n, 1), n - pos, confidence.mean(),
    )
    return df_out


def curate(config_path: str | None = None) -> Path:
    """Executa a curadoria e grava o dataset processado."""
    cfg = Config.load(config_path)
    min_length = int(cfg.get_path("data_sources.ncbi_virus.min_length", 1000))
    max_ambiguous = float(cfg.get_path("curation.remove_ambiguous_frac", 0.01))
    max_per_family = cfg.get_path("curation.max_seqs_per_family", None)
    seed = int(cfg.get_path("project.seed", 42))
    log.info("Iniciando curadoria (min_length=%d, max_ambiguous=%.3f, max_per_family=%s)",
             min_length, max_ambiguous, max_per_family or "ilimitado")

    df = load_raw_fastas(cfg)
    if df.empty:
        log.warning("Nenhum FASTA em data/raw — gerando dataset sintético de demonstração.")
        from .synthetic import generate
        df = generate(seed=seed)
    else:
        before = len(df)
        log.info("QC: avaliando %d sequências...", before)
        mask = [
            passes_qc(s, min_length=min_length, max_ambiguous=max_ambiguous)
            for s in tqdm(df["sequence"], desc="QC", unit="seq", ncols=90)
        ]
        df = df[mask].drop_duplicates(subset="accession").reset_index(drop=True)
        log.info("QC + dedup: %d → %d sequências (removidas %d)", before, len(df), before - len(df))

        if max_per_family:
            before_sub = len(df)
            df = _subsample(df, int(max_per_family), seed)
            log.info("Subsample (max %d/família): %d → %d seqs",
                     int(max_per_family), before_sub, len(df))

    # Gerar rótulos de spillover a partir de evidências reais
    log.info("Gerando spillover_label a partir de IntAct + VirusHostDB + host direto...")
    df = label_spillover(df, cfg)

    out = cfg.resolve("data_processed")
    out.mkdir(parents=True, exist_ok=True)
    path = out / "dataset.parquet"
    df.to_parquet(path)
    log.info("Dataset salvo em %s (%d sequências, %d famílias, %d positivos spillover)",
             path, len(df), df["family"].nunique(), df["spillover_label"].sum())
    return path
