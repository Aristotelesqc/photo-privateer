# ADR 001: durable photograph, representation and web-use identities

Status: proposed implementation contract for #30, preserving the merged PR4
behavior. This ADR and its executable compatibility examples do **not** install
the target schema or change the current integer API IDs. Schema implementation
belongs to later migrations, after the backup/recovery prerequisite #48.

## Problem and decision

Today `images.id` names a catalog record and `matches.id` simultaneously names a
physical observation and its current logical discovery. A mutable group supplies
the shared identity. Canonical ownership can change on departure, replacement or
purge. Using any of those integers, a path, SHA, primary flag, URL or current group
membership as a future case/evidence identity would make historical associations
change meaning as users organize their photographs.

Introduce separately allocated UUID4 identities. Generate them locally once,
store lowercase canonical UUID text, validate at application boundaries and never
recycle them. Imports preserve original UUIDs; an actual UUID collision is an
explicit import conflict, not an upsert. Integer IDs remain compatibility lookup
keys during migration. UUIDs identify records; they do not prove ownership,
content equality or access permission.

| Entity | Lifetime and meaning | What does not change its UUID |
| --- | --- | --- |
| Photograph | An asserted permanent source lineage; initially one independent lineage per representation with no proven predecessor. | Paths, availability, primary changes, reversible grouping, review, archive and purge. |
| Representation | One physical content record: content SHA, dimensions and original acquisition metadata, associated with a photograph lineage. Separate copies retain separate representation IDs even with equal SHA. | Unambiguous rename/move of the same existing record, library changes, archive/offline and purge. Changed content gets a new representation UUID. |
| Group | A user-created, mutable equivalence assertion among representations, with versioned membership and primary selection. Its UUID remains historical after dissolution. | Join/leave, primary changes and archive/offline. A dissolved/recreated group gets a new UUID. |
| WebUse | Target #31: use of one durable photograph lineage on one conservatively normalized page, keyed by `(photograph identity, page identity)`. Candidate/asset URLs are subordinate observations, not part of page-use identity. A result without a page remains a separate provisional ASSET_ONLY use. | CDN/asset variants, provider, match strength, title, classification, primary changes or later disappearance. A permanent lineage equivalence may resolve old IDs together without deleting them. |
| Photograph–WebUse association | A durable historical attachment of a lineage to its WebUse, independently of current grouped presentation; retain original targets when lineage or GROUP equivalence changes the view. | Rediscovery, canonical-owner promotion or primary changes. |
| Observation | Evidence that a particular provider call searched a particular representation and returned a particular WebUse. | Later grouping, replacement, handover and purge. |

No UUID is derived from a path, SHA, dHash or URL. SHA detects byte identity;
dHash proposes or validates representation equivalence under the existing rules.
Neither alone proves that two independently indexed records share a permanent
lineage. Grouping is the user's **reversible** equivalence decision. A validated
in-place re-export establishes a **permanent** LINEAGE relation. Exact duplicate
copies remain separate representations until a supported explicit operation
establishes their relationship.

If a known target representation already belongs to another independently
allocated photograph, validated LINEAGE appends an equivalence link between the
two photograph UUIDs. Both UUIDs remain valid and all original foreign keys stay
unchanged. Resolve the predecessor's established lineage as the preferred
logical identity; preserve the target UUID as an alias through the permanent
link. Reject contradictory lineage links or cycles transactionally. Correction
of a wrongly asserted lineage must be an explicit audited corrective operation;
group departure or dissolution never undoes LINEAGE. This correction UI is not
implemented by this ADR.

For #31, two distinct photograph lineages used on the **same page** have separate
WebUse UUIDs. Multiple CDN URLs, resized assets or signed asset URLs observed for
the **same photograph and page** sit beneath one page WebUse. Different pages
remain different uses even when they embed the same asset. Reversible GROUP
equivalence can unify the current presentation of member discoveries; it does
not globally identify those photograph lineages or erase their WebUses.

