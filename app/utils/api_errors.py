"""Generic 500 responses that do not hand internals to the client.

Every route used to answer an unexpected failure with ``str(exception)``.
That is the Supabase/httpx/PostgREST error text verbatim, which routinely
names tables, columns, hosts and file paths - free reconnaissance for anyone
able to provoke a 500, and meaningless to the person who hit it.

The detail belongs in the server log, where operators can read it. The client
gets one stable sentence it can safely show a user.

Deliberately NOT applied to ``except ValueError`` handlers returning 4xx:
those carry domain messages the user is meant to read ("Company ID not found
in token. Please login again."), and blanking them would be a regression.
"""

from flask import current_app, jsonify

GENERIC_MESSAGE = "Something went wrong on our end. Please try again."


def server_error(context, exc=None, message=None):
    """Log the real cause, return a safe body.

    :param context: route function name, so the log line is greppable
    :param exc: the caught exception - logged, never returned
    :param message: optional safe override when a route can say something
                    more useful than the generic sentence
    """
    current_app.logger.exception("Unhandled error in %s: %s", context, exc)
    return jsonify({
        "status": "error",
        "message": message or GENERIC_MESSAGE,
    }), 500
