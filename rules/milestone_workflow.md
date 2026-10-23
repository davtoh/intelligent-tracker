# Rule: Milestone-by-Milestone Workflow & Review

## Purpose
Prevent large, untested batches of code changes. Ensure the developer can understand, manually test, and review code milestone-by-milestone before committing or advancing.

## Guidelines
1. **Incremental Scope:**
   - Group tasks into focused, self-contained milestones:
     - *Milestone 1: Environment & Core Engine Revitalization* (Python 3.12 virtualenv, cross-platform setup guide for Win/Linux/Mac, unit test suite passing).
     - *Milestone 2: Detector Modernization* (Integrate YOLOv8/v11 Edge with ONNX Runtime / OpenVINO / Coral TPU alongside/replacing legacy Haar cascades).
     - *Milestone 3: RTSP Camera Feeds & Multi-Zone Analytics* (RTSP/IP camera streaming, virtual tripwires, zones, occupancy counting, dwell times, and heatmaps).
     - *Milestone 4: Edge Alerting & Event Dispatch* (Webhooks, Telegram bot notifications, and MQTT messaging for retail/security events).
     - *Milestone 5: Dashboard & Packaging* (Modern web/desktop analytics UI, Docker/Raspberry Pi setup, and updated Sphinx/Markdown documentation).
   - Do not mix unrelated architectural changes into a single milestone.
2. **Automated Verification Before Milestone Completion:**
   - Run automated test suite:
     ```powershell
     .\.venv\Scripts\python.exe -m unittest discover tests
     ```
   - Verify synthetic frame processing and FPS benchmark where applicable before closing a milestone.
3. **Structured Milestone Report:**
   - At the conclusion of every milestone, present:
     - **Summary of Changes**: What was implemented and why.
     - **Automated Test Results**: Confirmation of green checks and test output.
     - **Manual Testing Steps**: Clear, copy-pasteable execution commands (e.g. running `main.py` with mock feed or webcam).
     - **Pending Questions / Blockers**: Any decisions needing developer guidance.
4. **Pause for Review & Commit:**
   - Allow the user to test manually and commit their work to Git with a clean commit message when they are satisfied.