Page normalization is conservative and versioned. Preserve every raw page and
asset URL alongside the normalized value and its normalization version. Retain
query parameters that may identify content; do not drop arbitrary queries,
collapse distinct paths, assume HTTP/HTTPS equivalence, or fetch redirects to
discover a canonical URL. Purely syntactic normalization may normalize scheme
and host casing and default ports; further equivalence requires explicit proof
and retained provenance. The exact approved normalizer and corpus belong to #31,
not to a production migration installed here. Existing legacy normalized URLs
may already have lost information; unavailable raw values must be marked unknown.

ASSET_ONLY is provisional: a candidate URL is not evidence of a page use. A later
supported observation may create a **reversible** link from the provisional use
to a page WebUse of the same photograph lineage. Preserve the provisional UUID,
original observations and scopes; do not rewrite it into the page identity.
If multiple pages fit, the raw/normalized URL is uncertain, or the photograph
lineage is ambiguous, keep explicit unresolved candidates instead of choosing a
page. Removing/correcting that attachment restores the independent provisional
view without deleting triage or evidence. Similar asset URLs alone cannot merge
pages, photograph identities or evidence. #31 must specify attachment evidence
and ambiguity resolution before implementing this transition.

## Current compatibility boundary

PR4 is the acceptance baseline for the **legacy compatibility projection**, not
a claim that its discovery key is the future WebUse key. Legacy discovery
identity is `(source_kind, page_url or '', candidate_image_url or '')` within an
image/current group. Preserve that key and every row's state for compatibility;
#31 intentionally changes the future page-use projection. The following
implementation points and existing tests are normative inputs for compatibility:

| Current invariant | Code / existing regression proof |
| --- | --- |
| One logical discovery per identity among current group members; folds preserve rows. Survivor is earliest `first_seen_at`, then match ID, not primary. | `backend/repositories/discovery_merge.py:_identity`, `coalesce_discoveries`; `tests/backend/test_grouping_audit_fixes.py:test_grouping_already_scanned_photos_coalesces_discoveries`. |
| Merged conflict is UNREVIEWED/new; further joins and domain rules cannot silently resolve it. | `discovery_merge.py:_merged_state`; `match_repo.py:apply_rule_to_unreviewed_matches`; `test_joining_third_photo_cannot_silently_resolve_existing_conflict`, `test_repeated_conflicts_keep_a_single_banner`. |
| `obs_*` is original triage captured once. `rb_*` is the pre-current-cycle state, including inheritance and unresolved conflict. | `discovery_merge.py:_capture_observation_triage`, `_restore_observation_triage`; `test_latest_explicit_decision_survives_a_second_group_cycle`, `test_rollback_preserves_an_unresolved_pre_cycle_conflict`. |
| Selecting the same classification, editing notes or acknowledging can be an explicit review. Only explicit classification resolves conflict. | `match_repo.py:update_classification_and_notes`; `test_explicit_review_selecting_the_unchanged_classification_counts`, `test_rollback_preserves_an_unresolved_pre_cycle_conflict`. |
| Explicit post-merge review keeps the current carrier's logical decision after dissolution; siblings regain their pre-cycle decisions. A group decision is not copied to every sibling. | `discovery_merge.py:reconcile_group_folds`; `test_dissolving_after_explicit_review_keeps_the_groups_decision`. |
| Permanent purge inheritance travels through later handovers. Inheritance acquired before a later cycle is its rollback state; inheritance acquired during the cycle blocks rollback. | `discovery_merge.py:release_discoveries`, `_ROLLBACK_ALLOWED`, `_promote`; `test_pre_cycle_inheritance_rolls_back_with_a_later_reversible_group`, `test_purge_during_the_current_cycle_keeps_the_newly_inherited_decision`, `test_inherited_decision_travels_through_a_later_ordinary_handover`. |
| LINEAGE is permanent, does not keep a GROUP cycle open and does not make a temporary group conflict permanent. | `discovery_merge.py:_write_merge`, `reconcile_group_folds`; `test_lineage_observation_does_not_prevent_group_rollback`, `test_dissolving_after_a_reexport_keeps_the_lineage_merged_decision`, `test_reexport_does_not_make_a_temporary_group_conflict_permanent`. |
| Scan history belongs to the actual searched content; replacement does not inherit physical scan counts. | `image_repo.py:transfer_representation_history`; `tests/backend/test_perceptual_grouping.py:test_group_scan_records_physical_history_only_on_searched_representative`. |

