# Evaluations

Start backend, configure its key, and complete Reindex first. From backend run:

```
.venv/Scripts/python.exe -m evals.run
```

Fourteen seed cases cover facts, equation interpretation, table values, summaries, comparisons, false premises, unrelated/related-but-absent questions, instruction overrides and follow-ups. Reference page locations for numeric/equation cases were checked in the local PDFs. These are development cases, not an independently validated held-out benchmark. Add your own held-out JSONL cases with the same schema using `--cases path.jsonl`.

Runner saves all answers, expected behavior, source-page hits, required-paper citation coverage and optional model grading. `--skip-judge` disables grading calls. Original cited page text is supplied independently to the grader. Its judgments remain advisory, particularly where text extraction loses table/equation layout. Manually review these against PDF page images. Summary/comparison rubrics need human adjudication. Absent-content cases are seeds and should be reviewed as new documents enter the index; an upload may legitimately change answerability.

Offline lifecycle tests also verify pending upload exclusion, successful snapshot activation, failed reindex rollback, initial allowlist, citation integrity and rejection of unsupported claims. Run `python -m pytest -q` in the backend environment.

To test later uploads, create a PDF with a unique factual assertion, upload it, verify that a question about it abstains before reindex, then index and verify a cited answer afterward. Use a separate test knowledge base (`STORAGE_DIR`, `RAG_DATA_DIR`) to avoid changing the assignment corpus. A successful activation test is automated with mocked embeddings in tests/test_app.py.

Live evals are not run automatically at startup: they incur API charges. The user authorized API usage, but a local API key is still required.


## Live checks completed

The final run `storage/evals/20261018T165034Z.json` passes all 14 answerability cases, with all six expected abstentions correct and all eight supported answers graded correct and grounded. The mean model citation score is 0.98. Grading remains advisory; use source pages for important details.

Use `python -m evals.run --workers 3` for bounded concurrency or `--ids attention-results bert-masking` for selected cases. Each completed case is checkpointed to the result JSON. Use `python -m evals.lifecycle` for a funded end-to-end upload test in an isolated synthetic corpus. It preserves the main corpus and checks pending exclusion, source-access exclusion, index activation, and a cited answer after reindexing. Its report is `storage/evals/lifecycle-report.json`.
