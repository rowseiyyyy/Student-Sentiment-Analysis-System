/**
 * Asiatech Sentiment Analysis - Student Module
 * Updated for "Asiatech Feedback Casefile" paper theme design.
 * Handles student login (by student number) and evaluation form submission.
 * All evaluation questions, fields, and submit logic preserved.
 */

const STUDENT = {
    currentStudentNumber: null,
    currentCourse: null,
    currentYearLevel: null,

    init() {
        const studentNum = sessionStorage.getItem('asiatech_student_number');
        if (studentNum) {
            this.currentStudentNumber = studentNum;
            this.currentCourse = sessionStorage.getItem('asiatech_student_course') || '';
            this.currentYearLevel = sessionStorage.getItem('asiatech_student_year_level') || '';
            this.showEvalForm();
        }
    },

    handleLogin(e) {
        e.preventDefault();
        const studentNumber = document.getElementById('inp-sn').value.trim();
        if (!studentNumber || studentNumber.length < 3) {
            showToast('Please enter a valid student number.', 'warning');
            return;
        }

        this.currentStudentNumber = studentNumber;
        sessionStorage.setItem('asiatech_student_number', this.currentStudentNumber);
        showToast(`Welcome, ${this.currentStudentNumber}! Please fill out the evaluation form.`, 'success');
        this.showEvalForm();
    },

    logout() {
        sessionStorage.removeItem('asiatech_student_number');
        sessionStorage.removeItem('asiatech_student_course');
        sessionStorage.removeItem('asiatech_student_year_level');
        this.currentStudentNumber = null;
        this.currentCourse = null;
        this.currentYearLevel = null;
        APP.goToPage('page-login');
        document.getElementById('nav-student').style.display = 'none';
    },

showEvalForm() {
        APP.goToPage('page-student-eval');
        document.getElementById('nav-student').style.display = 'flex';
        document.getElementById('badge-student').textContent = '\u{1F393} ' + this.currentStudentNumber;
        document.getElementById('student-id-disp').textContent = 'Student ID: ' + this.currentStudentNumber;

        // Show the form area, hide the submissions area
        const studentContent = document.getElementById('student-content');
        const formArea = document.getElementById('student-form-area');
        const submissionsArea = document.getElementById('student-submissions-area');
        if (formArea) formArea.style.display = '';
        if (submissionsArea) submissionsArea.style.display = 'none';

        // Restore saved course/year
        if (this.currentCourse) {
            document.getElementById('sel-course').value = this.currentCourse;
        }
        if (this.currentYearLevel) {
            document.getElementById('sel-year').value = this.currentYearLevel;
        }

        this.renderFormTab('professor');
    },

    async showSubmissions() {
        APP.goToPage('page-student-eval');
        document.getElementById('nav-student').style.display = 'flex';
        document.getElementById('badge-student').textContent = '\u{1F393} ' + this.currentStudentNumber;
        document.getElementById('student-id-disp').textContent = 'Student ID: ' + this.currentStudentNumber;

        const studentContent = document.getElementById('student-content');
        const formArea = document.getElementById('student-form-area');
        const submissionsArea = document.getElementById('student-submissions-area');
        if (formArea) formArea.style.display = 'none';

        if (!submissionsArea) {
            // Build the submissions area dynamically
            const div = document.createElement('div');
            div.id = 'student-submissions-area';
            studentContent.appendChild(div);
        }

        const container = document.getElementById('student-submissions-area');
        container.style.display = '';
        container.innerHTML = '<div class="page-header"><h1><i class="fas fa-history"></i> My Submissions</h1><span class="date-note">Your submitted evaluations</span></div><div class="text-center mt-4"><div class="spinner"></div><p>Loading your submissions...</p></div>';

        try {
            const data = await API.getEvaluations({ page_size: 100 });
            const items = Array.isArray(data.items) ? data.items : [];
            if (items.length === 0) {
                container.innerHTML = '<div class="page-header"><h1><i class="fas fa-history"></i> My Submissions</h1></div><div class="card"><div class="empty-state"><div class="empty-icon"><i class="fas fa-inbox"></i></div><h3>No Submissions Yet</h3><p>You haven\'t submitted any evaluations yet.</p></div></div>';
                return;
            }

            const rows = items.map(function(item, idx) {
                const category = item.category || 'N/A';
                const sentiment = item.sentiment || 'N/A';
                const sentBadge = sentimentBadge ? sentimentBadge(item.sentiment) : '<span class="badge badge-neutral">' + escapeHtml(sentiment) + '</span>';
                const commentShort = item.comment ? (item.comment.length > 100 ? item.comment.substring(0, 100) + '...' : item.comment) : '';
                return '<tr>' +
                    '<td style="font-family:var(--font-mono);font-size:.72rem;color:var(--ink-faint);">' + (idx + 1) + '</td>' +
                    '<td><span class="badge badge-' + (String(category).toLowerCase() === 'faculty' ? 'faculty' : String(category).toLowerCase() === 'staff' ? 'staff' : String(category).toLowerCase() === 'facilities' ? 'facilities' : 'payment') + '">' + escapeHtml(category) + '</span></td>' +
                    '<td style="max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + escapeHtml(item.comment || '') + '">' + escapeHtml(commentShort) + '</td>' +
                    '<td style="white-space:nowrap;">' + sentBadge + '</td>' +
                    '<td style="font-family:var(--font-mono);font-size:.8rem;white-space:nowrap;">' + formatDate(item.created_at) + '</td>' +
                    '<td style="white-space:nowrap;"><button class="btn btn-sm btn-primary" onclick="STUDENT.viewSubmission(\'' + item.id + '\')" title="View"><i class="fas fa-eye"></i></button></td>' +
                '</tr>';
            }).join('');

            container.innerHTML =
                '<div class="page-header"><h1><i class="fas fa-history"></i> My Submissions</h1><span class="date-note">' + items.length + ' total</span></div>' +
                '<div class="card"><div class="table-container"><table>' +
                    '<thead><tr><th>#</th><th>Category</th><th>Comment</th><th>Sentiment</th><th>Date</th><th>Actions</th></tr></thead>' +
                    '<tbody>' + rows + '</tbody></table></div></div>';
        } catch (error) {
            container.innerHTML = '<div class="page-header"><h1><i class="fas fa-history"></i> My Submissions</h1></div><div class="card"><div class="empty-state"><div class="empty-icon"><i class="fas fa-exclamation-triangle" style="color:var(--neu);"></i></div><h3>Error</h3><p>' + error.message + '</p></div></div>';
        }
    },

    async viewSubmission(id) {
        showLoading('Loading submission...');
        try {
            const item = await API.getEvaluation(id);
            hideLoading();
            const category = item.category || 'N/A';
            const sentiment = item.sentiment || 'N/A';
            const html =
                '<div class="modal-row"><div class="modal-field"><label>Category</label><p>' + escapeHtml(category) + '</p></div>' +
                '<div class="modal-field"><label>Sentiment</label><p>' + sentimentBadge(item.sentiment) + '</p></div></div>' +
                '<div class="modal-row"><div class="modal-field"><label>Date Submitted</label><p>' + formatDate(item.created_at) + '</p></div>' +
                '<div class="modal-field"><label>Evaluatee</label><p>' + escapeHtml(item.evaluatee || 'N/A') + '</p></div></div>' +
                '<div style="margin-top:1rem;"><h4 style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-faint);margin-bottom:.3rem;">Full Comment</h4><p style="white-space:pre-wrap;">' + escapeHtml(item.comment || 'N/A') + '</p></div>';
            if (item.strengths) {
                html = html + '<div style="margin-top:1rem;background:var(--pos-bg);padding:0.75rem;border:1px solid var(--paper-line);"><h4 style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.06em;text-transform:uppercase;color:var(--pos);margin-bottom:.3rem;">Strengths</h4><p style="font-size:.85rem;white-space:pre-wrap;">' + escapeHtml(item.strengths) + '</p></div>';
            }
            if (item.areas_for_improvement) {
                html = html + '<div style="margin-top:1rem;background:var(--neg-bg);padding:0.75rem;border:1px solid var(--paper-line);"><h4 style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.06em;text-transform:uppercase;color:var(--neg);margin-bottom:.3rem;">Improvements</h4><p style="font-size:.85rem;white-space:pre-wrap;">' + escapeHtml(item.areas_for_improvement) + '</p></div>';
            }
            APP.openModal(html);
        } catch (error) {
            hideLoading();
            showToast('Failed to load submission: ' + error.message, 'error');
        }
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
    // PROFESSOR FORM — All original questions/fields preserved
    // ============================================================
    professorForm() {
        return `
            <div class="eval-form-card">
                <h2><i class="fas fa-chalkboard-teacher"></i> Professor Evaluation Form</h2>
                <p class="form-desc">Please provide your honest feedback about your professor's teaching performance and professionalism.</p>
                <form class="eval-form" id="professor-form">
                    ${selectField('professor_name', 'Select the professor you are evaluating', [
                        'Prof. Abellano, Polyana R.',
                        'Prof. Aragon, Ana Rose',
                        'Prof. Atienza, Leo',
                        'Prof. Atienza, Rea',
                        'Prof. Avendano, Alexander',
                        'Prof. Bagunas, Norielene C.',
                        'Prof. Ballad, Joshua',
                        'Prof. Banga, Mary Jean',
                        'Prof. Baroro, Von Ryan',
                        'Prof. Barrete, Remegio Jr.',
                        'Prof. Barroso, Ailyn',
                        'Prof. Basuan, Keith Lenard',
                        'Prof. Batayon, John Carlo R.',
                        'Prof. Bayasbas, Rodel',
                        'Prof. Bejer, Marilyn',
                        'Prof. Bernardo, Myrtel',
                        'Prof. Binasoy, Juliet',
                        'Prof. Bonaobra, Carmela',
                        'Prof. Buhay, Elizabeth',
                        'Prof. Cabana, Mary Joy',
                        'Prof. Camaclang, Camille',
                        'Prof. Capacio, Mark Ryan',
                        'Prof. Cera, Pauline Grace',
                        'Prof. Cosep, Cyrill John',
                        'Prof. De Guzman, Marie Charlene',
                        'Prof. Deada, Lani',
                        'Prof. Deblois, Mary Strelitzia',
                        'Prof. Diano, Marivic',
                        'Prof. Endencio, Vicmar',
                        'Prof. Escuton, Darle Joy',
                        'Prof. Eusoya, Mhilpe',
                        'Prof. Farol, Jose III',
                        'Prof. Flores, Jomhae',
                        'Prof. Geraldez, Mademoiselle Irish',
                        'Prof. Golloso, Joy',
                        'Prof. Gomez, Romeo Jr.',
                        'Prof. Guardarama, Cesiel',
                        'Prof. Guarino, Ronnel',
                        'Prof. Gumapac, Samuel',
                        'Prof. Gutierrez, Malou',
                        'Prof. Indicio, John Lester',
                        'Prof. Indino, Creselito',
                        'Prof. Intia, John Francis R.',
                        'Prof. Iyoy, Nerie',
                        'Prof. Jasmin, Jose Mari',
                        'Prof. Jebunan, Bianca N.',
                        'Prof. Julianda, Bryan',
                        'Prof. Lafuente, Joel',
                        'Prof. Lalap, Rose Ann',
                        'Prof. Lascano, Clark Allen Y.',
                        'Prof. Libas, Sem O.',
                        'Prof. Lleve, Shelalin G.',
                        'Prof. Maghanoy, Charissa',
                        'Prof. Mallari, Abigail',
                        'Prof. Manarin, Crishel Aeye',
                        'Prof. Mapote, Harvie',
                        'Prof. Maquinad, Sheila',
                        'Prof. Mendoza, Joanne',
                        'Prof. Miranda, Christine',
                        'Prof. Natividad, Angel',
                        'Prof. Nava, Clara Mae',
                        'Prof. Ocampo, Rodelmar',
                        'Prof. Oliva, Catherine',
                        'Prof. Paciente, Aila Marie',
                        'Prof. Payos, John Paul',
                        'Prof. Plenago, Adrian',
                        'Prof. Ramos, Kaizzer Paul',
                        'Prof. Ramos, Marigrace',
                        'Prof. Reformo, Jasper Keith',
                        'Prof. Respende, John Ray',
                        'Prof. Roman, Rhizza',
                        'Prof. Sabao, Joemari',
                        'Prof. Salazar, Jefrey',
                        'Prof. Samson, Alliah',
                        'Prof. Seastres, Agustin',
                        'Prof. Sumbilon, Roy',
                        'Prof. Tolentino, Jonathan',
                        'Prof. Tuazon, Rozaida',
                        'Prof. Tuquilar, Eduardo',
                        'Prof. Veridiano, Johana',
                        'Prof. Veridiano, Johani',
                        'Prof. Veron, Jeff Fred',
                        'Prof. Victorio, Joaquin',
                        'Prof. Villarama, Bon Jovi',
                        'Prof. Zamora, Kerr'
                    ], 'Choose a professor')}
                    <div class="form-group">
                        <label for="subject"><i class="fas fa-book"></i> Subject/Course handled by this professor</label>
                        <input type="text" id="subject" name="subject" class="form-control" placeholder="Type the subject/course name..." required />
                    </div>
                    <div class="form-section" style="margin-top:1.5rem;">
                        <h4 style="margin-bottom:0.75rem;">Rate the following aspects (1 = Very Poor, 5 = Excellent):</h4>
                        ${likertScale('mastery', 'This professor demonstrates mastery of the subject matter.')}
                        ${likertScale('teaching_quality', 'This professor delivers lessons with good teaching quality.')}
                        ${likertScale('clarity', 'This professor communicates and explains lessons clearly.')}
                        ${likertScale('fairness', 'This professor grades and evaluates students fairly.')}
                        ${likertScale('punctuality', 'Rate this professor\'s punctuality and attendance.')}
                        ${likertScale('approachability', 'Rate this professor\'s approachability.')}
                        ${likertScale('classroom_mgmt', 'Rate this professor\'s classroom management.')}
                    </div>
                    ${textareaField('teaching_style', 'What can you say about this professor\'s teaching style this semester?', 'Share your thoughts...')}
                    ${textareaField('strengths', 'What are this professor\'s strengths?', 'List the professor\'s strengths...')}
                    ${textareaField('improvements', 'What can this professor improve on?', 'Suggest areas for improvement...')}
                    <button type="submit" class="btn btn-primary btn-block btn-lg mt-3">
                        <i class="fas fa-paper-plane"></i> Submit Professor Evaluation
                    </button>
                </form>
            </div>
        `;
    },

    // ============================================================
    // STAFF FORM — All original questions/fields preserved
    // ============================================================
    staffForm() {
        return `
            <div class="eval-form-card">
                <h2><i class="fas fa-users"></i> Staff Evaluation Form</h2>
                <p class="form-desc">Thank you for your feedback. Please answer the following questions based on your recent experience with our school staff.</p>
                <form class="eval-form" id="staff-form">
                    <div class="form-section">
                        <h4 style="margin-bottom:0.75rem;">Rate the following aspects (1 = Very Poor, 5 = Excellent):</h4>
                        ${likertScale('safety', 'The guards make me feel safe and greet me warmly.')}
                        ${likertScale('registrar', 'The registrar\'s office staff are patient and helpful.')}
                        ${likertScale('cashier', 'Transactions at the cashier are stress-free.')}
                        ${likertScale('canteen', 'The canteen staff serve us warmly.')}
                        ${likertScale('substitute', 'Substitutes and temporary staff are well-prepared.')}
                        ${likertScale('office_staff', 'Office staff quickly respond to requests.')}
                        ${likertScale('admin_comm', 'Administration keeps students well-informed.')}
                        ${likertScale('maintenance', 'Maintenance staff do an excellent job.')}
                    </div>
                    ${textareaField('positive_impact', 'What specific behavior of the staff made a positive impact?', 'Share your thoughts...')}
                    ${textareaField('staff_improvements', 'What can staff improve to provide better service?', 'Share your thoughts...')}
                    <button type="submit" class="btn btn-primary btn-block btn-lg mt-3">
                        <i class="fas fa-paper-plane"></i> Submit Staff Evaluation
                    </button>
                </form>
            </div>
        `;
    },

    // ============================================================
    // FACILITIES FORM — All original questions/fields preserved
    // ============================================================
    facilitiesForm() {
        return `
            <div class="eval-form-card">
                <h2><i class="fas fa-building"></i> Facilities Evaluation Form</h2>
                <p class="form-desc">Please evaluate the school's facilities based on your recent experience.</p>
                <form class="eval-form" id="facilities-form">
                    <div class="form-section">
                        <h4 style="margin-bottom:0.75rem;">Rate the following aspects (1 = Very Poor, 5 = Excellent):</h4>
                        ${likertScale('spaces', 'The school has great spaces such as benches, study areas, and shaded outdoor spaces.')}
                        ${likertScale('furniture', 'Classroom tables and chairs are in good condition.')}
                        ${likertScale('cleanliness', 'General cleanliness is consistently maintained throughout the school facilities.')}
                        ${likertScale('bathrooms', 'The bathrooms are clean and well-maintained.')}
                        ${likertScale('cafeteria', 'The cafeteria has a clean dining area with sufficient seating.')}
                        ${likertScale('monitors', 'Classroom monitor systems are functioning properly.')}
                        ${likertScale('computers', 'Laboratory computers are easy to use and properly maintained.')}
                        ${likertScale('classrooms', 'Classrooms are bright, clean, and comfortable for learning.')}
                    </div>
                    ${textareaField('positive_facilities', 'Describe the most positive thing you noticed about the school facilities.', 'Share your thoughts...')}
                    ${textareaField('facilities_improvements', 'What improvements or maintenance would you recommend for the school facilities?', 'Share your thoughts...')}
                    <button type="submit" class="btn btn-primary btn-block btn-lg mt-3">
                        <i class="fas fa-paper-plane"></i> Submit Facilities Evaluation
                    </button>
                </form>
            </div>
        `;
    },

    // ============================================================
    // PAYMENTS FORM — All original questions/fields preserved
    // ============================================================
    paymentsForm() {
        return `
            <div class="eval-form-card">
                <h2><i class="fas fa-credit-card"></i> Payments Evaluation Form</h2>
                <p class="form-desc">Please answer the following questions based on your recent experience with the payment and accounting services.</p>
                <form class="eval-form" id="payments-form">
                    <div class="form-section">
                        <h4 style="margin-bottom:0.75rem;">Rate the following aspects (1 = Very Poor, 5 = Excellent):</h4>
                        ${likertScale('accessibility', 'The payment portal or payment counter is easily accessible during convenient hours.')}
                        ${likertScale('processing', 'My payments and fee clearances are processed promptly.')}
                        ${likertScale('queues', 'Payment queues move efficiently, even during peak periods.')}
                        ${likertScale('online', 'Online payment services are reliable and convenient.')}
                        ${likertScale('courteous', 'Payment personnel are courteous, helpful, and responsive to payment-related concerns.')}
                        ${likertScale('accounting', 'Accounting and registrar personnel are polite, professional, and responsive when handling payment or document-related inquiries.')}
                        ${likertScale('security', 'I feel confident that my personal and financial information is secure during transactions.')}
                    </div>
                    ${textareaField('payment_challenges', 'What specific challenges or difficulties have you experienced when making payments or transacting with the accounting/payment office?', 'Share your thoughts...')}
                    ${textareaField('payment_recommendations', 'What recommendations would you suggest to make the payment process more efficient and user-friendly?', 'Share your thoughts...')}
                    <button type="submit" class="btn btn-primary btn-block btn-lg mt-3">
                        <i class="fas fa-paper-plane"></i> Submit Payment Evaluation
                    </button>
                </form>
            </div>
        `;
    },

    // ============================================================
    // FORM SUBMIT — All original logic preserved
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
        let strengthsText = '';
        let improvementsText = '';
        let evaluatee = '';

        for (const [key, value] of formData.entries()) {
            const num = parseInt(value, 10);
            if (!Number.isNaN(num) && num >= 1 && num <= 5) {
                ratings[key] = num;
           } else if (value && value.trim().length > 0) {
                if (key === 'professor_name') {
                    evaluatee = value.trim();
                } else if (key === 'strengths') {
                    strengthsText = strengthsText
                        ? strengthsText + '\n\n' + value.trim()
                        : value.trim();
                } else if (key === 'teaching_style') {
                    const teachingStyleText = 'Teaching style: ' + value.trim();
                    strengthsText = strengthsText
                        ? strengthsText + '\n\n' + teachingStyleText
                        : teachingStyleText;
                } else if (key === 'improvements' || key === 'staff_improvements' || key === 'facilities_improvements' || key === 'payment_recommendations') {
                    improvementsText = value.trim();
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
if (!yearLevel) {
    showToast('Please select your year level.', 'warning');
    return;
}
const emptyTextarea = Array.from(form.querySelectorAll('textarea[required]'))
            .find(function(el) { return el.value.trim().length === 0; });
        if (emptyTextarea) {
            showToast('Please answer all questions before submitting.', 'warning');
            emptyTextarea.focus();
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

        const allRatings = Object.values(ratings);
        const avgRating = allRatings.length > 0
            ? (allRatings.reduce((a, b) => a + b, 0) / allRatings.length).toFixed(1)
            : 'N/A';

        const commentParts = [];
        if (strengthsText) commentParts.push(`Strengths: ${strengthsText}`);
        if (improvementsText) commentParts.push(`Areas for improvement: ${improvementsText}`);
        if (avgRating !== 'N/A') commentParts.push(`Average rating: ${avgRating}/5`);
        const comment = commentParts.length > 0
            ? commentParts.join('. ')
            : `${categoryName} evaluation submitted`;

        const payload = {
            category: categoryName,
            comment,
            evaluatee: evaluatee || null,
            strengths: strengthsText || null,
            areas_for_improvement: improvementsText || null,
            ratings: Object.keys(ratings).length > 0 ? ratings : null,
            student_id: this.currentStudentNumber,
            course: course || null,
            year_level: yearLevel || null
        };

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

            showToast('Evaluation submitted successfully! Thank you for your feedback.', 'success');
            if (typeof APP !== 'undefined' && APP.openModal) {
                APP.openModal(
                    '<div style="text-align:center;padding:1rem;">' +
                        '<i class="fas fa-check-circle" style="font-size:2.5rem;color:var(--pos);"></i>' +
                        '<h3 style="margin-top:.75rem;">Evaluation Submitted Successfully!</h3>' +
                        '<p>Thank you for your feedback. Your evaluation has been recorded successfully.</p>' +
                    '</div>'
                );
            }
            form.reset();
        } catch (error) {
            showToast(`Failed to submit: ${error.message}`, 'error');
        } finally {
            hideLoading();
        }
    }
};

if (typeof window !== 'undefined') {
    window.STUDENT = STUDENT;
}