Original triage is not the same as immutable provider evidence. Rediscovery
currently updates timestamps/session pointers, and the current schema does not
retain every provider response as an observation event. A unique LINEAGE match
can be re-homed by changing `matches.image_id` when the target has no observation
of that use (`discovery_merge.py:coalesce_discoveries`). `obs_*` contains no
original representation/image ID. Purge physically deletes some legacy rows and
keeps textual `inherited_from`, not a complete original observation. Migration
must label those provenance gaps; it must not reconstruct missing source IDs or
provider responses from current ownership, names or editable notes.
For a uniquely re-homed LINEAGE observation, the original searched file/path is
unknown unless an independently retained provider-call/scan record proves it;
the successor's current filename and path must not be presented as that original
file. Retained legacy aliases are clues, not proof that a particular observation
came from that alias.

## Transition contract

Each operation is one SQLite transaction covering membership, links, decision
projection and its history event. User source files are read only. Eligibility
is resolved again before a provider call; an identity never grants access to an
archived, disabled or unavailable source.

| Operation | Durable target transition | Required PR4-compatible visible result |
| --- | --- | --- |
| Create group | Allocate group UUID and membership version; open a GROUP cycle snapshot only for discovered uses that actually acquire merged state. Original photograph/representation/WebUse IDs remain. | At least two distinct, existing, ungrouped representations. Primary explicit or first requested member. Coalesce existing discoveries without deleting their observations. |
| Join group | Append membership/version event; add reversible GROUP association equivalences for matching WebUses. Snapshot the joining association's pre-cycle state. | Add an ungrouped member atomically. Existing primary remains unless explicitly chosen. Existing unresolved conflicts remain unresolved. |
| Leave group | Close that member's membership interval and affected GROUP links. Restore its independent association's pre-cycle projection, subject to current-cycle permanent inheritance. | Remaining group receives logical triage via an observation handover if needed. Departing former canonical retains a post-merge explicit decision, otherwise rolls back when independent. Primary leaves → smallest remaining image ID during compatibility phase. |
| Split into multiple groups | Target operation: close old group and its GROUP links; allocate distinct group UUIDs for partitions of ≥2, leave singleton partitions independent; freeze old membership snapshot. Never alter LINEAGE or historical scopes. | No arbitrary split API exists today. Future implementation must apply departure/dissolution rules per resulting component transactionally, retain each original observation and hand over within each remaining component. Preserve inherited projections in multiple components where PR4 does so; forbid duplicating explicit decision events or broadening their recorded scope. |
| Dissolve | Tombstone group; close memberships and GROUP links. Keep group UUID, cycle snapshots and decision history queryable. | All members independent. Restore pre-cycle states except explicit post-merge carrier decisions and inheritance newly acquired during the cycle. Permanent LINEAGE links remain. |
| Select primary | Append a versioned primary event naming an existing member. | Update primary flags only; no change to association/observation owner, evidence, triage or scope. |
| Same path, same content | Preserve representation and lineage UUIDs. Update location/presence metadata. | Existing record stays; an unambiguous SHA-based rename can reconcile the old record. Ambiguous identical copies cannot silently pick an identity. |
| Same path, changed content, validated grouped re-export | Allocate/reuse the new physical representation as the current indexer permits; retain old representation as unavailable history. Add permanent predecessor→successor LINEAGE and preserve group role. If adopting a known target lineage, retain both photograph IDs via permanent equivalence. | Existing grouped predecessor and valid dHash candidate are required for automatic transfer. Combine permanent decisions, carry an already open GROUP rollback cycle, and exclude temporary siblings from its permanent baseline. Physical scan history remains on old content. |
| Same path, changed unrelated/uncertain content | Old representation becomes historical; new representation and new photograph UUID. No automatic GROUP or LINEAGE edge. | Old discoveries remain historical. New content is independent; low-information/unavailable hashes fail open to separate review. Currently ungrouped replacements also receive no automatic LINEAGE transfer, even if perceptually similar. |
| Purge library/representation | Tombstone affected library/representation and end its locations/memberships. Preserve referenced photograph, WebUse, observation, decisions and scopes. Append inheritance/handover event when a surviving equivalence component keeps a discovery. | Before legacy row deletion, hand over existing folded observations by earliest first-seen then match ID. Only when no surviving observation exists, re-home to present active member first, then primary, then smallest image ID. Retain logical triage and every inherited origin. No surviving component → retain only historical target records, no active discovery. |
| Archive/disable | Record monitoring state; no identity, membership or decision change. | History remains reviewable; archived/disabled selected sources cannot be searched. An active group member can supply an available fallback. |
| Offline/missing/reconnect | Record availability and location history; no identity or scope change. | No provider call without an eligible available source. Existing history remains; active grouped missing selection can use an eligible sibling. Reconnection restores access to the same indexed content identity. |

