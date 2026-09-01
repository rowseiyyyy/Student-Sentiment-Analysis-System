/**
 * Asiatech Sentiment Analysis - Student Module
 * Multi-step evaluation with Next/Back navigation
 */

const STUDENT = {
    currentCourse: null,
    currentYearLevel: null,
    currentStep: 0,
    categories: ["professor", "staff", "facilities", "payments"],
    categoryNames: {"professor": "Professors", "staff": "Staff", "facilities": "Facilities", "payments": "Payments"},
    evaluations: {},
    _justSubmitted: false,

    init() {},

    handleLogin(e) {
        e.preventDefault();
        showToast("Welcome! Please fill out the evaluation form.", "success");
        this.startEvaluation();
    },

    logout() {
        // Persist the visible step before leaving, unless the form was just
        // submitted successfully (so submitted answers aren't restored next time).
        if (!this._justSubmitted) this.persistCurrentStep();
        sessionStorage.removeItem("asiatech_student_course");
        sessionStorage.removeItem("asiatech_student_year_level");
        this.currentCourse = null;
        this.currentYearLevel = null;
        this.currentStep = 0;
        this.evaluations = {};
        APP.goToPage("page-login");
        document.getElementById("nav-student").style.display = "none";
    },

    startEvaluation() {
        this.currentStep = 0;
        this.evaluations = {};
        this._justSubmitted = false;
        APP.goToPage("page-student-eval");
        document.getElementById("nav-student").style.display = "flex";
        document.getElementById("badge-student").textContent = "\u{1F393} Anonymous";
        document.getElementById("student-id-disp").textContent = "";

        const formArea = document.getElementById("student-form-area");
        if (formArea) formArea.classList.remove("hidden-block");

        if (this.currentCourse) {
            document.getElementById("sel-course").value = this.currentCourse;
        }
        if (this.currentYearLevel) {
            document.getElementById("sel-year").value = this.currentYearLevel;
        }

        this.hideTabs();
        this.renderCurrentStep();
    },

    hideTabs() {
        const tabs = document.getElementById("eval-tabs");
        if (tabs) tabs.classList.add("hidden");
    },
    renderCurrentStep() {
        const container = document.getElementById("eval-form-content");
        const category = this.categories[this.currentStep];
        const isLastStep = this.currentStep === this.categories.length - 1;
        const isFirstStep = this.currentStep === 0;

        let formContent = "";
        switch (category) {
            case "professor": formContent = this.professorFormContent(); break;
            case "staff": formContent = this.staffFormContent(); break;
            case "facilities": formContent = this.facilitiesFormContent(); break;
            case "payments": formContent = this.paymentsFormContent(); break;
        }

        const nextBtnText = isLastStep ? "Submit All" : "Next";
        const nextBtnClass = isLastStep ? "btn btn-success" : "btn btn-primary";
        const nextHandler = isLastStep ? "STUDENT.submitAllEvaluations()" : "STUDENT.nextStep()";

        const stepperHtml = this.categories.map((cat, i) => {
            const active = i === this.currentStep;
            const done = i < this.currentStep;
            const cls = active ? "step-item active" : (done ? "step-item completed" : "step-item");
            const ico = done ? "<i class=\"fas fa-check\"></i>" : "<span>" + (i + 1) + "</span>";
            return "<div class=\"" + cls + "\"><div class=\"step-circle\">" + ico + "</div><div class=\"step-label\">" + this.categoryNames[cat] + "</div></div>";
        }).join("");

        container.innerHTML =
            "<div class=\"stepper-container\"><div class=\"stepper\">" + stepperHtml + "</div></div>" +
            "<div class=\"eval-form-card\">" +
            "<h2><i class=\"fas fa-clipboard-list\"></i> " + this.categoryNames[category] + "</h2>" +
            "<form id=\"step-form\">" +
            formContent +
            "<div class=\"step-navigation\">" +
            "<div class=\"nav-left\">" + (!isFirstStep ? "<button type=\"button\" class=\"btn btn-secondary\" onclick=\"STUDENT.previousStep()\">Back</button>" : "") + "</div>" +
            "<div class=\"nav-right\"><button type=\"button\" class=\"" + nextBtnClass + "\" onclick=\"" + nextHandler + "\">" + nextBtnText + "</button></div>" +
            "</div></form></div>";

        this.restoreStepData();
    },

    saveStepData() {
        const cat = this.categories[this.currentStep];
        const form = document.getElementById("step-form");
        if (!form) return;

        const ratings = {};
        // Read each question's key directly from the radio input's own `name`
        // attribute (the canonical source) rather than a parallel attribute on
        // the wrapper. This guarantees every answered rating is stored under the
        // correct question key so restoreStepData() can bring it back when the
        // student navigates Back to re-edit before submitting.
        form.querySelectorAll("input[type=radio]:checked").forEach(c => {
            ratings[c.name] = parseInt(c.value);
        });

        const txt = form.querySelector("textarea[name=share_your_thoughts]");
        this.evaluations[cat] = {
            ratings: Object.keys(ratings).length ? ratings : null,
            share_your_thoughts: txt ? txt.value : null
        };
        this.saveDraft(cat);
    },

    restoreStepData() {
        const cat = this.categories[this.currentStep];
        // Load this category's anonymous draft from localStorage if we have no
        // in-memory copy yet (e.g. page refresh, returning to the form).
        if (!this.evaluations[cat]) this.loadDraft(cat);
        const data = this.evaluations[cat];
        if (!data) return;

        const form = document.getElementById("step-form");
        if (!form) return;

        if (data.ratings) {
            Object.entries(data.ratings).forEach(([name, val]) => {
                const rb = form.querySelector("input[type=radio][name=" + name + "][value=" + val + "]");
                if (rb) rb.checked = true;
            });
        }
        if (data.share_your_thoughts) {
            const ta = form.querySelector("textarea[name=share_your_thoughts]");
            if (ta) ta.value = data.share_your_thoughts;
        }
    },

// ============================================================
    // Anonymous local draft persistence (browser-localStorage only)
    // ============================================================

    // Map an evaluation category to its anonymous localStorage key. No
    // student identity (ID, user ID, email, name, etc.) is used.
    _draftKey(cat) {
        const keyMap = {
            professor: "evaluation_draft_faculty",
            staff: "evaluation_draft_staff",
            facilities: "evaluation_draft_facilities",
            payments: "evaluation_draft_payment",
        };
        return keyMap[cat] || ("evaluation_draft_" + cat);
    },

    // Persist one category's draft to localStorage (best-effort).
    saveDraft(cat) {
        try {
            localStorage.setItem(this._draftKey(cat), JSON.stringify(this.evaluations[cat]));
        } catch (e) { /* storage unavailable/full → best-effort, never crash */ }
    },

    // Load one category's anonymous draft from localStorage into memory.
    loadDraft(cat) {
        try {
            const raw = localStorage.getItem(this._draftKey(cat));
            if (raw) {
                const data = JSON.parse(raw);
                if (data && typeof data === "object") {
                    this.evaluations[cat] = data;
                    return true;
                }
            }
        } catch (e) { /* corrupted JSON → ignore */ }
        return false;
    },

    // Remove ONE category's draft (called only after that category's submission
    // succeeds, or by a future Clear/Reset control）。
    clearDraft(cat) {
        try {
            localStorage.removeItem(this._draftKey(cat));
        } catch (e) { /* best-effort */ }
        if (this.evaluations) delete this.evaluations[cat];
    },

    // Save the currently-visible step's answers right before the page/browser
    // leaves (refresh, browser-Back, closing tab, navigating away).
    persistCurrentStep() {
        const page = document.getElementById("page-student-eval");
        const active = page ? page.classList.contains("active") : false;
        if (!active) return;
        if (this._justSubmitted) return;
        const form = document.getElementById("step-form");
        if (!form) return;
        this.saveStepData();
    },

    beginDraftAutosave() {
        window.addEventListener("beforeunload", () => this.persistCurrentStep());
        window.addEventListener("pagehide", () => this.persistCurrentStep());
        window.addEventListener("visibilitychange", () => {
            if (document.visibilityState === "hidden") this.persistCurrentStep();
        });
    },
    nextStep() {
        if (!this.validateCurrentStep()) return;
        this.saveStepData();
        this.currentStep++;
        this.renderCurrentStep();
    },

    previousStep() {
        this.saveStepData();
        this.currentStep--;
        this.renderCurrentStep();
    },

    validateCurrentStep() {
        const form = document.getElementById("step-form");
        if (!form) return true;
        const ratingGroups = form.querySelectorAll(".rating-group");
        let unanswered = null;
        for (let i = 0; i < ratingGroups.length; i++) {
            if (!ratingGroups[i].querySelector("input[type=radio]:checked")) {
                unanswered = ratingGroups[i];
                break;
            }
        }
        if (ratingGroups.length > 0 && unanswered) {
            showToast("Please answer every rating question before proceeding.", "warning");
            unanswered.scrollIntoView({ behavior: "smooth", block: "center" });
            var firstRadio = unanswered.querySelector("input[type=radio]");
            if (firstRadio) firstRadio.focus();
            return false;
        }
        const thoughtsArea = form.querySelector("textarea[name=share_your_thoughts]");
        if (thoughtsArea && !thoughtsArea.value.trim()) {
            showToast("Please share your thoughts before proceeding.", "warning");
            thoughtsArea.scrollIntoView({ behavior: "smooth", block: "center" });
            thoughtsArea.focus();
            return false;
        }
        return true;
    },
    async submitAllEvaluations() {
        if (!this.validateCurrentStep()) return;

        // Capture the currently visible step's answers FIRST. saveStepData()
        // used to run only after validateAllCategories(), which meant the step
        // the student was looking at (e.g. Payments on the last step) was not
        // yet in this.evaluations → "Payments: No evaluation data" even though
        // every question had been answered.
        this.saveStepData();

        // Validate ALL categories before submitting
        const validation = this.validateAllCategories();
        if (!validation.isComplete) {
            const btn = document.querySelector("#step-form button.btn-success");
            if (btn) btn.disabled = false;
            showToast("Please complete all questions in: " + validation.incompleteCategories.join(", "), "error");

            // Show detailed message
            const detailedMsg = validation.unansweredDetails.slice(0, 3).join("; ");
            if (validation.unansweredDetails.length > 3) {
                showToast("Details: " + detailedMsg + "...", "warning");
            } else {
                showToast("Details: " + detailedMsg, "warning");
            }

            // Navigate to first incomplete category
            this.navigateToFirstIncomplete();
            return;
        }

        const course = document.getElementById("sel-course")?.value;
        const yearLevel = document.getElementById("sel-year")?.value;
        if (!course) return;

        this.saveStepData();

        const btn = document.querySelector("#step-form button.btn-success");
        if (btn) btn.disabled = true;

        showLoading("Submitting all evaluations...");

        try {
            for (const [cat, data] of Object.entries(this.evaluations)) {
                const payload = {
                    category: this.categoryNames[cat] || cat,
                    comment: null,
                    evaluatee: null,
                    share_your_thoughts: data.share_your_thoughts || null,
                    ratings: data.ratings || null,
                    student_id: null,
                    course: course,
                };

                const response = await fetch(getApiBase() + "/evaluation", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });

                if (!response.ok) {
                    const err = await response.json();
                    // FastAPI 422s return `detail` as an array of validation
                    // errors; join them so the toast isn't "[object Object]".
                    const detail = err.detail;
                    const message = typeof detail === "string"
                        ? detail
                        : Array.isArray(detail)
                            ? detail.map(d => d.msg || JSON.stringify(d)).join("; ")
                            : (detail ? JSON.stringify(detail) : "Submission failed");
                    throw new Error(message);
                }
                // This category was submitted successfully → clear ONLY its draft.
                // Other categories' drafts stay intact until they are each submitted.

                // On failure the throw above leaves every draft untouched so the
                // student can retry without losing their answers。
                this.clearDraft(cat);
            }

            this._justSubmitted = true;
            this.currentCourse = course;
            sessionStorage.setItem("asiatech_student_course", course);
            if (yearLevel) {
                this.currentYearLevel = yearLevel;
                sessionStorage.setItem("asiatech_student_year_level", yearLevel);
            }

            APP.openModal(
                "<div style=\"text-align:center;padding:1rem;\">" +
                "<i class=\"fas fa-check-circle\" style=\"font-size:3rem;color:var(--pos);\"></i>" +
                "<h3 style=\"margin-top:.75rem;\">All Evaluations Submitted Successfully!</h3>" +
                "<p>Thank you for your feedback! Your evaluations have been recorded.</p>" +
                "<button class=\"btn btn-primary mt-2\" onclick=\"STUDENT.finishEvaluation()\"><i class=\"fas fa-home\"></i> Return to Home</button>" +
                "</div>"
            );
        } catch (error) {
            showToast("Failed to submit: " + error.message, "error");
            if (btn) btn.disabled = false;
        } finally {
            hideLoading();
        }
    },

    finishEvaluation() {
        APP.closeModal();
        this.logout();
    },
    professorFormContent() {
        return `<div class="form-section" style="margin-top:1.5rem;">
            <h4 style="margin-bottom:0.75rem;">Rate the following aspects:</h4>
            ${likertScale("teaching_quality", "The professor delivers lessons with good teaching quality.")}
            ${likertScale("mastery", "The professors demonstrates mastery of the subject matter.")}
            ${likertScale("clarity", "The professors communicates and explains lessons clearly.")}
            ${likertScale("fairness", "The professors grades and evaluates students fairly.")}
            ${likertScale("punctuality", "The professors are punctual and has regular attendance.")}
            ${likertScale("approachability", "The professors are approachable and willing to help students.")}
            ${likertScale("feedback", "The professors provides timely and constructive feedback on students' performance.")}
            ${likertScale("classroom_mgmt", "The professors manages the classroom effectively.")}
            ${likertScale("teaching_style", "The professors teaching style is effective this semester.")}
        </div>
        ${textareaField("share_your_thoughts", "Share Your Thoughts", "")}`;
    },

    staffFormContent() {
        return `<div class="form-section" style="margin-top:1.5rem;">
            <h4 style="margin-bottom:0.75rem;">Rate the following aspects:</h4>
            ${likertScale("safety", "The guards make me feel safe and greet me warmly whenever I enter the campus.")}
            ${likertScale("registrar", "The registrar's office staff are patient and helpful when answering questions about documents, records, and enrollment.")}
            ${likertScale("cashier", "Transactions at the cashier or accounting window are stress-free and handled with professionalism.")}
            ${likertScale("canteen", "The canteen staff serve us warmly and keep the food service area clean and organized.")}
            ${likertScale("substitute", "Substitutes and temporary staff are well-prepared and keep our regular routines going smoothly.")}
            ${likertScale("office_staff", "The office staff quickly reply whenever I ask for help or need paperwork done.")}
            ${likertScale("admin_comm", "The school administration keeps us well updated through social media about campus announcements and events.")}
            ${likertScale("maintenance", "The maintenance and hallway staff do a wonderful job keeping our school surroundings safe and clean.")}
        </div>
        ${textareaField("share_your_thoughts", "Share Your Thoughts", "")}`;
    },
    facilitiesFormContent() {
        return `<div class="form-section" style="margin-top:1.5rem;">
            <h4 style="margin-bottom:0.75rem;">Rate the following aspects:</h4>
            ${likertScale("spaces", "The school has great spaces like hanging spots, benches, and trees.")}
            ${likertScale("furniture", "The classroom tables and chairs are all in good condition.")}
            ${likertScale("cleanliness", "General cleanliness in all facilities is observed.")}
            ${likertScale("bathrooms", "The bathrooms are always clean and smell fresh.")}
            ${likertScale("cafeteria", "The cafeteria or canteen has a clean dining space with plenty of room to sit and eat.")}
            ${likertScale("monitors", "The monitor systems in the classrooms are all working properly.")}
            ${likertScale("computers", "The lab computers are all easy to use and are well-managed.")}
            ${likertScale("classrooms", "The classrooms are always bright, clean, and well-maintained, making me comfortable to work properly.")}
        </div>
        ${textareaField("share_your_thoughts", "Share Your Thoughts", "")}`;
    },

    paymentsFormContent() {
        return `<div class="form-section" style="margin-top:1.5rem;">
            <h4 style="margin-bottom:0.75rem;">Rate the following aspects:</h4>
            ${likertScale("accessibility", "The payment portal/counter is easily accessible at convenient times for my schedule.")}
            ${likertScale("processing", "My payments or fee clearances are processed and posted to my account in a timely manner.")}
            ${likertScale("queues", "The on-site payment queues move quickly and efficiently, even during peak days.")}
            ${likertScale("courteous", "Payment personnel are courteous, helpful, and prompt in addressing payment-related inquiries or concerns.")}
            ${likertScale("accounting", "Accounting and registrar personnel are helpful, polite, and responsive when addressing payment and document-related inquiries or issues.")}
        </div>
        ${textareaField("share_your_thoughts", "Share Your Thoughts", "")}`;
    },
    showEvalForm() {
        this.startEvaluation();
    },

    renderFormTab(tab) {
        // Persist the current step's answers (and any others just entered) so the
        // per-category drafts stay separated and up-to-date before switching categories.
        this.saveStepData();
        const idx = this.categories.indexOf(tab);
        if (idx !== -1) {
            this.currentStep = idx;
            this.renderCurrentStep();
        }
    },

    professorForm() {
        return this.professorFormContent();
    },

    staffForm() {
        return this.staffFormContent();
    },

    facilitiesForm() {
        return this.facilitiesFormContent();
    },

    paymentsForm() {
        return this.paymentsFormContent();
    },

    handleFormSubmit(e, category) {
        e.preventDefault();
        const idx = this.categories.indexOf(category);
        if (idx !== -1) {
            this.currentStep = idx;
        }
        this.startEvaluation();
    },

    // ========================================
    // Required Field Validation Helpers
    // ========================================
    
    // Define all required questions for each category
    requiredQuestions: {
        professor: ["teaching_quality", "mastery", "clarity", "fairness", "punctuality", "approachability", "feedback", "classroom_mgmt", "teaching_style"],
        staff: ["safety", "registrar", "cashier", "canteen", "substitute", "office_staff", "admin_comm", "maintenance"],
        facilities: ["spaces", "furniture", "cleanliness", "bathrooms", "cafeteria", "monitors", "computers", "classrooms"],
        payments: ["accessibility", "processing", "queues", "courteous", "accounting"]
    },

    // Get required questions for a category
    getRequiredQuestionsForCategory(category) {
        return this.requiredQuestions[category] || [];
    },

    // Get form content for a category (used for validation)
    getCategoryFormContent(category) {
        switch (category) {
            case "professor": return this.professorFormContent();
            case "staff": return this.staffFormContent();
            case "facilities": return this.facilitiesFormContent();
            case "payments": return this.paymentsFormContent();
            default: return "";
        }
    },

    // Highlight unanswered questions in the current step
    highlightUnansweredQuestions() {
        const form = document.getElementById("step-form");
        if (!form) return;
        
        // Remove any existing error highlights
        form.querySelectorAll(".rating-group.error, .form-group.error").forEach(el => {
            el.classList.remove("error");
        });
        
        const category = this.categories[this.currentStep];
        const data = this.evaluations[category];
        const requiredQuestions = this.getRequiredQuestionsForCategory(category);
        
        // Check each Likert question
        const ratingGroups = form.querySelectorAll(".rating-group");
        for (const group of ratingGroups) {
            const radio = group.querySelector("input[type=radio]");
            if (radio) {
                const name = radio.name;
                if (requiredQuestions.includes(name)) {
                    if (!data?.ratings?.[name]) {
                        group.classList.add("error");
                    }
                }
            }
        }
        
        // Check textarea
        const thoughtsArea = form.querySelector("textarea[name=share_your_thoughts]");
        if (thoughtsArea && requiredQuestions.length > 0) {
            if (!data?.share_your_thoughts?.trim()) {
                const parent = thoughtsArea.closest(".form-group");
                if (parent) parent.classList.add("error");
            }
        }
    },

    // Validate all categories before final submission
    validateAllCategories() {
        const incompleteCategories = [];
        const unansweredDetails = [];
        
        for (const cat of this.categories) {
            const data = this.evaluations[cat];
            const requiredQuestions = this.getRequiredQuestionsForCategory(cat);
            const categoryName = this.categoryNames[cat] || cat;
            
            if (!data) {
                incompleteCategories.push(categoryName);
                unansweredDetails.push(categoryName + ": No evaluation data");
                continue;
            }
            
            if (!data.ratings) {
                if (!incompleteCategories.includes(categoryName)) {
                    incompleteCategories.push(categoryName);
                }
                unansweredDetails.push(categoryName + ": Missing ratings");
                continue;
            }
            
            const unansweredQuestions = [];
            for (const question of requiredQuestions) {
                if (!data.ratings[question]) {
                    unansweredQuestions.push(question);
                }
            }
            
            if (unansweredQuestions.length > 0) {
                if (!incompleteCategories.includes(categoryName)) {
                    incompleteCategories.push(categoryName);
                }
                unansweredDetails.push(categoryName + ": " + unansweredQuestions.length + " unanswered rating(s)");
            }
            
            if (!data.share_your_thoughts || !data.share_your_thoughts.trim()) {
                if (!incompleteCategories.includes(categoryName)) {
                    incompleteCategories.push(categoryName);
                }
                unansweredDetails.push(categoryName + ': Missing "Share Your Thoughts"');
            }
        }
        
        return {
            isComplete: incompleteCategories.length === 0,
            incompleteCategories,
            unansweredDetails
        };
    },

    // Navigate to first incomplete category
    navigateToFirstIncomplete() {
        for (const cat of this.categories) {
            const data = this.evaluations[cat];
            const requiredQuestions = this.getRequiredQuestionsForCategory(cat);
            let hasUnanswered = false;
            
            if (!data?.ratings) {
                hasUnanswered = true;
            } else {
                for (const question of requiredQuestions) {
                    if (!data.ratings[question]) {
                        hasUnanswered = true;
                        break;
                    }
                }
            }
            
            if (!data?.share_your_thoughts?.trim()) {
                hasUnanswered = true;
            }
            
            if (hasUnanswered) {
                this.currentStep = this.categories.indexOf(cat);
                this.renderCurrentStep();
                this.highlightUnansweredQuestions();
                return true;
            }
        }
        return false;
    }
};

if (typeof window !== "undefined") {
    window.STUDENT = STUDENT;
    // Wire automatic draft saving so answers survive refresh, browser-Back,
    // tab-close, or navigating away — thened restored when the student returns.
    STUDENT.beginDraftAutosave();
}
