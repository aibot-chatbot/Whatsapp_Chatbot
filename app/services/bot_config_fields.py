"""Canonical persona field names for ``public.bot_configs``.

Three persona values were historically stored under two column names each.
``settings_service`` and ``profile_service`` both read the pair with a fallback
and both wrote the value into *both* columns, so the duplication had to be kept
in sync by hand in two files.  This module is the single definition of that
mapping.

Canonical column                Legacy column (deprecated)
------------------------------  ---------------------------
``business_description``        ``business_objective``
``tone``                        ``response_style``
``custom_prompt``               ``prompt_text``

The canonical names win because they are the only ones anything outside this
table's two writer services uses: ``rag_service`` builds the LLM prompt from
``business_description``/``tone``/``custom_prompt`` (:671-672, :706),
``match_service`` reads the first two (:64-65), the API responses expose them,
and the prompt-template variables advertised to users in the UI are
``{business_description}`` and ``{tone}``.  The legacy trio is written by two
files and read by those same two files as a fallback -- it has no other reader.

Both functions assume the three columns are free text.  A pair whose value can
be legitimately falsy (a number, a boolean) must not be added to
:data:`LEGACY_ALIASES` without revisiting the ``or`` chains below, which treat
every falsy value as absent.

Rollout note: :func:`resolve_persona_fields` keeps the legacy fallback so rows
that the ``031`` backfill has not reached still resolve.  :func:`persona_write_payload`
writes ``NULL`` into the legacy columns rather than omitting them, so a row
touched by this code can never leave a stale mirror behind for the fallback to
resurrect.  Both can be deleted once ``031`` has been applied everywhere and no
pre-unification code is running; see the rollback file for the sequencing.
"""

from collections.abc import Mapping
import json
from types import MappingProxyType
from typing import Any, NamedTuple

#: Canonical column name -> the deprecated column that mirrored it.
LEGACY_ALIASES: Mapping[str, str] = MappingProxyType({
    "business_description": "business_objective",
    "tone": "response_style",
    "custom_prompt": "prompt_text",
})

# ---------------------------------------------------------------------------
# Persona provenance
# ---------------------------------------------------------------------------
# The three values below can be typed by the client OR derived from the
# client's own ingested documents.  Without a record of which happened, a
# re-ingest cannot tell a value it may refresh from one it must never touch,
# and a client who genuinely wants to be called "Your Company" is
# indistinguishable from one who never opened the form.
#
# Storage: ONE jsonb column, ``bot_configs.persona_provenance``, holding
# ``{field: marker}``.  Chosen over three sibling columns and over a separate
# table for one decisive reason: provenance is written in the *same* single
# INSERT/UPDATE as the value it describes, so the two can never disagree.
# A sibling table would need a second PostgREST round-trip that can fail on its
# own, leaving a derived value marked client-entered -- an unfixable state.
# Sibling columns would also work, but each new persona field would then need
# its own migration on a table whose DDL is not in this repository, and the
# persona set has already proven unstable (see 031).
# ---------------------------------------------------------------------------

#: The persona values that can be derived from ingested documents.  NOT the
#: same set as :data:`LEGACY_ALIASES`: ``company_name`` never had a legacy
#: mirror, and ``custom_prompt`` is a template the client writes, never derived.
DERIVED_PERSONA_FIELDS: tuple[str, ...] = (
    "company_name",
    "business_description",
    "tone",
)

PROVENANCE_COLUMN: str = "persona_provenance"

#: The client typed this value.  Never overwritten by a derivation.
PROVENANCE_CLIENT: str = "client_entered"
#: Derived from an ingested document.  A later ingest may refresh it.
PROVENANCE_DERIVED: str = "derived"
#: No record either way -- every row written before 032 is in this state.
PROVENANCE_UNKNOWN: str = ""

PROVENANCE_MARKERS: frozenset[str] = frozenset({
    PROVENANCE_CLIENT,
    PROVENANCE_DERIVED,
})

#: The exact strings ``settings_service.DEFAULT_SETTINGS`` writes into the row
#: when nobody filled the form in.  A pre-existing row holding one of these
#: byte-for-byte is treated as "never set" -- see :func:`may_derive`.
#: ``settings_service.DEFAULT_SETTINGS`` is built from this mapping so the two
#: cannot drift apart.
SYSTEM_PLACEHOLDER_VALUES: Mapping[str, str] = MappingProxyType({
    "company_name": "Your Company",
    "business_description": "No business description provided.",
    "tone": "Friendly",
})