Split is a new operation specification, not an assertion about PR4's API.
Joining two existing groups is also unsupported today. A future group merge
must use the same membership/cycle transitions with both predecessor UUIDs kept
as history; it cannot silently create permanent photograph equivalence.

For example, A+B+C+D is reviewed IRRELEVANT on canonical A and later split into
A+B and C+D. PR4's sequential equivalent is leave A, leave B, regroup A+B;
the remaining C+D receives the reviewed logical state through B then C while A
keeps its explicit post-merge state. Both components may display IRRELEVANT.
The target implementation must retain **one** original decision event and its
unchanged A+B+C+D scope snapshot, append the carrier/handover links, and label
the secondary projection as inherited. It must not manufacture new explicit
reviews, expand that historical snapshot to later members, or copy a license.
The new atomic split follows this deterministic partition order: the partition
containing the original carrier first, then partitions ordered by their lowest
legacy image ID (or stable representation UUID after the compatibility phase).
Every resulting group gets a fresh UUID; the old group's identity stays historical.

## Fixed scopes for decisions, permissions and records

Store scope references as explicit UUID lists plus a membership/version or
cycle snapshot, never as a query such as “all current members of group G”. A
scope is immutable once a record is created; changing intent appends a record
that supersedes the old one. Empty scope is invalid. A scope snapshot can
reference tombstones and inactive objects. Resolving a lineage alias for current
display does not rewrite the original scope.

| Record | Stored scope and split/purge behavior |
| --- | --- |
| WebUse / association | The photograph + conservative-page key has no mutable group scope. Two photographs on one page stay separate; asset variants for one photograph/page remain subordinate. A historical association keeps its original target. GROUP equivalence records exact group UUID, membership version, affected associations and cycle; split ends that equivalence without changing WebUse IDs or historical targets. A provisional ASSET_ONLY attachment is separately reversible and never rewrites the original scope. Purge retains referenced uses/assets and history. |
| Classification/acknowledgement | Photograph–WebUse association or a GROUP logical-discovery snapshot: exact association/member UUIDs, cycle UUID and carrier at review. Preserve historical decision after split. Current projection follows PR4: explicit post-merge decision remains on its carrier (or explicit handover successor), not every separated sibling. A later join cannot extend the old scope. |
| Notes | Same fixed discovery or photograph scope as chosen at creation. Legacy merged notes remain provenance and cycle rollback input. New notes retain author/time and original scope; moving a carrier does not relabel the author's target. Editing notes alone does not resolve classification conflicts. |
| Authorization/license | Explicit photograph lineage UUIDs or representation UUIDs, WebUse/domain restrictions and temporal bounds, captured at creation. A GROUP snapshot is allowed only as an explicit finite member list. Split, join, primary changes and purge never broaden it or turn APPROVED triage into legal authorization. No authorization module exists today; legacy APPROVED must not be imported as a license. |
| Provider/manual evidence | Original representation UUID, content SHA at capture, photograph lineage at capture, WebUse UUID, provider-call ID/time, and immutable evidence artifact digest when such an artifact exists. Split and handover alter presentation only. Purge leaves the metadata/artifact according to explicit retention, and original tombstone references remain valid. Unknown legacy origins remain unknown. |
| Case | Explicit photograph/WebUse associations, evidence/decision IDs and scope snapshot at creation. Split yields a “scope spans separated identities” review state; it neither duplicates the case nor silently changes defendants, ownership claims, evidence or authorizations. Purge leaves a historical case with unavailable source labels. Cases are a future module, not generated here. |

