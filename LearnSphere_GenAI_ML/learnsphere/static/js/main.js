// LearnSphere — Main JS

// Cursor glow
const glow = document.getElementById('cursorGlow');
if (glow) {
    document.addEventListener('mousemove', e => {
        glow.style.left = e.clientX + 'px';
        glow.style.top = e.clientY + 'px';
    });
}

// Load and display user level in navbar
async function loadNavLevel() {
    try {
        const res = await fetch('/api/profile');
        const profile = await res.json();
        const levelText = document.getElementById('levelText');
        if (levelText) {
            const map = { beginner: 'Beginner', intermediate: 'Intermediate', advanced: 'Advanced' };
            levelText.textContent = map[profile.level] || 'Beginner';
        }
    } catch(e) {}
}
loadNavLevel();

// Highlight.js init
document.addEventListener('DOMContentLoaded', () => {
    if (typeof hljs !== 'undefined') {
        document.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));
    }
});
