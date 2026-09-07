/**
 * Checks if the user is logged in (has a valid token).
 * Redirects to login page if not.
 */
function requireLogin() {
    const token = sessionStorage.getItem("token");
    if (!token) {
        window.location.href = "login.html";
    }
}

function clearChatbotContext() {
    sessionStorage.removeItem("selectedBotId");
}

function clearAuthenticatedSession() {
    sessionStorage.removeItem("token");
    sessionStorage.removeItem("user");
    sessionStorage.removeItem("isLoggedIn");
    clearChatbotContext();
}

function establishAuthenticatedSession(user, token) {
    clearAuthenticatedSession();
    if (
        !user
        || typeof user !== "object"
        || typeof token !== "string"
        || token.trim().length === 0
    ) {
        return false;
    }

    sessionStorage.setItem("isLoggedIn", "true");
    sessionStorage.setItem("user", JSON.stringify(user));
    sessionStorage.setItem("token", token);
    return true;
}

function getLoginDestination(result) {
    const destination = result && result.redirect_url;
    return ["bots.html", "admin.html", "superadmin.html"].includes(destination)
        ? destination : null;
}

function parsePositiveSafeInteger(value) {
    if (typeof value !== "string" || !/^[1-9][0-9]*$/.test(value)) {
        return null;
    }
    const parsed = Number(value);
    return Number.isSafeInteger(parsed) ? parsed : null;
}

async function validateChatbotContext(botId) {
    const normalizedBotId = parsePositiveSafeInteger(String(botId));
    if (!normalizedBotId) {
        clearChatbotContext();
        window.location.replace("bots.html");
        return false;
    }

    try {
        const response = await authenticatedFetch(`/api/bots/${normalizedBotId}`);
        if (!response.ok) {
            clearChatbotContext();
            window.location.replace("bots.html");
            return false;
        }
        sessionStorage.setItem("selectedBotId", String(normalizedBotId));
        return true;
    } catch (_) {
        clearChatbotContext();
        window.location.replace("bots.html");
        return false;
    }
}

/**
 * Helper to fetch data with the Authorization token automatically attached.
 * Use this instead of standard fetch() for any API calls.
 */
async function authenticatedFetch(url, options = {}) {
    const token = sessionStorage.getItem("token");

    // Ensure headers exist
    if (!options.headers) {
        options.headers = {};
    }

    // Add Authorization header if token exists
    if (token) {
        options.headers["Authorization"] = `Bearer ${token}`;
    }

    const response = await fetch(url, options);

    // Auto-logout if unauthorized
    if (response.status === 401) {
        logout();
    }

    // Deactivated account detection
    if (response.status === 403) {
        try {
            const text = await response.clone().text();
            const json = JSON.parse(text);
            if (json.message && json.message.toLowerCase().indexOf("deactivated") !== -1) {
                sessionStorage.setItem("deactivated_message", json.message);
                logout();
                return response;
            }
        } catch (_) {}
    }

    return response;
}

/**
 * Logs the user out by clearing the token and redirecting.
 */
function logout() {
    clearAuthenticatedSession();
    window.location.href = "login.html";
}

/**
 * Redirects member users to bots.html if they try to access an admin-only page.
 * Call this at the top of admin-only pages after requireLogin().
 */
function requireAdminOrOwner() {
    var userStr = sessionStorage.getItem("user");
    if (!userStr) {
        window.location.href = "login.html";
        return;
    }
    try {
        var user = JSON.parse(userStr);
        var role = (user.role || "").toLowerCase();
        if (role !== "admin" && role !== "owner") {
            sessionStorage.setItem("redirect_message", "You do not have permission to access that page.");
            window.location.href = "bots.html";
        }
    } catch (_) {
        window.location.href = "login.html";
    }
}

/**
 * Shows a stored redirect/permission message if one exists.
 * Call on safe pages like bots.html or index.html to display messages.
 */
function showRedirectMessage() {
    var msg = sessionStorage.getItem("redirect_message");
    if (msg) {
        sessionStorage.removeItem("redirect_message");
        alert(msg);
    }
}
