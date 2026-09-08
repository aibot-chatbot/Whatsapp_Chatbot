"""Generic 500 responses that do not hand internals to the client.

Every route used to answer an unexpected failure with ``str(exception)``.
That is the Supabase/httpx/PostgREST error text verbatim, which routinely
names tables, columns, hosts and file paths - free reconnaissance for anyone
able to provoke a 500, and meaningless to the person who hit it.

The server log records the operation and exception type. Exception messages and
tracebacks can contain credentials or customer data and must not be copied into
logs. The client gets one stable sentence it can safely show a user.

Deliberately NOT applied to ``except ValueError`` handlers returning 4xx:
those carry domain messages the user is meant to read ("Company ID not found
in token. Please login again."), and blanking them would be a regression.
"""

from flask import current_app, jsonify

GENERIC_MESSAGE = "Something went wrong on our end. Please try again."


def server_error(context, exc=None, message=None):
    """Log safe failure metadata and return a safe body.

    :param context: static route function name, so the log line is greppable
    :param exc: the caught exception - only its class name is logged
    :param message: optional safe override when a route can say something
                    more useful than the generic sentence
    """
    current_app.logger.error(
        "Unhandled error in %s (%s)",
        context,
        type(exc).__name__ if exc is not None else "unknown",
    )
    return jsonify({
        "status": "error",
        "message": message or GENERIC_MESSAGE,
    }), 500
