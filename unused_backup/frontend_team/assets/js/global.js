// Global Interactivity for Antigravity AI
document.addEventListener('DOMContentLoaded', () => {
    updateDate();
    initSidebar();
});

function updateDate() {
    const dateEl = document.getElementById('date-display');
    if (dateEl) {
        const options = { year: 'numeric', month: 'long', day: 'numeric' };
        dateEl.innerText = new Date().toLocaleDateString(undefined, options);
    }
}

function initSidebar() {
    // This could be expanded to load from config.json if needed
    // For now, we handle active state based on current URL
    const currentPath = window.location.pathname.split('/').pop() || 'index.html';
    const navLinks = document.querySelectorAll('.nav-link');
    
    navLinks.forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });
}