class PersonaMerge(NamedTuple):
    """Result of :func:`merge_persona_write`: what to store, and its origin."""

    values: dict[str, str]
    provenance: dict[str, str]


def resolve_persona_fields(row: Mapping[str, Any] | None) -> dict[str, str]:
    """Read the persona values out of a ``bot_configs`` row.

    Canonical column first, deprecated column as the fallback for rows the
    ``031`` backfill has not reached.  Returns only canonical keys, never emits
    a legacy key, and never mutates ``row``.

    The ``or`` chain is carried over verbatim from the two call sites this
    module replaced, so read behaviour is unchanged by the unification.  It
    disagrees with the ``031`` backfill in one bounded case: a canonical value
    of ``'   '`` is truthy here and wins, while the backfill treats it as blank
    (``btrim(...) = ''``) and overwrites it from the legacy column.  Such a row
    therefore reads differently before and after the migration; section 11 of
    the preflight script enumerates every row in that state.

    The ``str`` in the return type holds for the ``text`` columns this is meant
    to be called with; a non-string value is passed through as-is.
    """
    source = row or {}

    return {
        canonical: source.get(canonical) or source.get(legacy) or ""
        for canonical, legacy in LEGACY_ALIASES.items()
    }


def persona_write_payload(values: Mapping[str, Any] | None) -> dict[str, str | None]:
    """Build the persona slice of a ``bot_configs`` insert/update payload.

    Writes each value under its canonical name only, and explicitly clears the
    deprecated column.  Clearing matters: if the legacy column kept its old
    value, blanking the canonical one would let :func:`resolve_persona_fields`
    fall back and restore the value the user just deleted.

    ``or ""`` coalesces every falsy value, so ``None``, ``0`` and ``False`` are
    all written as ``''``.  This deliberately narrows the ``.get(name, "")``
    the two writers used before, which passed those through to the column: all
    three columns are free text, so no falsy value carries meaning, and
    coercing ``None`` avoids a not-null violation on a column that may still be
    ``NOT NULL``.  ``values`` reaches here straight from ``request.get_json()``
    in ``profile_service.save_profile``, so it is not necessarily well typed.

    Requires ``data/039_unify_bot_config_persona_fields.sql`` to have been
    applied first -- it drops the NOT NULL that may still guard the legacy
    columns.  Applying the code first surfaces as a loud 23502 not-null
    violation on write, never as silent data loss.
    """
    source = values or {}
    payload: dict[str, str | None] = {}

    for canonical, legacy in LEGACY_ALIASES.items():
        payload[canonical] = source.get(canonical) or ""
        payload[legacy] = None

    return payload


# ---------------------------------------------------------------------------
# Provenance read / decide / write
# ---------------------------------------------------------------------------


def _is_blank(value: Any) -> bool:
    return not str(value or "").strip()


def resolve_persona_provenance(row: Mapping[str, Any] | None) -> dict[str, str]:
    """Read the provenance marker of each derivable field out of a row.

    Returns exactly the :data:`DERIVED_PERSONA_FIELDS` keys, each mapped to a
    member of :data:`PROVENANCE_MARKERS` or to :data:`PROVENANCE_UNKNOWN`.
    Never mutates ``row``.

    Anything that is not a JSON object of recognised markers -- a missing
    column, ``NULL``, a list, a number, unparseable text, an unknown marker
    string -- resolves to unknown rather than raising.  A malformed provenance
    record must degrade to "we don't know", which is the safe direction: unknown
    is then adjudicated by value in :func:`may_derive`.
    """
    raw: Any = (row or {}).get(PROVENANCE_COLUMN)

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = None

    record: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}

    return {
        field: (
            record.get(field)
            if record.get(field) in PROVENANCE_MARKERS
            else PROVENANCE_UNKNOWN
        )
        for field in DERIVED_PERSONA_FIELDS
    }


