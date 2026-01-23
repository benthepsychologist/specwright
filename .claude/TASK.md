# Task: e008-01-core

**Epic:** e008-specwright-v2
**Branch:** feat/specwright-v2-core

## Goal

Transform specwright from step-gating executor to Claude Code orchestrator

## Expectations

- AIP v3 schema exists and validates
- spec aip-compile <spec_id> reads epic, outputs AIP skeleton
- spec aip-enrich <spec_id> calls LLM to generate steps + guidance
- spec aip-run <spec_id> invokes Claude with --dangerously-skip-permissions --print
- spec aip-run <spec_id> --interactive launches Claude TUI
- Artifacts captured: transcript.jsonl, commands.json, patch.diff, verification.json
- spec aip-status <spec_id> shows run state and artifact summary
- spec aip-diff <spec_id> shows branch diff
- Dogfood: run this spec against specwright repo and produce a non-empty artifact set

## Constraints

- Compiler reads from epic, not spec.md
- AIP is the only execution artifact (no sep.yaml)
- Use existing LLMClient and prompts.yaml infrastructure
- Artifacts stored at ~/.local/local-governor/artifacts/{epic}/{spec}/
- Background mode captures stdout with timeout handling
- Repo-scoped by default: execution and diffs are for the target repo; cross-repo changes require explicit opt-in

## Implementation Steps

### step-1: Validate AIP v3 Data Model

Verify that dataclasses in `src/spec/aip/models.py` correctly serialize to JSON that validates against `src/spec/schemas/aip-v3.schema.json`, ensuring the foundation for AIP execution artifacts.

**Likely files:**
- `src/spec/aip/models.py`
- `src/spec/schemas/aip-v3.schema.json`
- `tests/aip/test_models.py`

**Patterns to follow:**
- `src/spec/aip/models.py` - Use standard python @dataclass for model definitions.
- `tests/aip/test_compiler.py` - Follow existing test structure for fixtures and assertions.

**Approach:**

1. Create a new test file `tests/aip/test_models.py`.
2. Define a 'golden' instance of the top-level AIP dataclass in `src/spec/aip/models.py` populated with all possible fields.
3. Implement a serialization routine (using `dataclasses.asdict`) that handles Enums and optional fields to match JSON expectations.
4. Load `src/spec/schemas/aip-v3.schema.json` using the `jsonschema` library.
5. Assert that the serialized dataclass validates against the schema.
6. Adjust `src/spec/aip/models.py` field names or types if validation fails.

**Watch out for:**
- Mismatch between Python snake_case attributes and JSON schema field naming (camelCase vs snake_case).
- Serialization of Python `Enum` objects (requires conversion to string values before validation).
- Handling of `None` values in dataclasses versus omitted keys in JSON schema validation.

### step-2: Verify Compiler CLI Integration

Confirm `spec aip-compile` in `src/spec/cli/spec.py` correctly invokes `src/spec/aip/compiler.py` to read an epic via `src/spec/epic/loader.py` and output a valid AIP skeleton.

**Likely files:**
- `src/spec/cli/spec.py`
- `src/spec/aip/compiler.py`
- `src/spec/epic/loader.py`
- `src/spec/aip/models.py`
- `tests/aip/test_compiler.py`

**Patterns to follow:**
- `src/spec/cli/spec.py` - Follow existing click/argparse command definitions for handling input file paths and flags.
- `src/spec/epic/loader.py` - Use existing loader functions to hydrate Epic objects from disk before passing to the compiler.

**Approach:**

1. Inspect `src/spec/cli/spec.py` to ensure the `aip-compile` command is registered and accepts an epic path and output path.
2. Verify that `aip-compile` imports `load_epic` from `src/spec/epic/loader.py` to parse the input.
3. Ensure the CLI passes the loaded Epic object to `src/spec/aip/compiler.py`.
4. Confirm `src/spec/aip/compiler.py` returns a compliant AIP skeleton (dict or dataclass) matching `src/spec/aip/models.py`.
5. Verify the CLI writes the resulting output to the specified destination.

**Watch out for:**
- Ensure logic remains in `compiler.py` and not leaked into `cli/spec.py`.
- Validate that the output structure aligns with `src/spec/schemas/aip-v3.schema.json`.
- Avoid using Pydantic for models; stick to standard library dataclasses or TypedDict.

### step-3: Verify Enricher CLI Integration

Confirm `spec aip-enrich` in `src/spec/cli/spec.py` correctly invokes `src/spec/aip/enricher.py`, utilizing `src/spec/llm/client.py` to populate the AIP skeleton with steps and guidance.

**Likely files:**
- `src/spec/cli/spec.py`
- `src/spec/aip/enricher.py`
- `src/spec/llm/client.py`
- `src/spec/llm/prompts.py`
- `tests/aip/test_enricher.py`

**Patterns to follow:**
- `src/spec/cli/spec.py` - Follow the existing Click command registration pattern (e.g., similar to `aip-compile`) for handling input/output file paths.
- `src/spec/aip/compiler.py` - Mirror the functional approach: load JSON, instantiate LLM client, invoke logic, save JSON.

**Approach:**

1. Implement the `aip-enrich` command in `src/spec/cli/spec.py`, ensuring it accepts path arguments for the skeleton AIP and the output file.
2. In `src/spec/aip/enricher.py`, implement the logic to traverse the AIP skeleton steps, using `src/spec/llm/client.py` and prompts from `src/spec/llm/prompts.py` to generate step-specific guidance.
3. Ensure the enricher populates the `guidance` field for each step without altering the overall JSON structure defined in `src/spec/schemas/aip-v3.schema.json`.
4. specific unit tests in `tests/aip/test_enricher.py` to mock LLM responses and verify JSON transformation.

