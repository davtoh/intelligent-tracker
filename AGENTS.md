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

## 3. Testing & Verification Standards (OS-Agnostic)
- Always run the full test suite in headless mode using cross-platform commands (with `MPLBACKEND=Agg` set in the environment):
  ```bash
  python -m unittest discover tests
  ```
- Ensure 100% green test passes across all unit and integration tests.
- When adding new modules or fixing bugs, add corresponding unit tests in `tests/test_<module>.py`.
- Never leave temporary `scratch/` directories or browser profiles inside the repository root.

## 4. Documentation Standards (OS-Agnostic)
- Keep Sphinx documentation up-to-date in `documentation/` and ensure clean builds with zero warnings:
  ```bash
  python -m sphinx -W --keep-going documentation/ documentation/_build/html/
  ```
- Maintain `milestone_plan.md` and `MIGRATION_LOG.md` with detailed records of code changes, architectural decisions, and verification results.
- Never embed `file:///` URIs, machine-local absolute paths, OS-locked virtualenv binary paths, or hardcoded `localhost` URLs inside committed plans or documentation.

## 5. Frontend, CSS & Specificity Standards
- **Strict Avoidance of `!important`**: Never use `!important` in production stylesheets. `!important` breaks the natural CSS cascade, prevents responsive theme overrides, breaks fullscreen pseudo-classes (`:fullscreen`), and creates compounding specificity debt that downstream components cannot override.
- **Natural Specificity Hierarchy**: Structure selectors using clean structural cascading (e.g. `.video-card:fullscreen .video-container`), pseudo-classes (`:fullscreen`, `:hover`, `:focus-visible`), or CSS custom properties (variables) rather than brute-forcing specificity with `!important`.
- **Contained Overflow & Text Truncation**: All flexible headers, labels, and title spans must specify `min-width: 0`, `overflow: hidden`, and `text-overflow: ellipsis` along with descriptive `title` attributes to prevent unbounded string expansion from blowing out parent grid or flex layouts.

## 6. Core Coding Principles & Quantitative Modularity Budgets
All new code and refactors must adhere to the 10 Core Coding Principles (**SRP, DRY, KISS, Descriptive Naming, Comments for the "Why", Consistent Style, Error Handling & Robustness, Testing & Verification, Version Control Hygiene, and Security First**) and the following structural budgets:

| Code Element | Healthy Target | Soft Warning (Refactor Trigger) | Hard Ceiling (Mandatory Split) | Required Action |
| :--- | :--- | :--- | :--- | :--- |
| **Source File** (`.py`, `.js`, `.css`) | 150 – 300 lines | **350 lines** | **500 lines** | Extract domain submodules (`routers/`, `services/`, `repositories/`, `static/js/`). |
| **Class** | 50 – 180 lines | **10 methods** (or 200 lines) | **12 methods** (or 300 lines) | Decompose using composition, focused domain services, or cohesive mixins. |
| **Function / Method** | 10 – 25 lines | **30 lines** | **40 lines** | Extract pure helper functions; flatten nested conditionals. |
| **Route / Endpoint** | 5 – 15 lines | **15 lines** | **25 lines** | Keep handlers thin: parse request, invoke a service, and return response. |

## 7. Monolith Freeze & Strangler-Fig Architecture Map
The following legacy files currently exceed the 500-line hard ceiling and are under an active **Monolith Freeze**:
- `dashboard/static/styles.css` (2,902 lines)
- `intelligent_tracker/database.py` (2,107 lines, `TrackerDB` has 68 methods)
- `dashboard/app.py` (1,951 lines)
- `intelligent_tracker/geometry.py` (1,816 lines)
- `intelligent_tracker/detectors.py` (1,653 lines)
- `intelligent_tracker/core.py` (1,537 lines)
- `intelligent_tracker/events.py` (1,377 lines)
- `dashboard/static/app.js` (1,263 lines)
- `dashboard/static/studio.js` (994 lines)
- `dashboard/stream_manager.py` (880 lines, `StreamManager` has 25 methods)
- `dashboard/static/review_and_rsac.js` (813 lines)
- `intelligent_tracker/tracker.py` (781 lines)

### Mandatory Placement for New Features ("Split-Before-You-Grow")
1. **New Web Routes & API Endpoints**: Do **NOT** add new endpoints directly into `dashboard/app.py`. Place new route handlers in `dashboard/routers/<domain>.py` (using FastAPI `APIRouter`) and business logic in `dashboard/services/<domain>_service.py`, then mount the router in `dashboard/app.py`.
2. **New Database Queries & Tables**: Do **NOT** add new methods directly into `TrackerDB` inside `intelligent_tracker/database.py`. Create focused domain repositories or query mixins in `intelligent_tracker/repositories/<domain>_repo.py` ($\le$ 10–12 methods per class) and compose or re-export them via `TrackerDB` so existing callers remain unbroken.
3. **New Stream / Pipeline Logic**: Do **NOT** expand `dashboard/stream_manager.py`. Extract focused collaborator classes (e.g. `dashboard/services/stream_lifecycle.py`, `dashboard/services/frame_Overlay.py`).
4. **New Frontend Scripts & Styles**: Do **NOT** append new feature blocks to `dashboard/static/app.js` or `dashboard/static/styles.css`. Place new frontend modules in `dashboard/static/js/<feature>.js` and component styles in `dashboard/static/css/<component>.css`.
5. **Decomposing Existing Monoliths**: When executing a dedicated refactoring milestone, use the `/refactor-monolith` skill and preserve 100% of existing public imports via `__init__.py` or facade re-exports.
