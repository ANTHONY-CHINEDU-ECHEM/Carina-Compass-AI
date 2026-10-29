import type { PatientContext } from "../types";

const BIOMARKERS: [string, string][] = [
  ["EGFR_COMMON", "EGFR ex19del / L858R"],
  ["EGFR_T790M", "EGFR T790M"],
  ["EGFR_EXON20_INS", "EGFR exon 20 ins"],
  ["ALK", "ALK"],
  ["ROS1", "ROS1"],
  ["KRAS_G12C", "KRAS G12C"],
  ["BRAF_V600", "BRAF V600"],
  ["MET_EX14", "MET exon 14"],
  ["RET", "RET"],
  ["NTRK", "NTRK"],
  ["HER2_MUT", "HER2 mutation"],
];

const HISTOLOGY = [
  ["", "Not stated"],
  ["adenocarcinoma", "Adenocarcinoma"],
  ["squamous", "Squamous cell"],
  ["non_squamous", "Non squamous NSCLC"],
  ["large_cell", "Large cell"],
  ["small_cell", "Small cell"],
];

const SETTINGS = [
  ["", "Infer from stage"],
  ["neoadjuvant", "Neoadjuvant"],
  ["perioperative", "Perioperative"],
  ["adjuvant", "Adjuvant"],
  ["unresectable_stage3", "Unresectable stage III"],
  ["consolidation_after_crt", "After chemoradiotherapy"],
  ["advanced_first_line", "Advanced, first line"],
  ["advanced_subsequent", "Advanced, later line"],
  ["limited_stage_sclc", "Limited stage SCLC"],
  ["extensive_stage_sclc", "Extensive stage SCLC"],
  ["relapsed_sclc", "Relapsed SCLC"],
];

function list(value: string): string[] {
  return value.split(",").map((v) => v.trim()).filter(Boolean);
}

function num(value: string): number | undefined {
  const parsed = Number(value);
  return value === "" || Number.isNaN(parsed) ? undefined : parsed;
}

interface Props {
  value: PatientContext;
  onChange: (next: PatientContext) => void;
}

export default function PatientContextPanel({ value, onChange }: Props) {
  const set = <K extends keyof PatientContext>(key: K, v: PatientContext[K]) => onChange({ ...value, [key]: v });
  const toggle = (code: string) =>
    set("biomarkers", value.biomarkers.includes(code) ? value.biomarkers.filter((b) => b !== code) : [...value.biomarkers, code]);

  return (
    <aside className="panel context" aria-label="De identified patient context">
      <header className="panel-head">
        <h2>Patient context</h2>
        <p className="hint">De identified only. Names and NHS numbers are redacted automatically.</p>
      </header>

      <label>
        Histology
        <select value={value.histology ?? ""} onChange={(e) => set("histology", e.target.value || undefined)}>
          {HISTOLOGY.map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
      </label>

      <div className="row">
        <label>
          Stage group
          <input placeholder="IVA" value={value.stage_group ?? ""} onChange={(e) => set("stage_group", e.target.value.toUpperCase() || undefined)} />
        </label>
        <label>
          Setting
          <select value={value.setting ?? ""} onChange={(e) => set("setting", e.target.value || undefined)}>
            {SETTINGS.map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </label>
      </div>

      <fieldset>
        <legend>Molecular profile</legend>
        <div className="chips">
          {BIOMARKERS.map(([code, label]) => (
            <button
              type="button"
              key={code}
              className={value.biomarkers.includes(code) ? "chip on" : "chip"}
              aria-pressed={value.biomarkers.includes(code)}
              onClick={() => toggle(code)}
            >
              {label}
            </button>
          ))}
        </div>
      </fieldset>

      <div className="row">
        <label>
          PD L1 TPS %
          <input inputMode="decimal" value={value.pdl1_tps ?? ""} onChange={(e) => set("pdl1_tps", num(e.target.value))} />
        </label>
        <label>
          Performance status
          <select value={value.performance_status ?? ""} onChange={(e) => set("performance_status", num(e.target.value))}>
            <option value="">Not stated</option>
            {[0, 1, 2, 3, 4].map((ps) => (
              <option key={ps} value={ps}>{`ECOG ${ps}`}</option>
            ))}
          </select>
        </label>
      </div>

      <details>
        <summary>Dosing and safety inputs</summary>
        <div className="row">
          <label>
            Age
            <input inputMode="numeric" value={value.age ?? ""} onChange={(e) => set("age", num(e.target.value))} />
          </label>
          <label>
            Sex
            <select value={value.sex ?? ""} onChange={(e) => set("sex", e.target.value || undefined)}>
              <option value="">Not stated</option>
              <option value="female">Female</option>
              <option value="male">Male</option>
            </select>
          </label>
        </div>
        <div className="row">
          <label>
            Weight kg
            <input inputMode="decimal" value={value.weight_kg ?? ""} onChange={(e) => set("weight_kg", num(e.target.value))} />
          </label>
          <label>
            Height cm
            <input inputMode="decimal" value={value.height_cm ?? ""} onChange={(e) => set("height_cm", num(e.target.value))} />
          </label>
        </div>
        <label>
          Creatinine micromol/L
          <input inputMode="decimal" value={value.serum_creatinine_umol_l ?? ""} onChange={(e) => set("serum_creatinine_umol_l", num(e.target.value))} />
        </label>
        <label>
          Prior treatments
          <input placeholder="osimertinib, carboplatin" value={value.prior_treatments.join(", ")} onChange={(e) => set("prior_treatments", list(e.target.value))} />
        </label>
        <label>
          Current medicines
          <input placeholder="omeprazole, bisoprolol" value={value.current_medicines.join(", ")} onChange={(e) => set("current_medicines", list(e.target.value))} />
        </label>
        <label>
          Conditions
          <input placeholder="ILD, renal transplant" value={value.conditions.join(", ")} onChange={(e) => set("conditions", list(e.target.value))} />
        </label>
        <label>
          Allergies
          <input value={value.allergies.join(", ")} onChange={(e) => set("allergies", list(e.target.value))} />
        </label>
      </details>
    </aside>
  );
}