Permanent LINEAGE carries the logical history as established by PR4. It does not
change the **recorded** target of an old license or evidence record. Evaluating
whether a license applies to a successor representation must obey that license's
explicit lineage/representation scope and terms; no group equivalence suffices.
An operation can change a current projection while all historical decisions and
their original scopes remain immutable.

The GROUP member list is stored in `scope_members`, tied to the immutable
`scope_snapshots` row and the exact `group_memberships` version at the review
event. It is not recomputed when reading a decision. A later handover appends
`decision_id`, former/new carrier association IDs, source group/cycle and cause;
the same historical decision follows that carrier chain without rewriting its
scope. If a member joined **after** the decision and later receives its logical
triage through a PR4 handover, the view labels that state as inherited from the
original scoped discovery. It creates no new explicit review event about that
member and no new license/authorization target. An automatic merge may project
compatible classifications, but it is not evidence of a human decision for the
new member. Only a new explicit user review with a newly captured member list can
record that intent; the later UI must expose the reviewed scope and detect a
membership-version change before accepting a review.

Represent grouping cycles explicitly: one cycle UUID, start event, pre-cycle
triage/inheritance/conflict snapshot per affected association and end event.
Store original observation triage separately. A repeated cycle captures the
latest independent state, never the first `obs_*` state. Post-start explicit
review and inheritance events have monotonic local event sequence numbers so
equal timestamps or wall-clock adjustment cannot change rollback decisions.
Migration maps known legacy timestamps conservatively; it does not infer missing
events. Future event sequencing must reproduce current conditional behavior,
including acknowledgement/notes being explicit but not clearing conflicts.

## Indicative target schema

This is a relational outline for later implementation, **not executable migration
DDL**. Every referenced UUID uses `FOREIGN KEY ... ON DELETE RESTRICT`; append
tables cannot be cascade-deleted. `tombstoned_at` suppresses operational listings
without invalidating references. Physical deletion, if ever required for a
separate explicit retention request, is a distinct audited workflow checking
every dependent record; an ordinary library purge must not run it.

| Table | Key fields / constraints |
| --- | --- |
| `photographs` | `id UUID PK`, `created_event_id`, `tombstoned_at`; permanent original UUID. |
| `representations` | `id UUID PK`, `photograph_id FK`, immutable content SHA/acquisition metadata, `legacy_image_id UNIQUE NULL`, `tombstoned_at`. Current path is not identity. |
| `representation_locations` | UUID PK, representation/library FKs, path, validity interval, availability events. At most one live indexed record per normalized path; archived aliases are history rather than real filesystem paths. |
| `groups` / `group_memberships` | Group UUID PK/tombstone; member representation FK, joined/left events; one current group per representation, at least two members in active groups at commit. Versioned primary references an active member. |
| `web_uses` | UUID PK; original photograph FK, `kind PAGE or ASSET_ONLY`, conservative normalized page identity NULL for provisional asset-only, normalization version. Page identity uniqueness is **per photograph**, not global and not candidate-URL-dependent. Permanent lineage resolution retains UUID aliases; it must enforce one resolved page-use identity without rewriting original targets. |
| `web_use_assets` | UUID PK; WebUse FK, raw/normalized asset URL, normalization version, supporting observation FK, first/last evidence and provider details. Multiple observed CDN/assets belong beneath one photograph/page use; keep raw variants and evidence instead of selecting one asset as identity. |
| `asset_page_attachments` | UUID PK; provisional ASSET_ONLY and page-WebUse FKs, photograph-lineage proof, supporting observations, created/end events, state/candidate history. Reversible links, explicit unresolved/ambiguous candidates and no automatic redirect fetch. Retain original scopes and UUIDs on attach/detach. Detailed #31 rules precede implementation. |
| `photograph_web_uses` | Association UUID PK; photograph/WebUse FKs; UNIQUE pair; tombstone/history state. Current discovery is a projection over these associations and active GROUP/permanent LINEAGE links. |
| `association_equivalences` | UUID PK; left/right association FKs, `kind GROUP or LINEAGE`, group/cycle FK for GROUP, created/end events. GROUP can end; LINEAGE cannot end via group operations. Validate photograph relationship, conservative page identity and evidence context; never enforce the old candidate-dependent triple as the target WebUse key. |
| `lineage_links` | UUID PK; predecessor/successor representation FKs, photograph equivalence refs if needed, verification provenance/event, historical group role. Preserve both ends; forbid self-links and cycles. |
| `observations` | UUID PK; association, original representation, WebUse/asset and provider-call FKs; original SHA/time/source/raw URLs and normalization versions; legacy match mapping and original legacy key/state, provenance completeness enum `KNOWN`, `PARTIAL`, `UNKNOWN`. Missing proof is not filled by a guessed current owner. |
| `decision_events` / `scope_snapshots` / `scope_members` | Event UUID PK + unique monotonic local sequence; association FK, explicit/automatic origin, classification/notes/acquittement, immutable scope FK and carrier/handover reference. Snapshot members have typed FKs to retained targets. |
| `group_cycles` / `cycle_baselines` | Cycle UUID PK/group FK, start/end events; association FK with pre-cycle triage, conflict and inheritance refs. Original observation provenance is separate. |
| `inheritance_events` | UUID PK; source/recipient association and tombstoned representation FKs; cause `PURGE` or handover relation. Preserve every origin structurally rather than parsing notes. |
| Future `authorizations`, `evidence`, `cases` | UUID PK + immutable scope FK; explicit evidence/decision/link tables with RESTRICT FKs. No automatic population from existing triage. |
| `legacy_identity_map` / `migration_provenance_gaps` | Original table/integer ID→retained UUID mapping; mapping version and uniqueness; unresolved origin/cycle/lineage facts recorded with reason and source proof. Never treat an alias as missing data to overwrite. |

