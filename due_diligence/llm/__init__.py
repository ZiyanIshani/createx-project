"""
llm — LLM integration layer for the due diligence pipeline.

All LLM calls go through the Groq API (OpenAI-compatible endpoint).
The API key is read from the GROQ_API_KEY environment variable.

Submodules:
    client      — GroqClient: raw HTTP wrapper with retry-on-429 logic
    prompts     — All system prompt templates as string constants
    agents/     — Agent implementations using the shared ReAct loop:
                    authorship   — contributor risk assessment
                    provenance   — copy-paste / licence risk detection
                    quality      — coding standards violation grading
                    subscriptions — heuristic SaaS service scanner (no LLM)
"""
