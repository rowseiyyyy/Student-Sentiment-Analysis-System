/**
 * Asiatech Sentiment Analysis - Main Application
 * Updated for "Asiatech Feedback Casefile" paper theme design.
 * Handles routing, auth state, login forms, and global initialization.
 */

const APP = {
    currentRole: 'student', // 'student', 'admin', 'faculty'

    init() {
        this.setupLoginForms();
        this.setupNavListeners();
        this.setupLogout();
        this.checkExistingSession();
    },

    checkExistingSession() {
        // Public bulletin deep-link (#bulletin) needs no session at all.
        if (window.location.hash === '#bulletin') {
            this.showPublicBulletin();
            return;
        }

        // Check if student is already logged in
        const studentNum = sessionStorage.getItem('asiatech_student_number');
        if (studentNum) {
            STUDENT.currentStudentNumber = studentNum;
            STUDENT.showEvalForm();
            return;
        }

        // Check if admin/faculty is logged in
        const token = API.getToken();
        if (token) {
            const user = API.getUser();
            if (user) {
                if (user.role === 'administrator') {
                    ADMIN.currentUser = user;
                    ADMIN.showDashboard();
                    return;
                } else if (user.role === 'faculty') {
                    FACULTY.currentUser = user;
                    FACULTY.showDashboard();
                    return;
                }
            }
        }
    },

    setLoginRole(role) {
        this.currentRole = role;
        document.querySelectorAll('.role-pill').forEach(p => p.classList.toggle('active', p.dataset.role === role));

        const studentForm = document.getElementById('login-form-student');
        const credentialForm = document.getElementById('login-form-credential');
        const registerForm = document.getElementById('login-form-register');

        studentForm.classList.toggle('hidden', role !== 'student');
        credentialForm.classList.toggle('hidden', role === 'student');
        registerForm.classList.add('hidden');
    },

    setupLoginForms() {
        // Student login
        document.getElementById('login-form-student').addEventListener('submit', (e) => {
            e.preventDefault();
            STUDENT.handleLogin(e);
        });

        // Credential login (admin/faculty) — handled in HTML onclick
        // Registration — handled in HTML onsubmit
    },

    doCredentialLogin(e) {
        e.preventDefault();
        const email = document.getElementById('inp-email').value.trim();
        const password = document.getElementById('inp-pass').value;

        if (this.currentRole === 'admin') {
            ADMIN.handleLogin(email, password);
        } else if (this.currentRole === 'faculty') {
            FACULTY.handleLogin(email, password);
        }
    },

    doRegister(e) {
        e.preventDefault();
        const data = {
            full_name: document.getElementById('inp-rname').value.trim(),
            email: document.getElementById('inp-remail').value.trim(),
            password: document.getElementById('inp-rpass').value,
            role: document.getElementById('inp-rrole').value
        };

        showLoading('Creating account...');
        API.register(data)
            .then(() => {
                showToast('Account created! Please login.', 'success');
                this.hideRegForm();
            })
            .catch(error => {
                showToast('Registration failed: ' + error.message, 'error');
            })
            .finally(() => hideLoading());
    },

showRegForm() {
        document.getElementById('login-form-credential').classList.add('hidden');
        document.getElementById('login-form-register').classList.remove('hidden');
    },

    hideRegForm() {
        document.getElementById('login-form-register').classList.add('hidden');
        document.getElementById('login-form-credential').classList.remove('hidden');
    },

    showForgotForm() {
        document.getElementById('login-form-credential').classList.add('hidden');
        document.getElementById('login-form-register').classList.add('hidden');
        document.getElementById('login-form-forgot').classList.remove('hidden');
        document.getElementById('login-form-reset').classList.add('hidden');
    },

    hideForgotForm() {
        document.getElementById('login-form-forgot').classList.add('hidden');
        document.getElementById('login-form-reset').classList.add('hidden');
        document.getElementById('login-form-credential').classList.remove('hidden');
    },

    async doForgotPassword(e) {
        e.preventDefault();
        const email = document.getElementById('inp-femail').value.trim();
        if (!email) { showToast('Please enter your email.', 'warning'); return; }
        showLoading('Sending reset link...');
        try {
            const result = await API.forgotPassword(email);
            const token = result.reset_token;
            // Auto-fill the token into the reset form for this local deployment.
            if (token) {
                document.getElementById('inp-rtoken').value = token;
            }
            document.getElementById('login-form-forgot').classList.add('hidden');
            document.getElementById('login-form-reset').classList.remove('hidden');
            showToast('Reset link sent! ' + (token ? 'Token auto-filled below.' : 'Check your email.'), 'success');
        } catch (error) {
            showToast('Request failed: ' + error.message, 'error');
        } finally {
            hideLoading();
        }
    },

    async doResetPassword(e) {
        e.preventDefault();
        const token = document.getElementById('inp-rtoken').value.trim();
        const newPassword = document.getElementById('inp-news-pass').value;
        if (!token) { showToast('Please enter the reset token.', 'warning'); return; }
        if (newPassword.length < 8) { showToast('Password must be at least 8 characters.', 'warning'); return; }
        showLoading('Resetting password...');
        try {
            await API.resetPassword(token, newPassword);
            showToast('Password reset successfully! Please sign in.', 'success');
            this.hideForgotForm();
        } catch (error) {
            showToast('Reset failed: ' + error.message, 'error');
        } finally {
            hideLoading();
        }
    },

    /**
     * Navigate to a specific page for a given role
     */
    goToPage(pageId) {
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        const page = document.getElementById(pageId);
        if (page) page.classList.add('active');
    },

    // Public "Action Taken" bulletin — no auth, no API.getUser().
    // Reachable from the login page link or directly via #bulletin.
    showPublicBulletin() {
        this.goToPage('page-public-bulletin');
        const container = document.getElementById('public-bulletin-content');
        container.innerHTML = '<div class="text-center mt-4"><div class="spinner"></div><p>Loading bulletin...</p></div>';
        API.getPublicBulletin()
            .then(data => { BULLETIN.render(container, data); })
            .catch(err => {
                container.innerHTML = '<div class="page-header"><h1>Action Bulletin</h1></div>' +
                    '<div class="card"><div class="empty-state"><div class="empty-icon"><i class="fas fa-bullhorn"></i></div>' +
                    '<h3>Unable to load</h3><p>' + escapeHtml(err.message) + '</p></div></div>';
            });
    },

    showLogin() {
        this.goToPage('page-login');
    },

setupNavListeners() {
        // Student nav tabs (form / submissions)
        document.querySelectorAll('#nav-student .nav-links li button').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('#nav-student .nav-links li button').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                if (btn.dataset.stab === 'submissions') {
                    STUDENT.showSubmissions();
                } else {
                    STUDENT.showEvalForm();
                }
            });
        });

        // Admin nav tabs
        document.querySelectorAll('#nav-admin .nav-links li button').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('#nav-admin .nav-links li button').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                ADMIN.renderTab(btn.dataset.tab);
            });
        });

        // Faculty nav tabs
        document.querySelectorAll('#nav-faculty .nav-links li button').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('#nav-faculty .nav-links li button').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                FACULTY.renderFacultyTab(btn.dataset.ftab);
            });
        });

        // Student eval tabs
        document.querySelectorAll('#eval-tabs .tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('#eval-tabs .tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                STUDENT.renderFormTab(btn.dataset.tab);
            });
        });
    },

    setupLogout() {
        // Logout is handled by each module's logout function called from HTML onclick
    },

    // ============================================================
    // MODAL
    // ============================================================
    openModal(html) {
        document.getElementById('modal-body').innerHTML = html;
        document.getElementById('modal-eval').classList.add('show');
    },

    closeModal() {
        document.getElementById('modal-eval').classList.remove('show');
    }
};

// Close modal on backdrop click
document.addEventListener('click', (e) => {
    const modal = document.getElementById('modal-eval');
    if (e.target === modal) APP.closeModal();
});

// ============================================================
// Initialize the application when DOM is ready
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    APP.init();
});

