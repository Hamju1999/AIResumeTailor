"""ATS Scorer — keyword extraction and match scoring."""
from __future__ import annotations
import asyncio
import re
from dataclasses import dataclass, field

@dataclass
class ATSResult:
    score:            int
    above_threshold:  bool
    threshold:        int
    hard_skill_score: int
    matched:          list
    missing:          list
    matched_phrases:  list
    total_checked:    int
    breakdown:        dict = field(default_factory=dict)

# Module-level system prompt
_EXTRACTOR_SYSTEM = """\
You are an ATS (Applicant Tracking System) keyword extraction specialist.
Given a job description, extract the most important keywords and phrases
that an ATS would scan for. Return ONLY valid JSON — no explanation.

Output this exact structure:
{
  "hard_skills": ["<specific tool, language, platform, certification, or technical method>"],
  "soft_skills": ["<domain-specific competency or methodology mentioned in requirements>"],
  "phrases":     ["<important multi-word technical or domain phrase>"],
  "synonyms":    {"<term>": ["<alternate form 1>", "<alternate form 2>"]}
}

Rules:
- hard_skills: only specific named tools, languages, platforms, certifications,
  or frameworks. Examples: SQL, Python, Revit, AutoCAD, Salesforce, HIPAA, IRB,
  Radiation Oncology, SSRS. Max 20 items.
- soft_skills: only domain-specific competencies explicitly required in the JD.
  Examples: data modeling, critical thinking, stakeholder communication.
  Do NOT include generic words like "teamwork", "motivated", "fast-paced". Max 10 items.
- phrases: multi-word technical or domain-specific phrases meaningful as a unit.
  Examples: "data warehouse", "radiation oncology", "structural analysis",
  "building information modeling". Max 15 items.
- synonyms: map abbreviations or alternate spellings to their full form.
  Only include terms actually present in the JD. Max 10 pairs.
- Exclude: company names, location names, salary info, generic adjectives,
  boilerplate HR language ("equal opportunity", "benefits", "duties as assigned").
"""

# Module-level functions
def _extract_keywords_via_llm(jd_text: str) -> dict:
    """Call Claude to extract domain-aware keywords from the JD."""
    try:
        import llm_client
        async def _call():
            return await llm_client.call(
                system=_EXTRACTOR_SYSTEM,
                user=(
                    f"JOB DESCRIPTION:\n---\n{jd_text[:4000]}\n---\n\n"
                    "Extract the ATS keywords. Output only the JSON."
                ),
                expect_json=True,
            )
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, _call())
                    return future.result(timeout=30)
            else:
                return loop.run_until_complete(_call())
        except RuntimeError:
            return asyncio.run(_call())
    except Exception as e:
        import logging
        logging.getLogger("ats_scorer").warning(
            f"LLM keyword extraction failed: {e} — using fallback"
        )
        return _fallback_extract(jd_text)

def _fallback_extract(jd_text: str) -> dict:
    """Heuristic fallback when LLM call fails."""
    req_match = re.search(
        r"(qualif|requirement|responsibilit|minimum|preferred|skills)",
        jd_text, re.IGNORECASE,
    )
    text = jd_text[req_match.start():] if req_match else jd_text
    hard  = list(set(re.findall(r"\b[A-Z][a-z]{2,}\b", text)))[:20]
    hard += list(set(re.findall(r"\b[A-Z]{2,6}\b", text)))[:10]
    return {"hard_skills": hard, "soft_skills": [], "phrases": [], "synonyms": {}}

def _hit(kw, res_norm):
    if not kw or len(kw) < 2:
        return False
    if " " in kw:
        # Exact phrase match first
        if kw in res_norm:
            return True
        # For two-word phrases: check if both words appear nearby (within 60 chars)
        words = kw.split()
        if len(words) == 2:
            w1, w2 = re.escape(words[0][:5]), re.escape(words[1][:5])
            return bool(re.search(rf"{w1}.{{0,60}}{w2}|{w2}.{{0,60}}{w1}", res_norm))
        return False
    return bool(re.search(r"\b" + re.escape(kw) + r"\b", res_norm))

# Main scoring function 
def score(jd_text, resume_text, matched_keywords=None, threshold=75):
    extracted   = _extract_keywords_via_llm(jd_text)
    hard_skills = [k.lower() for k in extracted.get("hard_skills", [])]
    soft_skills = [k.lower() for k in extracted.get("soft_skills", [])]
    phrases     = [k.lower() for k in extracted.get("phrases", [])]
    synonyms    = {
        k.lower(): [v.lower() for v in vs]
        for k, vs in extracted.get("synonyms", {}).items()
    }
    res_norm = re.sub(r"[^\w\s+#./]", " ", resume_text.lower())
    res_norm = re.sub(r"\s+", " ", res_norm).strip()
    kw_weights: dict[str, float] = {}
    for kw in hard_skills:
        kw_weights[kw] = 3.0
    for kw in phrases:
        kw_weights[kw] = 2.5
    for kw in soft_skills:
        kw_weights.setdefault(kw, 1.5)
    if matched_keywords:
        for kw in matched_keywords:
            kn = kw.lower().strip()
            if kn:
                kw_weights[kn] = max(kw_weights.get(kn, 0), 3.0)
    if not kw_weights:
        return ATSResult(0, False, threshold, 0, [], [], [], 0)
    matched_list, missing_list, phrases_list = [], [], []
    total_w = matched_w = hard_total = hard_matched = 0.0
    for kw, weight in sorted(kw_weights.items(), key=lambda x: -x[1]):
        total_w += weight
        is_hard = kw in hard_skills or kw in phrases
        if is_hard:
            hard_total += weight
        found = _hit(kw, res_norm)
        if not found:
            for syn in synonyms.get(kw, []):
                if _hit(syn, res_norm):
                    found = True
                    break
        if found:
            matched_w += weight
            if is_hard:
                hard_matched += weight
            matched_list.append(kw.title())
            if " " in kw:
                phrases_list.append(kw.title())
        else:
            if weight >= 1.5:
                missing_list.append(kw.title())
    sv  = min(100, round(matched_w / total_w * 100)) if total_w else 0
    hsv = min(100, round(hard_matched / hard_total * 100)) if hard_total else 0
    return ATSResult(
        score            = sv,
        above_threshold  = sv >= threshold,
        threshold        = threshold,
        hard_skill_score = hsv,
        matched          = matched_list[:25],
        missing          = missing_list[:12],
        matched_phrases  = phrases_list[:12],
        total_checked    = len(kw_weights),
        breakdown        = {
            "total_keywords":   len(kw_weights),
            "matched_count":    len(matched_list),
            "hard_skill_score": hsv,
            "phrase_matches":   len(phrases_list),
        },
    )
