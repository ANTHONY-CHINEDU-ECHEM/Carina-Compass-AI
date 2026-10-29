import json
import xml.etree.ElementTree as ET

from carina.domain import Document, EvidenceGrade, SourceType
from ingestion.processing.chunker import chunk_document
from ingestion.processing.cleaner import clean_text
from ingestion.processing.dedup import deduplicate, hamming, simhash
from ingestion.processing.grader import grade
from ingestion.seed import load_seed_documents
from ingestion.sources.civic import parse_tsv
from ingestion.sources.clinicaltrials import parse_study
from ingestion.sources.openfda import parse_label
from ingestion.sources.pubmed import parse_article


def test_cleaner_preserves_clinical_tokens():
    text = clean_text("<p>PD-L1 ≥ 50%, 75 mg/m², HR 0.46 &amp; exon 19</p>")
    assert "≥" in text and "mg/m2" in text and "0.46" in text and "&" in text


def test_chunker_respects_sections_and_tags_each_chunk():
    doc = Document(
        doc_id="d",
        source=SourceType.PUBMED,
        title="T",
        url="u",
        text="",
        sections=[("Design", "Adjuvant osimertinib was compared with placebo. " * 3), ("Results", "In metastatic disease the response rate was 80%. " * 3)],
    )
    chunks = list(chunk_document(doc, target_words=20, max_words=40))
    assert {c.section for c in chunks} == {"Design", "Results"}
    assert all(c.section == "Design" for c in chunks if "placebo" in c.text)
    design = next(c for c in chunks if c.section == "Design")
    assert "adjuvant" in design.metadata["settings"]


def test_simhash_collapses_near_duplicates():
    a = Document(
        doc_id="a",
        source=SourceType.PUBMED,
        title="Osimertinib trial",
        url="u",
        text="Median progression free survival was 18.9 months with osimertinib versus 10.2 months.",
    )
    b = a.model_copy(update={"doc_id": "b", "evidence_grade": EvidenceGrade.RANDOMISED_TRIAL})
    assert hamming(simhash(a.text), simhash(b.text)) == 0
    unique, collapsed = deduplicate([a, b])
    assert collapsed == 1
    assert unique[0].evidence_grade == EvidenceGrade.RANDOMISED_TRIAL


def test_grading():
    assert grade(SourceType.PUBMED, ["Meta-Analysis"]) == EvidenceGrade.SYSTEMATIC_REVIEW
    assert grade(SourceType.PUBMED, ["Randomized Controlled Trial"]) == EvidenceGrade.RANDOMISED_TRIAL
    assert grade(SourceType.NICE_APPRAISAL) == EvidenceGrade.UK_NATIONAL_GUIDANCE
    assert grade(SourceType.CIVIC, civic_level="B") == EvidenceGrade.RANDOMISED_TRIAL


PUBMED_XML = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article>
<Journal><ISOAbbreviation>N Engl J Med</ISOAbbreviation><JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue></Journal>
<ArticleTitle>Adjuvant osimertinib in EGFR mutated NSCLC</ArticleTitle>
<Abstract><AbstractText Label="RESULTS">Disease free survival improved (hazard ratio 0.20).</AbstractText></Abstract>
<AuthorList><Author><AffiliationInfo><Affiliation>Royal Marsden, London, United Kingdom</Affiliation></AffiliationInfo></Author></AuthorList>
<PublicationTypeList><PublicationType>Randomized Controlled Trial</PublicationType></PublicationTypeList>
</Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1/x</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""


def test_pubmed_parser():
    article = ET.fromstring(PUBMED_XML).find("PubmedArticle")
    doc = parse_article(article)
    assert doc.identifiers == {"pmid": "123", "doi": "10.1/x"}
    assert doc.evidence_grade == EvidenceGrade.RANDOMISED_TRIAL
    assert doc.jurisdiction.value == "UK"
    assert "EGFR_COMMON" in doc.metadata["biomarkers"]


def test_clinicaltrials_parser():
    study = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT01234567", "briefTitle": "Sotorasib in KRAS G12C NSCLC"},
            "statusModule": {"overallStatus": "RECRUITING", "lastUpdatePostDateStruct": {"date": "2026-09-01"}, "startDateStruct": {"date": "2025-02"}},
            "descriptionModule": {"briefSummary": "A phase 3 study of sotorasib for previously treated KRAS G12C mutated NSCLC."},
            "eligibilityModule": {
                "eligibilityCriteria": "Inclusion: KRAS G12C mutation. Exclusion: active brain metastases.",
                "minimumAge": "18 Years",
                "sex": "ALL",
            },
            "designModule": {"phases": ["PHASE3"]},
            "contactsLocationsModule": {"locations": [{"facility": "The Christie", "city": "Manchester", "country": "United Kingdom"}]},
        }
    }
    doc = parse_study(study)
    assert doc.metadata["overall_status"] == "RECRUITING"
    assert doc.metadata["uk_sites"] == ["The Christie, Manchester"]
    assert "KRAS_G12C" in doc.metadata["biomarkers"]


def test_civic_parser_filters_disease_and_resolves_columns():
    tsv = "evidence_id\tmolecular_profile\tdisease\ttherapies\tevidence_type\tevidence_direction\tsignificance\tevidence_level\tevidence_statement\tcitation_id\tsource_type\tevidence_status\n"
    tsv += "1\tEGFR L858R\tLung Non-small Cell Carcinoma\tOsimertinib\tPredictive\tSupports\tSensitivity/Response\tA\tPatients with EGFR L858R responded to osimertinib in a phase 3 trial with longer survival.\t29151359\tPubMed\taccepted\n"
    tsv += "2\tBRAF V600E\tMelanoma\tVemurafenib\tPredictive\tSupports\tSensitivity/Response\tA\tMelanoma statement that should be filtered out by disease name entirely.\t1\tPubMed\taccepted\n"
    docs = list(parse_tsv(tsv, ["Lung Non-small Cell Carcinoma"]))
    assert len(docs) == 1
    assert docs[0].identifiers["pmid"] == "29151359"
    assert docs[0].evidence_grade == EvidenceGrade.SYSTEMATIC_REVIEW


def test_openfda_parser_never_indexes_dosage():
    label = {
        "set_id": "abc",
        "openfda": {"brand_name": ["TAGRISSO"]},
        "dosage_and_administration": ["80 mg orally once daily"],
        "warnings_and_cautions": ["Interstitial lung disease and QTc prolongation have occurred."],
    }
    doc = parse_label(label, "osimertinib")
    assert "80 mg" not in doc.text
    assert doc.jurisdiction.value == "US"


def test_seed_snapshot_is_real_and_traceable(settings):
    docs = load_seed_documents(settings.seed_dir)
    assert len(docs) >= 80
    for doc in docs:
        assert doc.url.startswith("https://")
        assert doc.metadata.get("verified")
    pmids = {d.identifiers.get("pmid") for d in docs if d.source == SourceType.PUBMED}
    assert {"29151359", "32955177", "27718847", "29658856", "35403841", "34555333", "38598794", "34096690"} <= pmids


def test_seed_files_are_valid_jsonl(settings):
    for path in settings.seed_dir.glob("*.jsonl"):
        for line in path.read_text().splitlines():
            json.loads(line)
