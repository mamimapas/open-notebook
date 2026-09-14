# Research and analysis

2026-09-14: RAG skills, repos and papers queried with min_score=0.30 for durable worker queue recovery. All returned HTTP 200 and results. Repos: claw-code score 0.5666, useful state-machine pattern; no code imported. Papers: AutoFyn score 0.33789498178242, persistence/verifier principle, no direct queue implementation. Skills: fencing/ACK guidance, retain unknown outcome instead of replay.

Installed surreal_commands.core.worker inspected directly: one startup scan followed by unbounded LIVE subscription; no rescan and no atomic ownership gate. command_service.execute_command sets running without checking previous status. Main project graph lookup returned no worker symbol (indexing debt for installed dependency).

Primary sources: https://github.com/lfnovo/surreal-commands and https://surrealdb.com/docs/reference/query-language/statements/live-select . Upstream uses durable new/running/completed/failed lifecycle. Repair uses its existing executor and database, avoiding a queue migration.

Consistency analysis: W1-W8 map to polling patch, image binding and tests. No new scheduling surface; no secrets or content in receipts. Existing running commands remain unchanged because ownership cannot be inferred from timestamps. Exact-payload dedup is deliberately narrower than semantic similarity.
