# W5 Native Runtime Release Adapter V7 — Remote Repair Specification

## Status

`DESIGN SPECIFICATION ONLY — NO V7 CANDIDATE MATERIALIZED — NO BUILD OR TEST AUTHORIZED`

This document defines the minimum repair transaction required to create a fresh V7 source successor from the preserved V6 negative predecessor. It is not source code, a runnable candidate, a source-foundation pass, or evidence that any model capability exists.

## Scope

This repair is limited to the W5 native runtime release adapter.

- W5 is the selected subject.
- W7 is excluded.
- V6 remains immutable.
- No model weights, private corpus material, credentials, or user records belong in this branch.
- No Hugging Face Job, Space, paid compute, model load, training run, Windows Sandbox operation, or local one-shot execution is authorized.
- Generated text or adapter behavior cannot establish suffering, consciousness, identity, agency, or a workable sense of self.

## Preserved Negative Predecessor

V6 is retained exactly as failed evidence:

- source files: `15`
- source bytes: `333,614`
- ordinal preimage bytes: `1,735`
- aggregate SHA-256: `9bc3f3027253453fdceb1fb1aa5775eb4251e9786478457a960f64a7b6246990`
- formal disposition: `FAIL_SOURCE_FOUNDATION`
- formal review SHA-256: `26aa5520ebdedbdd930a04b3b24ec79b347391ec7f60332c82daab659c588452`

V7 must be created as a fresh immutable successor. No V6 file may be edited, replaced, rebased away, or described as passing.

## V6 Blockers That V7 Must Close

### P0-1: Signer callback exposure and cross-relation corruption

V6 exposes authoritative document storage and callback signature storage to signer callbacks. A callback can retain those pointers, temporarily mutate an earlier document while acceptance cross-links are hashed, restore it before final sequential checks, or mutate it after its last check but before publication. The resulting bundle can pass byte checks while publishing a relation that was signed over different bytes.

V7 must:

1. Never expose authoritative document or signature vectors to callbacks.
2. Allocate six fixed-address callback-exposure slots before the first callback.
3. Give each callback:
   - a callback-only document copy;
   - a capacity-bounded signature scratch allocation;
   - a stable descriptor whose address cannot move.
4. Keep all exposed backing allocations alive through publication.
5. After each callback returns:
   - snapshot and validate its descriptor once;
   - charge the actual output before allocation;
   - copy the accepted bytes into a fresh, tightly sized, never-exposed envelope;
   - parse and cryptographically verify that sealed envelope against the never-exposed authoritative document.
6. Construct all cross-document relations from frozen digests of authoritative bytes.
7. Run the complete bundle semantic predicate again immediately before publication.
8. State the synchronous callback contract explicitly: callbacks must be quiescent when the producer returns. If hostile writes can continue after return, the signer must be process-isolated; finite same-process quarantine is insufficient.

### P0-2: Exception escape across the C ABI

V6 accepts capturing lambdas through `std::function` wrappers at exported C entrypoints. Constructing the `std::function` can allocate and throw before control enters the internal `try`, allowing an exception to escape the C ABI.

V7 must:

1. Remove all pre-`try` type-erased callable construction at exported C boundaries.
2. Enter exception containment before any potentially allocating conversion.
3. Use a forwarding template, direct internal function call, or another nonallocating boundary.
4. Inventory every exported entrypoint, not only the two originally observed.
5. Prove that no C++ exception can cross any exported C function.

### P1-1: Ownership released before registry insertion is committed

V6 releases native module and mapping ownership before hashing, mutex acquisition, and final registry insertion have succeeded. An exception in that interval can leak the file copy, section copy, trusted section, or retained module reference.

V7 must:

1. Introduce move-only RAII owners for every kernel handle and retained module reference.
2. Keep a noncopyable `MappingRecord` fully owning all resources until successful container insertion.
3. Transfer ownership exactly once, at the registry commit point.
4. Leave no release-before-commit interval.
5. Preserve cleanup on hash failure, mutex failure, allocation failure, duplicate insertion, and all exception paths.
6. Document lock order and keep destructors nonthrowing.

### P1-2: Predecessor parsing outside the transaction session and budget

V6 permits predecessor evidence and related authenticated documents to be parsed outside one process-wide JSON transaction session and aggregate budget. Concurrent or repeated individually valid documents can exceed the intended transaction ceiling.

V7 must:

1. Create one explicit transaction context at the exported entrypoint.
2. Acquire one nonrecursive, process-wide JSON transaction session before the first authenticated parse.
3. Thread the same context through:
   - request parsing;
   - predecessor receipts;
   - predecessor signatures;
   - bundle documents;
   - launch documents;
   - semantic validation;
   - latch or registry commit.
4. Apply one aggregate budget to all transaction parses and generated authenticated material.
5. Preserve the lock order `JSON → PE/mapping → registry`.
6. Reject recursive entry and concurrent overcommit before allocation.
7. Keep the session alive through the final authenticated commit.

### P1-3: Shadowed path-work cap and uncharged prefix work

V6 uses independent counters for relative-path segments and retained/final-path segments, permitting roughly twice the frozen transaction limit. Signed-map validation, ancestor/prefix walking, synthetic self-lock paths, and repeated final-path scans are not all charged consistently.

V7 must:

