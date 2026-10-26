# Intelligent Tracker - Agent Guidelines & Modernization Rules

This file documents persistent instructions, modernization principles, and architecture rules for AI coding assistants working in this repository.

## 1. Python Modernization & Decrufting Standards
All codebase additions and refactors MUST strictly follow modern Python 3.10–3.12+ idioms:
- **No Python 2 Compatibility Imports**: Never use `from __future__ import division, print_function, absolute_import`. These are no-ops in Python 3.
- **No Obsolete Shims**: Never import `builtins.object`, `past.builtins.basestring`, `past.utils.old_div`, or `six` (`reraise`, `with_metaclass`, `moves`).
- **Clean Class Declarations**: Never write `class Foo(object):`. Use standard `class Foo:`. For metaclasses, use `class Foo(metaclass=Meta):`.
- **Modern Exception Chaining**: Use native `raise NewException(...) from err` rather than custom reraise helpers.
- **Standard String & Path Types**: Use native `str` instead of `basestring`. Use standard `pathlib.Path` or `os.path`.
- **Collections ABCs**: Always import abstract collections from `collections.abc` (e.g. `MutableMapping`, `MutableSet`, `Iterable`), never from `collections`.
- **Lean Dependencies**: Maintain a minimal dependency footprint without legacy bridging packages (`future`, `six`).

## 2. Comment & Mathematical Formula Preservation
- **Preserve Domain Comments**: Never strip or summarize computer vision docstrings, mathematical proofs, camera matrix coordinate transformations, or algorithm rationale.
- **Maintain Algorithm Explanations**: OpenCV matrix calculations, moment division formulas, IoU and Kalman kinematic states must retain their original mathematical annotations.

## 3. Testing & Verification Standards
- Always run the full test suite in headless mode with:
  ```powershell
  $env:MPLBACKEND="Agg"; .\.venv\Scripts\python.exe -m unittest discover tests
  ```
- Ensure 100% green test passes across all 156+ unit and integration tests.
- When adding new modules or fixing bugs, add corresponding unit tests in `tests/test_<module>.py`.

## 4. Documentation Standards
- Keep Sphinx documentation up-to-date in `documentation/` and ensure clean builds with zero warnings:
  ```powershell
  .\.venv\Scripts\python.exe -m sphinx -W --keep-going documentation/ documentation/_build/html/
  ```
- Maintain `milestone_plan.md` and `MIGRATION_LOG.md` with detailed records of code changes, architectural decisions, and verification results.
