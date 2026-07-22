"""
src.tools — System interaction layer for Sistemista.

Each module implements one capability the agent can exercise against the OS:

  fileops        — native file I/O (bypasses shell quoting issues)
  session        — persistent shell subprocess with process registry
  terminal       — PTY wrapper for interactive wizards
  wizard_driver  — launcher normalisation and cwd resolution
  observer       — filesystem snapshot + deterministic step judge
  safety_gate    — LLM-backed goal risk classifier (SAFE / RECOVERABLE / DESTRUCTIVE)
  template_guard — detects unrendered {{placeholder}} leaks before they hit disk
  behavior_verifier — operational-state smoke-tester (is the project runnable?)
  success_checker   — lightweight artifact-presence check
  capability_registry — records which tool invocations succeeded, for planner context
  shell_runner    — standalone subprocess helper (used outside session contexts)
"""