def may_derive(field: str, value: Any, provenance: str) -> bool:
    """May a derivation overwrite this stored value?

    * ``client_entered`` -- never.  This is requirement 3.
    * ``derived``        -- yes, a later ingest refreshes it.
    * unknown            -- **only** when the stored value is blank or is
      byte-identical to the system placeholder for that field.

    That last clause is the backfill assumption for every row written before
    032, and it is deliberately narrow.  Treating all pre-existing rows as
    client-entered would leave the reported bug unfixed for the entire existing
    tenant base -- those rows are precisely the ones holding "Your Company".
    Treating them all as derived would destroy values clients really typed.
    Matching the placeholder exactly is the only available evidence that nobody
    typed anything, because the placeholder is a string the *system* writes.

    Known cost, accepted: a client who deliberately chose the exact placeholder
    (most plausibly ``tone = "Friendly"``) loses it to the first derivation.
    The loss is bounded and self-healing -- the field then carries ``derived``,
    and the moment the client retypes it, it becomes ``client_entered`` and is
    permanent.
    """
    if provenance == PROVENANCE_CLIENT:
        return False
    if provenance == PROVENANCE_DERIVED:
        return True

    return _is_blank(value) or value == SYSTEM_PLACEHOLDER_VALUES.get(field)


def merge_persona_write(
    current_values: Mapping[str, Any] | None,
    current_provenance: Mapping[str, Any] | None,
    incoming: Mapping[str, Any] | None,
    *,
    source: str,
) -> PersonaMerge:
    """Decide the stored value and provenance of each derivable field.

    ``source`` is :data:`PROVENANCE_CLIENT` for a human edit or
    :data:`PROVENANCE_DERIVED` for a document-derived write; they follow
    different rules and this is the single place either is applied.

    Client edits, keyed on **presence** of the field in ``incoming``:

    ===========================  ==============================================
    field absent                 keep the stored value *and* its provenance
    present but blank            clear both -- the client deleted it on purpose
    present and non-blank        store it, mark ``client_entered``
    ===========================  ==============================================

    Presence is what makes ``save_profile``'s full-replace semantics safe: a
    partial body no longer blanks -- or silently re-provenances -- a field it
    never mentioned.

    Derived writes are filtered by :func:`may_derive`, and additionally never
    *persist* a system placeholder: a field the derivation could not fill is
    stored blank instead, so the row never carries "Your Company" as data.

    Returns new mappings; neither argument is mutated.
    """
    stored = current_values or {}
    provenance = current_provenance or {}
    proposed = incoming or {}

    values: dict[str, str] = {}
    markers: dict[str, str] = {}

    for field in DERIVED_PERSONA_FIELDS:
        kept_value = stored.get(field) or ""
        kept_marker = (
            provenance.get(field)
            if provenance.get(field) in PROVENANCE_MARKERS
            else PROVENANCE_UNKNOWN
        )

        if source == PROVENANCE_CLIENT:
            if field not in proposed:
                values[field], markers[field] = kept_value, kept_marker
            elif _is_blank(proposed.get(field)):
                values[field], markers[field] = "", PROVENANCE_UNKNOWN
            else:
                values[field] = proposed[field]
                markers[field] = PROVENANCE_CLIENT
            continue

        derivable = may_derive(field, kept_value, kept_marker)

        if _is_blank(proposed.get(field)) or not derivable:
            # Never write a placeholder back into a field a derivation is still
            # allowed to fill: blank is the honest representation of "not
            # derived yet", and it stays derivable.
            #
            # Guarded on ``derivable``.  A client CAN legitimately store a value
            # equal to a placeholder -- ``tone = "Friendly"`` is the settings
            # form's pre-selected default (frontend/bots.html:555) -- and
            # blanking that would both destroy a client-entered value, in direct
            # violation of requirement 3, and strand the field permanently:
            # blank + ``client_entered`` is never derivable again.
            if derivable and kept_value == SYSTEM_PLACEHOLDER_VALUES.get(field):
                kept_value = ""
            values[field], markers[field] = kept_value, kept_marker
        else:
            values[field] = proposed[field]
            markers[field] = PROVENANCE_DERIVED

    return PersonaMerge(values=values, provenance=markers)


def persona_provenance_payload(
    provenance: Mapping[str, Any] | None,
) -> dict[str, dict[str, str]]:
    """Build the provenance slice of a ``bot_configs`` insert/update payload.

    Unknown markers are omitted rather than stored as ``""``, so "absent means
    unknown" is the single representation of that state both in the column and
    in :func:`resolve_persona_provenance`.
    """
    source = provenance or {}

    return {
        PROVENANCE_COLUMN: {
            field: source[field]
            for field in DERIVED_PERSONA_FIELDS
            if source.get(field) in PROVENANCE_MARKERS
        }
    }
