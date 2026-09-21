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

        studentForm.classList.toggle('hidden', role !== 'student');
        credentialForm.classList.toggle('hidden', role === 'student');
    },

    setupLoginForms() {
        // Student login
        document.getElementById('login-form-student').addEventListener('submit', (e) => {
            e.preventDefault();
            STUDENT.handleLogin(e);
        });

        // Credential login (admin/faculty) — handled in HTML onclick
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


    showForgotForm() {
        document.getElementById('login-form-credential').classList.add('hidden');
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

    // ============================================================
    // VOICE IN A BOX — anonymous open-ended feedback (landing page)
    // ============================================================
    openVoiceBox(e) {
        if (e) e.preventDefault();
        // Start each visit to the drop box with a clean slate.
        var form = document.getElementById('voice-box-form');
        if (form) form.reset();
        var msg = document.getElementById('voice-box-message');
        if (msg) msg.value = '';
        var modal = document.getElementById('modal-voice-box');
        if (modal) modal.classList.add('show');
        // Focus without scrolling the page behind the modal.
        setTimeout(function() { if (msg) msg.focus({ preventScroll: true }); }, 60);
    },

    closeVoiceBox() {
        var modal = document.getElementById('modal-voice-box');
        if (modal) modal.classList.remove('show');
    },

    async submitVoiceNote(e) {
        e.preventDefault();
        var msgEl = document.getElementById('voice-box-message');
        var message = msgEl ? msgEl.value.trim() : '';
        if (!message) {
            showToast('Please write a message before submitting.', 'warning');
            return;
        }

        var submitBtn = document.querySelector('#voice-box-form button[type="submit"]');
        if (submitBtn) submitBtn.disabled = true;
        showLoading('Sealing your message in the box...');

        try {
            // Fully anonymous: this request carries no auth token and no
            // student identifier — only the free-text message.
            await API.createVoiceNote(message);
            this.closeVoiceBox();
            if (msgEl) msgEl.value = '';
            APP.openModal(
                "<div style=\"text-align:center;padding:1rem;\">" +
                "<i class=\"fas fa-check-circle\" style=\"font-size:3rem;color:var(--pos);\"></i>" +
                "<h3 style=\"font-family:var(--font-display);margin:0.5rem 0;\">Message dropped</h3>" +
                "<p style=\"color:var(--ink-soft);max-width:38ch;margin:0 auto;\">Thank you — your voice is in the box. It was analyzed anonymously and will be reviewed alongside other voices.</p>" +
                "<button class=\"btn btn-primary\" style=\"margin-top:1rem;\" onclick=\"APP.closeModal()\">Done</button>" +
                "</div>"
            );
        } catch (error) {
            showToast(error.message || 'Could not submit your message. Please try again.', 'error');
        } finally {
            hideLoading();
            if (submitBtn) submitBtn.disabled = false;
        }
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
    },

    // ============================================================
    // DEFAULT PASSWORD PROMPT — offered (never forced) right after
    // login when the backend flags the account as still using its
    // seed default password (Token.using_default_password).
    // ============================================================
    _defaultPassword: null,

    promptDefaultPasswordChange(plainPassword) {
        // Kept in memory only for the lifetime of this prompt; never
        // written to storage.
        this._defaultPassword = plainPassword;
        this.openModal(
            '<div style="max-width:36ch;margin:0 auto;text-align:left;">' +
            '<h3><i class="fas fa-shield-alt"></i> Security notice</h3>' +
            '<p style="color:var(--ink-soft);">Your account is still using the default password issued by the system. We recommend changing it now.</p>' +
            '<div class="form-group">' +
            '<label for="inp-dp-new"><i class="fas fa-lock"></i> New password</label>' +
            '<input type="password" id="inp-dp-new" class="form-control" placeholder="At least 8 characters">' +
            '</div>' +
            '<div class="form-group">' +
            '<label for="inp-dp-confirm"><i class="fas fa-lock"></i> Confirm new password</label>' +
            '<input type="password" id="inp-dp-confirm" class="form-control" placeholder="Repeat new password">' +
            '</div>' +
            '<button class="btn btn-primary" style="margin-top:.5rem;" onclick="APP.changeDefaultPassword(event)">' +
            '<i class="fas fa-key"></i> Change password now</button> ' +
            '<button class="btn btn-secondary" style="margin-top:.5rem;" onclick="APP.remindLaterDefaultPassword()">' +
            'Remind me later</button>' +
            '</div>'
        );
    },

    remindLaterDefaultPassword() {
        this._defaultPassword = null;
        this.closeModal();
    },

    async changeDefaultPassword(e) {
        if (e) e.preventDefault();
        const newPass = document.getElementById('inp-dp-new').value;
        const confirmPass = document.getElementById('inp-dp-confirm').value;

        if (newPass.length < 8) {
            showToast('Password must be at least 8 characters.', 'warning');
            return;
        }
        if (newPass !== confirmPass) {
            showToast('Passwords do not match.', 'warning');
            return;
        }

        const currentPassword = this._defaultPassword;
        showLoading('Updating password...');
        try {
            await API.updateProfile({ current_password: currentPassword, new_password: newPass });
            this._defaultPassword = null;
            this.closeModal();
            showToast('Password changed successfully.', 'success');
        } catch (error) {
            showToast(error.message || 'Could not change your password. Please try again.', 'error');
        } finally {
            hideLoading();
        }
    }
};

// Close modals on backdrop click
document.addEventListener('click', (e) => {
    if (e.target === document.getElementById('modal-eval')) APP.closeModal();
    if (e.target === document.getElementById('modal-voice-box')) APP.closeVoiceBox();
});

// ============================================================
// Initialize the application when DOM is ready
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    APP.init();
});

