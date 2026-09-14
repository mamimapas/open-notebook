# Durable worker recovery

Approved 2026-09-14 as the first module of the FASTAPI recovery plan.

## Requirements

- W1: Replace the existing worker listener, not add a service, schedule or daemon.
- W2: Scan durable new commands every 15 seconds with a fresh database connection; process at most one command at once.
- W3: Claim a new command atomically before execution. A second worker cannot execute the same command.
- W4: For generate_podcast, deduplicate exact app/name/args/context payloads against other new/running/completed commands. Normalize absent/null/empty context. Reuse a completed result only with nonempty audio; block an ambiguous running duplicate. Never delete commands or replay legacy running commands. Exclusive kernel lock on the shared data volume protects different command IDs across consumer processes.
- W5: Parser errors and timeouts attempt terminal failed states; cancellation records interruption. A timeout remains unknown even if the database write fails and freezes further consumption. Do not log source text or credentials.
- W6: Preserve upstream command service, registration, profiles, TTS and API compatibility.
- W7: A missed notification does not strand new work. Tests cover two workers, duplicate payloads, parser failure, timeout, cancellation and database failure; page past blocked commands.
- W8: Readiness distinguishes process liveness from a successfully queried queue and active work. No automatic retry of ambiguous external publication.

## Evidence baseline

Consumer image 1022e5d8028d56c66280820d555b9597f7b5a360d5ea27336e3af4bc5cf4eeb6 is alive, but commands for 12/13 September remain new. Five legacy running commands belong to August/1 September. The two IA 13 September command payload hashes are identical (942d5b03c79b0a4f665b3cf29f42791588c91e5b3455e5b516eb36f72b7d751d).

## Acceptance

Unit/integration fault tests pass; original queued command IDs advance to terminal with real audio artifacts. Publication and two natural days remain FASTAPI integration criteria.