Enforce local graph and membership invariants inside write transactions and
validate them before commit; FK checks alone cannot enforce graph acyclicity,
one open cycle or membership-dependent primary references. Keep logical view
resolution bounded and indexed. The implementation must retain a compatibility
mapping for old route IDs and observations' inspect links until an explicit API
version transition, independently of thumbnail cache keys (still SHA based).

## Examples and executable compatibility fixtures

`tests/fixtures/identity_contract.json` supplies nine concrete legacy scenarios.
`tests/backend/test_identity_contract.py` runs their operation/expectation lists
against migrated temporary SQLite repositories, checks foreign keys after each
step, and confirms source bytes remain unchanged. It does not call any provider.

1. A/APPROVED and B/UNAUTHORIZED group: conflict. Dissolve without review restores
   their respective decisions, even when B was primary.
2. Explicit group classification IRRELEVANT stays on A's carrier after dissolve;
   B restores UNAUTHORIZED. A's original APPROVED remains `obs_*` provenance.
3. Editing group notes is explicit; it retains the carrier's unresolved conflict
   after dissolve but does not manufacture a classification decision.
4. A second cycle restores the latest IRRELEVANT decision rather than original
   APPROVED; its new baseline closes on dissolution.
5. Select B as primary while A's older discovery remains canonical: no discovery
   ownership movement.
6. Purge A in A+B+C+D: B inherits A's logical triage despite D being primary.
   B later leaves; C receives that same inheritance and keeps it on dissolution.
7. Re-export A into known C while A+B has a temporary conflict: LINEAGE remains
   permanent, and dissolution restores combined A/C permanent decisions without
   B's temporary notes/conflict.
8. A's unique discovery transferred to C changes its legacy `image_id`; the
   absence of an original-image column is an asserted **known limitation**.
9. Sequential split of A+B+C+D into A+B and C+D preserves the explicit carrier
   state and the inherited remaining-component state; this constrains the future
   atomic split without claiming an existing split API.

The LINEAGE examples exercise the repository boundary after validation. Existing
indexer regressions cited above verify real same-path replacement detection and
unrelated-content rejection. Target UUID uniqueness, tombstone constraints,
scope behavior for future authorizations/evidence/cases and arbitrary split are
specifications for the future implementation; these legacy tests do not prove
those unimplemented features. They also do not prove #31's future page-key
normalization, CDN consolidation or ASSET_ONLY attachment behavior. Those need
their own target adapter/corpus tests; the fixture intentionally preserves the
legacy candidate-dependent key.

