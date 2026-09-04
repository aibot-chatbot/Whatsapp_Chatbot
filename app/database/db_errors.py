"""Shared helpers for reading Postgres error codes off Supabase exceptions.

supabase-py does not raise typed exceptions per SQLSTATE. Depending on the call
path the code arrives either as an attribute or buried in a dict inside args, so
callers that care about a specific failure have to dig for it.

Substring matching on the message ("duplicate key") is the tempting shortcut and
the wrong one: the wording is not part of any contract, it changes with the
server locale, and "already exists" also appears in error text that has nothing
to do with a constraint. Match the SQLSTATE instead.
"""

# https://www.postgresql.org/docs/current/errcodes-appendix.html
UNIQUE_VIOLATION = "23505"


def database_error_code(error):
    """Return the SQLSTATE for a Supabase error, or None if it carries none."""
    code = getattr(error, "code", None)
    if code:
        return str(code)

    for argument in getattr(error, "args", ()):
        if isinstance(argument, dict) and argument.get("code"):
            return str(argument["code"])

    return None


def is_unique_violation(error):
    """True when the error is Postgres rejecting a duplicate on a unique index."""
    return database_error_code(error) == UNIQUE_VIOLATION
