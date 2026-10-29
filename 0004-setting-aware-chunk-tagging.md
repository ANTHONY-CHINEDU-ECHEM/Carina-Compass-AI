# 0004 Setting aware chunk tagging

Status: accepted

NG122 section 1.6 covers neoadjuvant, adjuvant and consolidation treatment in one document. Document level tags made every chunk look relevant to every setting. Tags are now computed per chunk from its own text, with biomarker tags falling back to the document because results sections rarely repeat the mutation studied. Biomarker detection ignores negated mentions such as "no EGFR or ALK alteration".
