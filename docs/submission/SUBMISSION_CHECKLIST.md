# Submission checklist

## Verified in the repository

- Live TigerGraph MCP connection and all seven `agent_*` GSQL queries pass the smoke test.
- GraphRAG indexes 5,570 policy, pattern and closed-case chunks into `KnowledgeChunk` and returns policy, pattern and prior-case citations.
- The real 20-case benchmark produced 20 valid answer files with zero review failures and wrote formal cases to the graph.
- Case writes use `InvestigationCase` plus deployed relationship names; approval routes are policy-derived and role-protected.
- Frontend TypeScript check passes; Python suite passes with 157 tests.
- Calibration report is generated at `outputs/CALIBRATION_REAL.md`.

## Manual before submission

- Record the 3–5 minute demo using `docs/submission/DEMO_SCRIPT.md`.
- Publish `docs/submission/BLOG_POST.md` with two screenshots and the repository/demo links.
- Publish one post from `docs/submission/SOCIAL_POSTS.md`, tagging `@TigerGraphDB`.
- Submit the repository, demo, blog, social links and `outputs/benchmark_final/answers/` in the hackathon form.
