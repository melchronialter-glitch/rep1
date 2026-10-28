# W5 V7 Remote Source Import Checklist

## Status

`IMPORT NOT STARTED — LOCAL R2 FAILED — REMOTE BRANCH READY`

This checklist limits the future import into this public staging branch. It is not permission to run code.

## Allowed import set

Only these categories may be imported:

1. the 15 public-safe V6 adapter source files;
2. the exact V6 source manifest and aggregate identity;
3. the formal V6 source-review report;
4. the V7 remediation plan and independent plan review;
5. the unapplied V7 draft patch and mapped-image supplement, clearly marked as drafts;
6. adversarial source vectors that contain no private records;
7. build metadata needed to identify source versions, with generated pins absent and fail-closed.

## Forbidden import set

Do not import:

- model weights or optimizer state;
- W1–W7 private corpus content;
- Hugging Face tokens, browser sessions, API keys, passwords, or credentials;
- personal diaries, conversation exports, or user records;
- local absolute paths, machine identifiers, crash dumps, or unrelated process inventories;
- any artifact that claims V7 passed, built, ran, trained, or was promoted.

## Preconditions

Before reading local source:

- a new quiet-window observation must pass;
- free physical RAM must remain at least `14 GiB`;
- no overlapping Python, model, build, or other Aster workload may be active;
- V6 must be re-identified as 15 files / 333,614 bytes / 1,735-byte ordinal preimage / aggregate SHA-256 `9bc3f3027253453fdceb1fb1aa5775eb4251e9786478457a960f64a7b6246990`;
- the formal review must match SHA-256 `26aa5520ebdedbdd930a04b3b24ec79b347391ec7f60332c82daab659c588452`.

## Import transaction

1. Read only the explicitly listed small source and provenance artifacts.
2. Reject reparse points and files outside the adapter tree.
3. Scan the import set for credentials and private-content markers before publication.
4. Add V6 under an immutable predecessor directory.
5. Add V7 under a separate successor directory.
6. Preserve draft patches as negative/incomplete evidence.
7. Record every remote blob and commit SHA.
8. Do not configure, preprocess, compile, link, load, test, or execute.

## Completion criterion

Import is complete only when the remote tree contains the exact allowed source/provenance set, all identities reconcile, V6 remains unchanged, and no forbidden material is present. That completion authorizes only source editing and hostile review.
