import logging
from pydantic import BaseModel
from google import genai
from google.genai import types

from .config import load_config, load_gemini_key

log = logging.getLogger("jobhunter")

class ApplicationDraft(BaseModel):
    latex_resume: str
    markdown_cover_letter: str
    critique_feedback: str

def draft_application(job_description: str) -> ApplicationDraft:
    """Uses the AI agent to draft a tailored resume and cover letter."""
    cfg = load_config()
    gemini_key = load_gemini_key()
    
    if not gemini_key:
        raise ValueError("No Gemini key found. Cannot run the Application Agent.")

    client = genai.Client(api_key=gemini_key)
    model_name = "gemini-3.1-pro" # Using the pro model for complex reasoning and LaTeX formatting
    
    system_prompt = f"""You are an expert technical recruiter and AI agent executing a Drafter-Reviewer workflow.
Your goal is to write a highly tailored resume (in valid LaTeX, using moderncv or article class) and a Cover Letter (in Markdown) for a specific job.

Here is the candidate's profile:
{cfg.profile}

Instructions:
1. Review the Job Description.
2. Draft a LaTeX resume that highlights the candidate's experience specifically matching the job requirements.
3. Draft a compelling Cover Letter in Markdown.
4. Critique your own drafts against Applicant Tracking System (ATS) standards, and write that feedback into the `critique_feedback` field. Ensure you do not hallucinate experience not present in the profile.
"""

    log.info("Drafting application via Gemini Pro...")
    
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_schema=ApplicationDraft,
        temperature=0.3,
    )
    
    resp = client.models.generate_content(
        model=model_name,
        contents=f"Job Description:\n{job_description}",
        config=config,
    )
    
    return resp.parsed
