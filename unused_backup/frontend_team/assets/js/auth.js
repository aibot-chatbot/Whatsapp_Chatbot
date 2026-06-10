function getReturnUrl() {
    const params = new URLSearchParams(window.location.search);
    const url = params.get('returnUrl');
    if (!url) return 'index.html';

    try {
        const decoded = decodeURIComponent(url);
        if (/^[a-zA-Z0-9._-]+\.html$/.test(decoded)) {
            return decoded;
        }
    } catch (e) {
        // ignore malformed URL
    }

    return 'index.html';
}

function requireLogin() {
    if (localStorage.getItem('isLoggedIn') !== 'true') {
        const current = window.location.pathname.split('/').pop() || 'index.html';
        window.location.replace('login.html?returnUrl=' + encodeURIComponent(current));
    }
}

function clearLogin() {
    localStorage.removeItem('isLoggedIn');
}
