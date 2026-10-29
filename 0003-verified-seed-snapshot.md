# 0003 Verified seed snapshot

Status: accepted

CI and offline development need a corpus without network access. Rather than synthetic text, the seed is a small slice of the real knowledge base: paraphrased NICE recommendations, appraisal titles and dates from the NICE listing, trial results with PMIDs confirmed against PubMed, and registry records with confirmed NCT numbers. Every record names how it was verified. Statements whose status could not be confirmed are written as "check the appraisal".
