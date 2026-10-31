# Tests

| Folder | Runs with | Needs |
|---|---|---|
| `unit/` | `make test-unit` | nothing |
| `contract/` | `make test-contract` | nothing |
| `emulator/` | `make test-emulator` | Firebase CLI + Java 11+ (auto-skipped otherwise) |
| `e2e/` | — | starts in M1 |
| `evaluation/` | — | model evaluation starts in M2 (Step 21); content gate lives in `unit/test_evaluation_content.py` |
