# 0001 Hybrid retrieval with clinical priors

Status: accepted

Dense embeddings blur exactly the tokens oncology depends on (L858R, G12C, TA654, N2b), while BM25 alone misses paraphrase. We fuse both with reciprocal rank fusion, rerank, then scale the score by clinical priors: evidence grade, recency for research, UK jurisdiction, biomarker match or conflict, treatment setting match or conflict, histology match or conflict, and a penalty for superseded guidance. Priors multiply relevance rather than add to it, so provenance cannot lift an irrelevant passage above a relevant one.
