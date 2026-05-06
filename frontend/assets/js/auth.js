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

    return response;
}

/**
 * Logs the user out by clearing the token and redirecting.
 */
function logout() {
    sessionStorage.removeItem("token");
    sessionStorage.removeItem("user");
    sessionStorage.removeItem("isLoggedIn");
    window.location.href = "login.html";
}