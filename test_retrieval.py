from carina.domain import Chunk, EvidenceGrade, Jurisdiction, SourceType
from carina.retrieval.bm25 import BM25Index
from carina.retrieval.embedder import HashingEmbedder
from carina.retrieval.supersession import superseding
from carina.retrieval.tokenizer import stem, tokenize


def test_clinical_tokens_kept_whole():
    tokens = tokenize("EGFR L858R and KRAS G12C, PD-L1 ≥50%, cT2a N2b, 60 mg/m2, TA654, NCT06345729")
    for expected in ("l858r", "g12c", "pdl1", "t2a", "n2b", "60mg/m2", "ta654", "nct06345729"):
        assert expected in tokens


def test_brand_names_index_as_generics():
    assert "osimertinib" in tokenize("Tagrisso")


def test_stage_forms_meet():
    assert "stageiiib" in tokenize("stage 3b disease")
    assert "stageiiib" in tokenize("Stage IIIB")


def test_concept_tokens_bridge_wording():
    assert "bm_egfr_common" in tokenize("EGFR exon 19 deletion")
    assert "bm_egfr_common" in tokenize("EGFR mutation positive")
    assert "phase_metastatic" in tokenize("stage IVA")
    assert "phase_metastatic" in tokenize("metastatic NSCLC")


def test_light_stemmer():
    assert stem("declines") == stem("decline")
    assert stem("fractions") == stem("fraction")
    assert stem("status") == "status"


def test_bm25_ranks_specific_passage_first():
    index = BM25Index()
    index.add(
        [
            ("a", "Osimertinib for EGFR exon 19 deletion advanced NSCLC"),
            ("b", "Pembrolizumab for PD-L1 high NSCLC"),
            ("c", "Alectinib for ALK positive NSCLC"),
        ]
    )
    assert index.search("osimertinib exon 19", 3)[0][0] == "a"


def test_hashing_embedder_is_normalised_and_deterministic():
    emb = HashingEmbedder(256)
    first, second = emb.embed(["sotorasib KRAS G12C"]), emb.embed(["sotorasib KRAS G12C"])
    assert abs(float((first[0] ** 2).sum()) - 1.0) < 1e-5
    assert (first == second).all()


def test_supersession_graph():
    chunk = Chunk(
        chunk_id="x::0",
        doc_id="x",
        text="t",
        title="NICE TA761: adjuvant osimertinib",
        url="u",
        source=SourceType.NICE_APPRAISAL,
        identifiers={"nice": "TA761"},
        evidence_grade=EvidenceGrade.UK_NATIONAL_GUIDANCE,
        jurisdiction=Jurisdiction.UK,
    )
    assert superseding(chunk) == "TA1043"


def test_hybrid_prefers_matching_setting(container):
    from carina.clinical.understanding import understand

    qu = understand("first line options for metastatic EGFR exon 19 deletion NSCLC")
    result = container.retriever.retrieve(
        qu.retrieval_query(), biomarkers=qu.biomarkers, setting=qu.setting, rerank_query=qu.precision_query(), expansions=" ".join(qu.expansions)
    )
    top = result.results[0]
    assert "adjuvant" not in top.chunk.metadata.get("settings", [])


def test_superseded_guidance_is_demoted_and_labelled(container):
    result = container.retriever.retrieve("adjuvant osimertinib TA761 Cancer Drugs Fund")
    flagged = [r for r in result.results if r.chunk.doc_id == "seed:nice:ta761"]
    assert flagged and flagged[0].superseded