Run the focused examples with:

```powershell
python -m pytest -q tests/backend/test_identity_contract.py
```

## Migration procedure and acceptance gate

1. Implement and validate #48's consistent SQLite backup, integrity checks and
   restore workflow before installing a production identity migration. Quiesce
   catalog writers/provider work. Verify the backup by opening/restoring a
   separate copy, not merely by seeing a file exist. Record source schema/head
   and deterministic pre-migration counts/content digests of triage/history.
2. Add target tables and a durable migration ledger without modifying source
   images. Create UUID mappings once in the migration transaction; a committed
   rerun reuses them. A fully rolled-back attempt exposed no IDs and can allocate
   new ones. Separate the legacy integer API map from durable UUID keys.
3. Allocate photograph/representation UUIDs for surviving legacy images and
   group UUIDs for current groups. Import current membership/primary history as
   “known at migration”, not as fabricated past events. Infer permanent lineage
   only from actual stored LINEAGE/proven source records; retain separate
   lineages where evidence is insufficient. Never deduce lineage from a path
   alias, shared SHA or dHash alone.
4. Preserve every physical legacy match/folded row under a mapped observation UUID,
   including its legacy `(source_kind, page_url, candidate_image_url)` key and
   row state. Populate the separate legacy projection without reinterpretation.
   After #31's conservative normalizer and attachment contract are implemented
   and reviewed, the **target** projection creates page WebUses per known durable
   photograph + conservative page identity; asset variants become child records.
   Two photographs on one page remain distinct. Keep ASSET_ONLY provisional and
   uncertain page/lineage attachments explicit. Preserve available raw URLs and
   their versions, never invent originals or fetch redirects. Consolidating
   legacy CDN rows for a single photograph/page must retain every row's triage,
   notes, rule provenance, first/last timestamps, acknowledgement, inheritance
   and provider/scan history. Conflicting reviewed classifications require an
   explicit unresolved conflict; consolidation is not a new human decision and
   cannot overwrite original observation state or fixed scope. Re-homed origins,
   lost URL content, deleted observations and unavailable provider responses are
   PARTIAL or UNKNOWN gaps, explicitly recorded; no guessed original evidence.
5. Translate GROUP folds into revocable links/current cycle baselines and LINEAGE
   folds into permanent links. Preserve `obs_*` separately from `rb_*`, including
   `rb_inherited_*` and `rb_triage_conflict`. Apply existing migration 019/020
   conservative conflict backfill principles; editable note text cannot prove
   that a conflict did not exist. Import explicit-review/inheritance ordering
   only when legacy timestamps establish it. Flag ambiguous equal/missing times
   for conservative review rather than letting generated sequence order invent
   a decision. Historical dissolved group IDs are not recoverable and must not
   be fabricated.
6. Populate a shadow **legacy compatibility** projection; compare its identity
   sets, classification, notes, conflict/new/acquittement state, counts and
   accessible originals against the old projection. Replay this fixture set
   plus PR4's grouping/indexing/history regressions against that adapter. Test
   #31's target projection separately: its page/CDN count can intentionally
   differ, while every legacy row and decision remains recoverable. Require
   same-page two-photograph separation, one-photograph CDN consolidation with
   conflicts/history preserved, query-content separation and reversible/ambiguous
   ASSET_ONLY attachment tests. Exercise all transition rows, repeated cycles,
   partial origins and interrupted reruns.
   Confirm FK/graph checks, UUID map stability, no silent scope expansion, and
   tombstone behavior with cases/evidence fixtures when those modules exist.
7. Switch the readers/writers atomically only after shadow equivalence and all
   four repository verification tiers pass. The later schema PR must document
   rollback/restore steps and the independent review outcome. Restore the
   verified database backup on failure; do not invent a lossy “down migration”
   that discards UUID relationships or post-cutover decisions. Preserve source
   files and avoid paid calls throughout validation.

This ADR deliberately records both preserved behavior and unavailable historical
facts. It supplies the boundary for schema, association and case work without
claiming that future modules or a lossless reconstruction already exist.