**Watch out for:**
- Ensure no Pydantic models are introduced; stick to standard Python types/dicts.
- Verify that `src/spec/llm/client.py` handles API key configuration implicitly or via environment variables, avoiding hardcoded secrets in the CLI.
- Do not depend on legacy logic in `src/spec/governor` or `src/spec/executor`.

### step-4: Harden Runner and Artifact Collection

Verify `spec aip-run` in `src/spec/cli/spec.py` invokes `src/spec/runner/background.py` to execute Claude (with `--dangerously-skip-permissions`), and ensure `src/spec/artifacts/collector.py` correctly captures `transcript.jsonl`, `commands.json`, `patch.diff`, and `verification.json` to the artifact storage path.

**Likely files:**
- `src/spec/cli/spec.py`
- `src/spec/runner/background.py`
- `src/spec/artifacts/collector.py`
- `src/spec/artifacts/storage.py`
- `tests/runner/test_background.py`

**Patterns to follow:**
- `src/spec/cli/spec.py` - Ensure `aip-run` uses the existing Click command structure and argument parsing patterns.
- `src/spec/artifacts/storage.py` - Use this module to resolve the destination paths for artifact persistence before implementing the copy logic in collector.py.

**Approach:**

1. Update `src/spec/runner/background.py` to build the `claude` subprocess command, explicitly adding the `--dangerously-skip-permissions` flag to bypass interactive prompts.
2. Implement the execution logic in `background.py` to run the subprocess in the target working directory and wait for completion.
3. Modify `src/spec/artifacts/collector.py` to scan the execution directory after the run completes and copy `transcript.jsonl`, `commands.json`, `patch.diff`, and `verification.json` to the artifact storage location.
4. Connect `spec aip-run` in `src/spec/cli/spec.py` to invoke the runner and then the collector.
5. Verify command construction and artifact file existence checks in `tests/runner/test_background.py`.

**Watch out for:**
- Failing to include `--dangerously-skip-permissions` will cause the background process to hang waiting for user input.
- The artifact collector must handle cases where optional files (like `patch.diff` or `verification.json`) are not generated by Claude.
- Ensure the subprocess execution environment (cwd) matches where Claude expects to run to generate relative file paths correctly.

### step-5: Verify Status and Diff Reporting

Ensure `spec aip-status` and `spec aip-diff` in `src/spec/cli/spec.py` correctly retrieve execution state and git diffs from `src/spec/artifacts/storage.py` and display them to the user.

**Likely files:**
- `src/spec/cli/spec.py`
- `src/spec/artifacts/storage.py`

**Patterns to follow:**
- `src/spec/cli/spec.py` - Follow the Click command structure for `aip-status` and `aip-diff` subcommands, ensuring proper context handling.
- `src/spec/artifacts/storage.py` - Encapsulate filesystem reads within the storage class methods (e.g., `load_execution_state`, `load_diff`) rather than reading files directly in the CLI.

**Approach:**

1. Update `src/spec/artifacts/storage.py` to include methods for retrieving the persisted execution state (status) and the generated git diff content.
2. In `src/spec/cli/spec.py`, implement `aip-status` to invoke the storage layer, parse the execution state, and display a human-readable summary of the current step and overall progress.
3. In `src/spec/cli/spec.py`, implement `aip-diff` to invoke the storage layer for the git diff artifact and print it to stdout.
4. Add error handling in the CLI to display a friendly message if the artifacts (status or diff) do not exist yet.

**Watch out for:**
- Hardcoding file paths in the CLI module instead of relying on `storage.py` configuration.
- Failing to handle cases where `aip-run` has not yet been executed (missing artifacts).
- Complex formatting logic in the CLI; keep it simple and readable.

### step-6: Dogfooding: End-to-End Orchestration Run

Run the full `spec aip-compile` -> `spec aip-enrich` -> `spec aip-run` lifecycle against the `specwright` repo (targeting a maintenance task) to prove the pipeline works and produce a complete set of non-empty artifacts.

**Likely files:**
- `src/spec/cli/spec.py`
- `src/spec/aip/compiler.py`
- `src/spec/aip/enricher.py`
- `src/spec/runner/background.py`
- `src/spec/artifacts/storage.py`
- `src/spec/llm/client.py`

**Patterns to follow:**
- `src/spec/cli/spec.py` - Ensure argparse subcommands (aip-compile, aip-enrich, aip-run) are correctly wired to pass artifact IDs/paths between stages.
- `src/spec/artifacts/storage.py` - Verify that JSON artifacts are serialized/deserialized correctly between CLI steps without using Pydantic (use standard json or dataclasses.asdict).

**Approach:**

1. Create a simple input file (e.g., `task.md`) describing a trivial maintenance task (e.g., 'Add a comment to src/spec/cli/spec.py').
2. Run `spec aip-compile task.md` and verify it produces an initial structural artifact (check storage).
3. Run `spec aip-enrich <artifact_id>` to invoke the LLM logic and verify the artifact is updated with concrete execution steps.
4. Run `spec aip-run <artifact_id>` to execute the plan.
5. validate that the expected change (the comment) appears in the target file.

**Watch out for:**
- Ensure `aip-enrich` does not hallucinate non-existent file paths; the context retrieval must be working.
- Verify that `aip-run` correctly interprets the enriched steps and doesn't just print them.
- Check that `ArtifactStorage` uses a consistent directory (e.g., `.spec/store`) across multiple CLI invocations.