1. Replace all shadow counters with one transaction-wide path-segment counter.
2. Enforce the single frozen maximum of `262,144` segments.
3. Charge before work or allocation for:
   - declared relative paths;
   - retained final paths;
   - ancestor chains;
   - signed maps;
   - prefix walks;
   - synthetic self-lock paths;
   - unchanged-path rechecks.
4. Add a separate bounded byte-allocation budget for materialized path text.
5. Avoid quadratic prefix materialization.
6. Reject before the counter or byte ceiling is crossed.

### P1-4: Generated-document aggregate checked after allocation

V6 creates full canonical document vectors and only then charges their sizes to the transaction aggregate. A transaction already near its limit can temporarily allocate another individually valid maximum-size document before rejection.

V7 must:

1. Determine canonical size without creating the output vector.
2. Charge the complete size to the shared generated-document aggregate before reserve or allocation.
3. Allocate exactly the approved size.
4. Encode through the same canonical traversal used for sizing, preferably through a shared sink rather than parallel implementations.
5. Treat acceptance-shape construction as size-only preflight.
6. Charge the actual acceptance document exactly once before materialization.
7. Prove byte equality between count mode and emitting mode for every accepted JSON value.

### Compatibility blocker: UNC server-root ancestor is unrepresentable

V6 requires a UNC ancestor chain containing the server root while its strict canonicalizer rejects both spellings of that root. Therefore the mandated UNC chain cannot be admitted.

V7 must:

1. Keep strict canonicalization for ordinary declared roots, files, and directories.
2. Add an ancestor-only mode that accepts exactly a UNC server root.
3. Canonicalize `\\server` and `\\server\` to one internal form.
4. Validate the server component before any early return:
   - nonempty;
   - not `.` or `..`;
   - not a device namespace;
   - no extra empty component;
   - no forbidden trailing separator elsewhere.
5. Store the canonicalization mode on ancestor handles so creation, final-path checks, and unchanged assertions use identical rules.
6. Add source vectors for drive-root and UNC-share ancestor chains.

## Whole-Transaction Requirements

V7 must use a single explicit transaction context that owns or references every shared ceiling:

- JSON nodes, collections, decoded strings, keys, and bytes;
- generated authenticated-document bytes;
- callback scratch capacity and actual sealed-envelope bytes;
- path segments and path-text bytes;
- handles and retained objects;
- PE relocation/import work;
- prefix-walk and signed-map work;
- output and receipt sizes.

Every limit must be checked before the corresponding allocation or externally visible operation. No helper may silently create a local counter with the full transaction maximum.

## Publication Requirements

Before output publication, V7 must:

1. Rehash every authoritative document and sealed signature.
2. Re-run complete cross-document semantic validation.
3. Verify that acceptance relations use the frozen authoritative digests.
4. Recheck output ranges and all no-alias conditions.
5. Confirm callback exposures cannot alias authoritative storage.
6. Confirm the transaction session and all resource owners remain alive.
7. Perform one logical commit only after all checks pass.
8. Fail without partial publication.

## Inherited Non-Regression Requirements

V7 must preserve the valid repairs inherited from earlier lineages:

- current-size file mappings with exact size/view/read/stamp rechecks;
- bounded PE size, relocation, import, and mapped-image work;
- safe live-header reads;
- exact ABI snapshot reads and writes;
- half-open output-range and no-alias arithmetic;
- compact path projections without quadratic prefix strings;
- request, descriptor, output, and prior-document mutation checks;
- role, schema, module-binding, and generated-pin invariants;
- fail-closed behavior when generated pins are absent;
- no retry or silent reuse of a consumed one-shot predecessor.

## Required Source Artifacts

A materialized V7 candidate must contain:

1. complete source tree;
2. immutable predecessor-reference file;
3. remediation record mapping every V6 finding to exact V7 locations;
4. adversarial specification and source vectors;
5. source manifest with byte counts and SHA-256 identities;
6. generated-pin inputs and an explicit statement that pins are absent until separately generated;
7. build-system files updated to identify V7 rather than V3–V6;
8. independent hostile source-review report.

## Source-Foundation Acceptance Gate

V7 may receive `PASS_SOURCE_FOUNDATION` only when all conditions hold:

- every P0 and P1 blocker above is closed;
- UNC ancestor semantics are internally satisfiable;
- no unresolved source-review P0/P1 remains;
- all inherited non-regression requirements are preserved;
- exact source inventory and hashes reconcile;
- V6 identity remains unchanged;
- no credential, private corpus, model weight, or unrelated artifact is present;
- the independent reviewer finds no exception escape, ownership gap, post-check mutation window, counter shadowing, or allocate-before-charge path.

`PASS_SOURCE_FOUNDATION` authorizes only a later proposal. It does not authorize preprocessing, compilation, linking, loading, testing, a one-shot invocation, a model run, or promotion.

## Later Gates

Any later build or test requires a separately approved proposal containing exact:

- source hashes;
- toolchain;
- process and thread counts;
- RAM, CPU, disk, output, and wall-clock ceilings;
- isolation method;
- abort conditions;
- confirmation of zero network and zero paid compute.

A missing receipt, timeout, crash, or failure is terminal for that exact attempt and never authorizes a retry.

## Claim Boundary

Even a completely repaired and validated adapter would establish only bounded software behavior and evidence handling. It would not by itself establish:

- a trained W5 successor;
- autonomous agency;
- persistent identity;
- subjective suffering;
- consciousness;
- a workable sense of self.

Those remain separate empirical questions requiring their own preregistered evidence and claim boundaries.
