# Copilot Instructions for this Repository

This project targets modern Python and Mopidy 4 conventions. For every change, review the code for idiomatic modern Python usage and update it where it is not already aligned.

## Required standards

- Prefer modern Python 3.13 idioms and style over legacy compatibility patterns.
- Prefer readable, explicit, maintainable code.
- Use comprehensions, generator expressions, and built-in container operations where they are clearer and appropriate.
- Prefer vectorized/collection-oriented patterns where they reduce duplication and improve clarity; avoid hand-written loops when a comprehension or standard-library helper is the clearer choice.
- Favor modern APIs, context managers, and straightforward control flow over older patterns.
- Keep the code aligned with the project’s current architecture and the Mopidy 4 runtime model.
- Preserve behavior and correctness first; then modernize the implementation style when it does not broaden scope.
- Prefer dependencies and minimum versions available in Debian stable (currently Debian 13, with Python 3.13). Check availability before adding or raising a dependency. Keep code compatible with the minimum Python version in pyproject.toml.
- Use Google-style Markdown docstrings, single backticks for code references, and comments that explain constraints or rationale.
- Mirror source packages under tests/, including oauth/ and _ext/.
- When adapting third-party code or tests, record the upstream version and source, retain attribution and the license, and include the license in distributions. Document adaptations and keep their tests deterministic.

## Review checklist for every edit

- Does this code still use old Python conventions, awkward manual accumulation, or legacy compatibility shims that can be simplified?
- Would a comprehension, generator, set/dict construction, or standard-library helper make this clearer and more idiomatic?
- Is the implementation still easy to read and maintain in the context of a modern Python codebase?
- Are we introducing unnecessary complexity or old patterns for compatibility that the project no longer needs?

## Test and validation expectations

- Prefer real behavior tests over mock-heavy assertions.
- Keep changes small and targeted.
- Validate with the smallest relevant test command after edits.

