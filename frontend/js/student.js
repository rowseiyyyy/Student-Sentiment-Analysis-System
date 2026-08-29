/**
 * Asiatech Sentiment Analysis - Student Module
 * Updated for "Asiatech Feedback Casefile" paper theme design.
 * Anonymous evaluation flow — no student login/ID required.
 * All evaluation questions, fields, and submit logic preserved.
 */

const STUDENT = {
    currentCourse: null,
    currentYearLevel: null,

    init() {
        // Anonymous flow: no student identity is persisted or restored.
        // Students always start at the login page and click "Open evaluation".
    },

    handleLogin(e) {
        e.preventDefault();
        // Anonymous evaluation — no student number required.
        showToast('Welcome! Please fill out the evaluation form.', 'success');
        this.showEvalForm();
    },

    logout() {
        sessionStorage.removeItem('asiatech_student_course');
        sessionStorage.removeItem('asiatech_student_year_level');
        this.currentCourse = null;
        this.currentYearLevel = null;
        APP.goToPage('page-login');
        document.getElementById('nav-student').style.display = 'none';
    },

    showEvalForm() {
        APP.goToPage('page-student-eval');
        document.getElementById('nav-student').style.display = 'flex';
        document.getElementById('badge-student').textContent = '\u{1F393} Anonymous';
        document.getElementById('student-id-disp').textContent = '';

        // Show the form area
        const formArea = document.getElementById('student-form-area');
        if (formArea) formArea.classList.remove('hidden-block');

        // Restore saved course/year
        if (this.currentCourse) {
            document.getElementById('sel-course').value = this.currentCourse;
        }
        if (this.currentYearLevel) {
            document.getElementById('sel-year').value = this.currentYearLevel;
        }

        this.renderFormTab('professor');
    },

    renderFormTab(tab) {
        const container = document.getElementById('eval-form-content');
        switch (tab) {
            case 'professor':
                container.innerHTML = this.professorForm();
                break;
            case 'staff':
                container.innerHTML = this.staffForm();
                break;
            case 'facilities':
                container.innerHTML = this.facilitiesForm();
                break;
            case 'payments':
                container.innerHTML = this.paymentsForm();
                break;
        }

        const form = container.querySelector('.eval-form');
        if (form) {
            form.addEventListener('submit', (e) => this.handleFormSubmit(e, tab));
        }
    },

    // ============================================================
    // PROFESSOR FORM — questions updated (9 rated items)
    // ============================================================
       professorForm() {
        return `
            <div class="eval-form-card">
                <h2><i class="fas fa-chalkboard-teacher"></i> Professor Evaluation Form</h2>
                <p class="form-desc">Please provide your honest feedback about your professor's teaching performance and professionalism.</p>
                <form class="eval-form" id="professor-form">
                    <div class="form-section" style="margin-top:1.5rem;">
                        <h4 style="margin-bottom:0.75rem;">Rate the following aspects:</h4>
                        ${likertScale('teaching_quality', 'The professor delivers lessons with good teaching quality.')}
                        ${likertScale('mastery', 'The professor demonstrates mastery of the subject matter.')}
                        ${likertScale('clarity', 'The professor communicates and explains lessons clearly.')}
                        ${likertScale('fairness', 'The professor grades and evaluates students fairly.')}
                        ${likertScale('punctuality', 'The professor is punctual and has regular attendance.')}
                        ${likertScale('approachability', 'The professor is approachable and willing to help students.')}
                        ${likertScale('feedback', 'The professor provides timely and constructive feedback on students\' performance.')}
                        ${likertScale('classroom_mgmt', 'The professor manages the classroom effectively.')}
                        ${likertScale('teaching_style', 'The professor\'s teaching style is effective this semester.')}
                    </div>
                    ${textareaField('share_your_thoughts', 'Share your thoughts about this professor (teaching style, strengths, areas for improvement, or anything else).', 'Share your thoughts...')}
                    <button type="submit" class="btn btn-primary btn-block btn-lg mt-3">
                        <i class="fas fa-paper-plane"></i> Submit Professor Evaluation
                    </button>
                </form>
            </div>
        `;
    },

    // ============================================================
    // STAFF FORM — questions updated
    // ============================================================
    staffForm() {
        return `
            <div class="eval-form-card">
                <h2><i class="fas fa-users"></i> Staff Evaluation Form</h2>
                <p class="form-desc">Thank you for your feedback. Please answer the following questions based on your recent experience with our school staff.</p>
                <form class="eval-form" id="staff-form">
                    <div class="form-section">
                        <h4 style="margin-bottom:0.75rem;">Rate the following aspects:</h4>
                        ${likertScale('safety', 'The guards make me feel safe and greet me warmly whenever I enter the campus.')}
                        ${likertScale('registrar', 'The registrar\'s office staff are patient and helpful when answering questions about documents, records, and enrollment.')}
                        ${likertScale('cashier', 'Transactions at the cashier or accounting window are stress-free and handled with professionalism.')}
                        ${likertScale('canteen', 'The canteen staff serve us warmly and keep the food service area clean and organized.')}
                        ${likertScale('substitute', 'Substitutes and temporary staff are well-prepared and keep our regular routines going smoothly.')}
                        ${likertScale('office_staff', 'The office staff quickly reply whenever I ask for help or need paperwork done.')}
                        ${likertScale('admin_comm', 'The school administration keeps us well updated through social media about campus announcements and events.')}
                        ${likertScale('maintenance', 'The maintenance and hallway staff do a wonderful job keeping our school surroundings safe and clean.')}
                    </div>
                    ${textareaField('share_your_thoughts', 'Share your thoughts about our staff (what stood out, what could be improved, or anything else).', 'Share your thoughts...')}
                    <button type="submit" class="btn btn-primary btn-block btn-lg mt-3">
                        <i class="fas fa-paper-plane"></i> Submit Staff Evaluation
                    </button>
                </form>
            </div>
        `;
    },

    // ============================================================
    // FACILITIES FORM — questions updated
    // ============================================================
    facilitiesForm() {
        return `
            <div class="eval-form-card">
                <h2><i class="fas fa-building"></i> Facilities Evaluation Form</h2>
                <p class="form-desc">Please evaluate the school's facilities based on your recent experience.</p>
                <form class="eval-form" id="facilities-form">
                    <div class="form-section">
                        <h4 style="margin-bottom:0.75rem;">Rate the following aspects:</h4>
                        ${likertScale('spaces', 'The school has great spaces like hanging spots, benches, and trees.')}
                        ${likertScale('furniture', 'The classroom tables and chairs are all in good condition.')}
                        ${likertScale('cleanliness', 'General cleanliness in all facilities is observed.')}
                        ${likertScale('bathrooms', 'The bathrooms are always clean and smell fresh.')}
                        ${likertScale('cafeteria', 'The cafeteria or canteen has a clean dining space with plenty of room to sit and eat.')}
                        ${likertScale('monitors', 'The monitor systems in the classrooms are all working properly.')}
                        ${likertScale('computers', 'The lab computers are all easy to use and are well-managed.')}
                        ${likertScale('classrooms', 'The classrooms are always bright, clean, and well-maintained, making me comfortable to work properly.')}
                    </div>
                    ${textareaField('share_your_thoughts', 'Share your thoughts about our facilities (what stood out, what needs improvement, or anything else).', 'Share your thoughts...')}
                    <button type="submit" class="btn btn-primary btn-block btn-lg mt-3">
                        <i class="fas fa-paper-plane"></i> Submit Facilities Evaluation
                    </button>
                </form>
            </div>
        `;
    },

    // ============================================================
    // PAYMENTS FORM — questions updated ("online" question replaced
    // by two new items: fee-info clarity and digital banking trust)
    // ============================================================
    paymentsForm() {
        return `
            <div class="eval-form-card">
                <h2><i class="fas fa-credit-card"></i> Payments Evaluation Form</h2>
                <p class="form-desc">Please answer the following questions based on your recent experience with the payment and accounting services.</p>
                <form class="eval-form" id="payments-form">
                    <div class="form-section">
                        <h4 style="margin-bottom:0.75rem;">Rate the following aspects:</h4>
                        ${likertScale('accessibility', 'The payment portal/counter is easily accessible at convenient times for my schedule.')}
                        ${likertScale('processing', 'My payments or fee clearances are processed and posted to my account in a timely manner.')}
                        ${likertScale('queues', 'The on-site payment queues move quickly and efficiently, even during peak days.')}
                        ${likertScale('courteous', 'Payment personnel are courteous, helpful, and prompt in addressing payment-related inquiries or concerns.')}
                        ${likertScale('accounting', 'Accounting and registrar personnel are helpful, polite, and responsive when addressing payment and document-related inquiries or issues.')}
                        ${likertScale('security', 'I feel confident that my personal and financial information is secure when making transactions.')}
                        ${likertScale('info_clarity', 'The payment process provides clear and accurate information about my fees, balances, and transactions.')}
                        ${likertScale('digital_trust', 'I trust that my personal and financial information is protected when using the digital banking information system for transactions.')}
                    </div>
                    ${textareaField('share_your_thoughts', 'Share your thoughts about our payment process (challenges you faced, suggestions, or anything else).', 'Share your thoughts...')}
                    <button type="submit" class="btn btn-primary btn-block btn-lg mt-3">
                        <i class="fas fa-paper-plane"></i> Submit Payment Evaluation
                    </button>
                </form>
            </div>
        `;
    },

    // ============================================================
    // FORM SUBMIT — All original logic preserved
    // FIX (C1): Stop building a client-side `comment` string that
    // tacks "Average rating: X/5" onto real text. That polluted
    // string was being sent as `comment`, and the backend's
    // _build_text_for_sentiment() uses `comment` as-is when present,
    // completely bypassing the backend fix that keeps Likert scores
    // out of the sentiment text. Now we only send the raw fields
    // (strengths, areas_for_improvement, ratings) and let the
    // backend do the joining — comment is left null.
    //
    // Anonymous flow: student_id is no longer sent/tracked.
    // ============================================================
    async handleFormSubmit(e, category) {
        e.preventDefault();
        const form = e.target;
        const formData = new FormData(form);

        const categoryMap = {
            professor: 'Faculty',
            staff: 'Staff',
            facilities: 'Facilities',
            payments: 'Payment'
        };

        const categoryName = categoryMap[category] || 'Evaluation';
        const ratings = {};
        let thoughtsText = '';
        let evaluatee = '';

        for (const [key, value] of formData.entries()) {
            const num = parseInt(value, 10);
            if (!Number.isNaN(num) && num >= 1 && num <= 5) {
                ratings[key] = num;
            } else if (value && value.trim().length > 0) {
                if (key === 'professor_name') {
                    evaluatee = value.trim();
                } else if (key === 'share_your_thoughts') {
                    thoughtsText = thoughtsText
                        ? thoughtsText + '\n\n' + value.trim()
                        : value.trim();
                }
            }
        }

        const courseEl = document.getElementById('sel-course');
        const yearLevelEl = document.getElementById('sel-year');
        const course = courseEl ? courseEl.value : '';
        const yearLevel = yearLevelEl ? yearLevelEl.value : '';

                if (!course) {
            showToast('Please select your course/program.', 'warning');
            return;
        }
        // Year level is completely optional — no validation for it.

        const emptyTextarea = Array.from(form.querySelectorAll('textarea[required]'))
            .find(function(el) { return el.value.trim().length === 0; });
        if (emptyTextarea) {
            showToast('Please answer all questions before submitting.', 'warning');
            emptyTextarea.focus();
            return;
        }

        // Enforce every Likert question is answered. Each rating-group
        // holds one radio set; a group is "answered" if any radio in it
        // is checked. Count groups and find the first unanswered one so
        // we can focus it for the user.
        const ratingGroups = form.querySelectorAll('.rating-group');
        var unanswered = null;
        for (var i = 0; i < ratingGroups.length; i++) {
            if (!ratingGroups[i].querySelector('input[type="radio"]:checked')) {
                unanswered = ratingGroups[i];
                break;
            }
        }
        if (ratingGroups.length > 0 && unanswered) {
            showToast('Please answer every rating question before submitting (' +
                (Array.prototype.indexOf.call(ratingGroups, unanswered) + 1) +
                ' of ' + ratingGroups.length + ' still unanswered).', 'warning');
            unanswered.scrollIntoView({ behavior: 'smooth', block: 'center' });
            var firstRadio = unanswered.querySelector('input[type="radio"]');
            if (firstRadio) firstRadio.focus();
            return;
        }

        if (course) {
            this.currentCourse = course;
            sessionStorage.setItem('asiatech_student_course', course);
        }
        if (yearLevel) {
            this.currentYearLevel = yearLevel;
            sessionStorage.setItem('asiatech_student_year_level', yearLevel);
        }

        // NOTE: no client-side `comment` construction anymore.
        // Do not compute avgRating-into-comment here — the backend's
        // _build_text_for_sentiment() is the single source of truth
        // for joining strengths/improvements/ratings into sentiment text.
        const payload = {
            category: categoryName,
            comment: null,
            evaluatee: evaluatee || null,
            share_your_thoughts: thoughtsText || null,
            ratings: Object.keys(ratings).length > 0 ? ratings : null,
            student_id: null,
            course: course || null,
        };

        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) submitBtn.disabled = true;

        showLoading('Submitting your evaluation...');

        try {
            let result;
            const token = API.getToken();
            if (token) {
                result = await API.submitEvaluation(payload);
            } else {
                const response = await fetch(`${getApiBase()}/evaluation`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Submission failed');
                }
                result = await response.json();
            }

            if (typeof APP !== 'undefined' && APP.openModal) {
                APP.openModal(
                    '<div style="text-align:center;padding:1rem;">' +
                        '<i class="fas fa-check-circle" style="font-size:2.5rem;color:var(--pos);"></i>' +
                        '<h3 style="margin-top:.75rem;">Evaluation Submitted Successfully!</h3>' +
                        '<p>Thank you for your feedback. Your evaluation has been recorded.</p>' +
                        '<button class="btn btn-primary mt-2" onclick="APP.closeModal()"><i class="fas fa-plus"></i> Submit Another Evaluation</button>' +
                    '</div>'
                );
            }
            form.reset();
        } catch (error) {
            showToast(`Failed to submit: ${error.message}`, 'error');
            if (submitBtn) submitBtn.disabled = false;
        } finally {
            hideLoading();
        }
    }
};

if (typeof window !== 'undefined') {
    window.STUDENT = STUDENT;
}