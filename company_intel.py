"""
Company Intelligence Gatherer.
Runs BEFORE the Tailor agent. Collects publicly available information
about the hiring company to help the resume tailor align language,
priorities, and framing with what the company actually cares about.
Intelligence gathered:
  - What the company does (product, service, domain)
  - Tech stack and tools they use or mention publicly
  - Company size and growth stage
  - Hiring priorities inferred from JD patterns
  - Culture signals (engineering-driven, sales-driven, research-focused)
This context is injected into the tailor prompt as COMPANY CONTEXT,
helping the model choose which projects and framings resonate most.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
log = logging.getLogger("company_intel")

@dataclass
class CompanyIntel:
    company_name: str
    what_they_do: str = ""          # core product/service in plain English
    domain: str = ""                # industry vertical
    tech_stack: list[str] = None    # tools/technologies they use
    size_stage: str = ""            # startup / mid-size / enterprise
    culture_signals: list[str] = None  # engineering-heavy, research-focused, etc
    hiring_priorities: list[str] = None  # what this team values based on JD
    sponsorship: dict = None        # from visa_sponsors.sponsorship_label()
    raw_summary: str = ""           # full LLM-generated summary paragraph

    def __post_init__(self):
        if self.tech_stack is None:
            self.tech_stack = []
        if self.culture_signals is None:
            self.culture_signals = []
        if self.hiring_priorities is None:
            self.hiring_priorities = []
        if self.sponsorship is None:
            self.sponsorship = {}

    def to_prompt_block(self) -> str:
        """Format as a prompt-ready context block for the tailor agent."""
        lines = [f"COMPANY CONTEXT: {self.company_name}"]
        if self.what_they_do:
            lines.append(f"What they do: {self.what_they_do}")
        if self.domain:
            lines.append(f"Domain: {self.domain}")
        if self.size_stage:
            lines.append(f"Size/stage: {self.size_stage}")
        if self.tech_stack:
            lines.append(f"Tech stack: {', '.join(self.tech_stack)}")
        if self.culture_signals:
            lines.append(f"Culture signals: {', '.join(self.culture_signals)}")
        if self.hiring_priorities:
            lines.append(f"Hiring priorities: {', '.join(self.hiring_priorities)}")
        if self.sponsorship:
            lines.append(f"Sponsorship: {self.sponsorship.get('summary', '')}")
        return "\n".join(lines)

_INTEL_SYSTEM = """\
You are a company intelligence analyst helping a job candidate understand a company
before applying. Given a company name and job description, extract structured
intelligence that will help the candidate tailor their resume.

Output ONLY valid JSON — no preamble, no explanation:
{
  "what_they_do": "<1-2 sentences: core product or service in plain English>",
  "domain": "<industry vertical: e.g. fintech, healthcare AI, logistics, e-commerce, defense>",
  "tech_stack": ["<tool or technology the company uses, inferred from JD or company type>"],
  "size_stage": "<one of: startup, growth-stage, mid-size, large enterprise, Fortune 500>",
  "culture_signals": [
    "<signal about engineering culture, e.g. 'data-driven', 'research-focused',
     'fast-moving startup', 'heavy compliance environment', 'customer-facing product'>"],
  "hiring_priorities": [
    "<what this specific team values most, inferred from JD language and emphasis>"],
  "resume_advice": "<one sentence: what aspect of the candidate's background to emphasise
                    most for this specific company and role>"
}

Rules:
- tech_stack: only list tools the company actually uses or mentions — do not invent.
  Infer from the JD, the domain, and public knowledge of the company type.
  Max 10 items.
- hiring_priorities: infer from the JD's language, what it emphasises repeatedly,
  and what appears under required vs preferred qualifications. Max 5 items.
- culture_signals: infer from company type, JD tone, and domain. Max 4 items.
- If you do not know something for certain, omit it rather than guessing.
- resume_advice: this is the single most important output — what should the candidate
  lead with for THIS company.
"""

async def gather(company_name: str, job_title: str, jd_text: str) -> CompanyIntel:
    """
    Gather company intelligence using Claude.
    Falls back gracefully if the call fails — returns minimal intel object.
    """
    try:
        import llm_client
        user_msg = f"""\
Company: {company_name}
Job Title: {job_title}

Job Description:
---
{jd_text[:3000]}
---

Extract company intelligence to help a candidate tailor their resume for this role.
Output only the JSON.\
"""
        data = await llm_client.call(
            system=_INTEL_SYSTEM,
            user=user_msg,
            expect_json=True,
        )
        # Get sponsorship assessment
        try:
            import visa_sponsors as vs
            sponsorship = vs.sponsorship_label(
                company_name=company_name,
                jd_text=jd_text,
                check_everify=True,
            )
        except Exception:
            sponsorship = {"verdict": "unknown", "summary": ""}
        intel = CompanyIntel(
            company_name     = company_name,
            what_they_do     = data.get("what_they_do", ""),
            domain           = data.get("domain", ""),
            tech_stack       = data.get("tech_stack") or [],
            size_stage       = data.get("size_stage", ""),
            culture_signals  = data.get("culture_signals") or [],
            hiring_priorities= data.get("hiring_priorities") or [],
            sponsorship      = sponsorship,
            raw_summary      = data.get("resume_advice", ""),
        )
        log.info(
            f"Company intel gathered: {company_name} | "
            f"domain={intel.domain} | "
            f"sponsorship={sponsorship.get('verdict','unknown')}"
        )
        return intel
    except Exception as e:
        log.warning(f"Company intel failed for '{company_name}': {e} — using minimal intel")
        return CompanyIntel(company_name=company_name)