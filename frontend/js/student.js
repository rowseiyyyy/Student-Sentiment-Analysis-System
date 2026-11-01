/**
 * Asiatech Sentiment Analysis - Student Module
 * Individual category evaluations
 */

const STUDENT = {
    currentCourse: null,
    currentYearLevel: null,
    currentCategoryIndex: 0,
    categories: ["professor", "facilities", "staff", "payments"],
    categoryNames: {"professor": "Professors", "staff": "Staff", "facilities": "Facilities", "payments": "Payments"},
    categoryLabels: {"professor": "Professor", "staff": "Staff", "facilities": "Facilities", "payments": "Payments"},
    categoryIcons: {"professor": "fa-chalkboard-teacher", "staff": "fa-users", "facilities": "fa-building", "payments": "fa-credit-card"},
    evaluations: {},
    _justSubmitted: false,

    init() {},

    handleLogin(e) {
        e.preventDefault();
        showToast("Welcome! Please fill out the evaluation form.", "success");
        this.startEvaluation();
    },

    logout() {
        // Persist the visible category before leaving, unless the form was just
        // submitted successfully (so submitted answers aren't restored next time).
        if (!this._justSubmitted) this.persistCurrentCategory();
        sessionStorage.removeItem("asiatech_student_course");
        sessionStorage.removeItem("asiatech_student_year_level");
        this.currentCourse = null;
        this.currentYearLevel = null;
        this.currentCategoryIndex = 0;
        this.evaluations = {};
        APP.goToPage("page-login");
        document.getElementById("nav-student").style.display = "none";
    },

    startEvaluation() {
        this.currentCategoryIndex = 0;
        this.evaluations = {};
        this._justSubmitted = false;
        APP.goToPage("page-student-eval");
        document.getElementById("nav-student").style.display = "flex";
        document.getElementById("badge-student").textContent = "Anonymous";
        document.getElementById("student-id-disp").textContent = "";

        const formArea = document.getElementById("student-form-area");
        if (formArea) formArea.classList.remove("hidden-block");

        if (this.currentCourse) {
            document.getElementById("sel-course").value = this.currentCourse;
        }
        if (this.currentYearLevel) {
            document.getElementById("sel-year").value = this.currentYearLevel;
        }

        this.renderCategorySelection();
    },

    renderCategorySelection() {
        const selection = document.getElementById("eval-selection");
        const formContent = document.getElementById("eval-form-content");
        if (!selection || !formContent) return;

        selection.classList.remove("hidden");
        formContent.innerHTML = "";
        formContent.classList.add("hidden");
        selection.innerHTML =
            "<section class=\"eval-selection-card\" aria-labelledby=\"eval-selection-title\">" +
            "<h2 id=\"eval-selection-title\">Choose an evaluation</h2>" +
            "<p>Select one category to complete. You can submit each evaluation separately.</p>" +
            "<div class=\"eval-category-grid\">" +
            this.categories.map(cat =>
                "<button type=\"button\" class=\"eval-category-button\" onclick=\"STUDENT.openCategory('" + cat + "')\">" +
                "<i class=\"fas " + this.categoryIcons[cat] + "\" aria-hidden=\"true\"></i>" +
                "<span>Evaluate " + this.categoryLabels[cat] + "</span>" +
                "<i class=\"fas fa-arrow-right eval-category-arrow\" aria-hidden=\"true\"></i>" +
                "</button>"
            ).join("") +
            "</div></section>";
    },

    openCategory(category) {
        const idx = this.categories.indexOf(category);
        if (idx === -1) return;
        this.currentCategoryIndex = idx;
        this.renderCategoryForm();
    },

    renderCategoryForm() {
        const container = document.getElementById("eval-form-content");
        const selection = document.getElementById("eval-selection");
        const category = this.categories[this.currentCategoryIndex];
        if (!container || !category) return;

        let formContent = "";
        switch (category) {
            case "professor": formContent = this.professorFormContent(); break;
            case "staff": formContent = this.staffFormContent(); break;
            case "facilities": formContent = this.facilitiesFormContent(); break;
            case "payments": formContent = this.paymentsFormContent(); break;
        }

        if (selection) selection.classList.add("hidden");
        container.classList.remove("hidden");
        container.innerHTML =
            "<div class=\"eval-form-card\">" +
            "<button type=\"button\" class=\"btn btn-secondary eval-back-button\" onclick=\"STUDENT.backToCategories()\"><i class=\"fas fa-arrow-left\"></i> All evaluations</button>" +
            "<h2><i class=\"fas " + this.categoryIcons[category] + "\"></i> Evaluate " + this.categoryLabels[category] + "</h2>" +
            "<form id=\"category-form\">" +
            formContent +
            "<div class=\"category-form-actions\">" +
            "<div class=\"nav-left\"></div>" +
            "<div class=\"nav-right\"><button type=\"button\" class=\"btn btn-success\" onclick=\"STUDENT.submitEvaluation('" + category + "')\">Submit " + this.categoryLabels[category] + " Evaluation</button></div>" +
            "</div></form></div>";

        this.restoreCategoryData();
    },

    backToCategories() {
        this.saveCategoryData();
        this._justSubmitted = false;
        this.renderCategorySelection();
    },

    saveCategoryData() {
        const cat = this.categories[this.currentCategoryIndex];
        const form = document.getElementById("category-form");
        if (!form) return;

        const ratings = {};
        // Read each question's key directly from the radio input's own `name`
        // attribute (the canonical source) rather than a parallel attribute on
        // the wrapper. This guarantees every answered rating is stored under the
        // correct question key so restoreCategoryData() can bring it back when
        // the student returns to this category to edit before submitting.
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

    restoreCategoryData() {
        const cat = this.categories[this.currentCategoryIndex];
        // Load this category's anonymous draft from localStorage if we have no
        // in-memory copy yet (e.g. page refresh, returning to the form).
        if (!this.evaluations[cat]) this.loadDraft(cat);
        const data = this.evaluations[cat];
        if (!data) return;

        const form = document.getElementById("category-form");
        if (!form) return;

        if (data.ratings) {
            Object.entries(data.ratings).forEach(([name, val]) => {
                // Attribute values in querySelector must be quoted or CSS
                // identifiers — a bare number like [value=5] throws
                // SyntaxError, so every value is quoted here.
                const rb = form.querySelector(
                    'input[type="radio"][name="' + name + '"][value="' + val + '"]'
                );
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

    // Save the visible category's answers before the page/browser leaves.
    persistCurrentCategory() {
        const page = document.getElementById("page-student-eval");
        const active = page ? page.classList.contains("active") : false;
        if (!active) return;
        if (this._justSubmitted) return;
        const form = document.getElementById("category-form");
        if (!form) return;
        this.saveCategoryData();
    },

    beginDraftAutosave() {
        window.addEventListener("beforeunload", () => this.persistCurrentCategory());
        window.addEventListener("pagehide", () => this.persistCurrentCategory());
        window.addEventListener("visibilitychange", () => {
            if (document.visibilityState === "hidden") this.persistCurrentCategory();
        });
    },
    validateCurrentCategory() {
        const form = document.getElementById("category-form");
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
            showToast("Please answer every rating question before submitting.", "warning");
            unanswered.scrollIntoView({ behavior: "smooth", block: "center" });
            var firstRadio = unanswered.querySelector("input[type=radio]");
            if (firstRadio) firstRadio.focus();
            return false;
        }
        const thoughtsArea = form.querySelector("textarea[name=share_your_thoughts]");
        if (thoughtsArea && !thoughtsArea.value.trim()) {
            showToast("Please share your thoughts before submitting.", "warning");
            thoughtsArea.scrollIntoView({ behavior: "smooth", block: "center" });
            thoughtsArea.focus();
            return false;
        }
        return true;
    },
    async submitEvaluation(category) {
        const categoryIndex = this.categories.indexOf(category);
        if (categoryIndex === -1 || categoryIndex !== this.currentCategoryIndex) return;
        if (!this.validateCurrentCategory()) return;

        this.saveCategoryData();
        const data = this.evaluations[category];

        const course = document.getElementById("sel-course")?.value;
        const yearLevel = document.getElementById("sel-year")?.value;
        if (!course) {
            showToast("Please select your course / program before submitting.", "warning");
            return;
        }
        if (!yearLevel) {
            showToast("Please select your year level before submitting.", "warning");
            return;
        }

        const btn = document.querySelector("#category-form button.btn-success");
        if (btn) btn.disabled = true;

        showLoading("Submitting " + this.categoryLabels[category] + " evaluation...");

        try {
            const payload = {
                category: this.categoryNames[category] || category,
                comment: null,
                share_your_thoughts: data.share_your_thoughts || null,
                ratings: data.ratings || null,
                student_id: null,
                course: course,
                year_level: yearLevel,
            };

            const response = await fetch(getApiBase() + "/evaluation", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const err = await response.json();
                const detail = err.detail;
                const message = typeof detail === "string"
                    ? detail
                    : Array.isArray(detail)
                        ? detail.map(d => d.msg || JSON.stringify(d)).join("; ")
                        : (detail ? JSON.stringify(detail) : "Submission failed");
                throw new Error(message);
            }

            this.clearDraft(category);
            this._justSubmitted = true;
            this.currentCourse = course;
            sessionStorage.setItem("asiatech_student_course", course);
            this.currentYearLevel = yearLevel;
            sessionStorage.setItem("asiatech_student_year_level", yearLevel);

            APP.openModal(
                "<div style=\"text-align:center;padding:1rem;\">" +
                "<i class=\"fas fa-check-circle\" style=\"font-size:3rem;color:var(--pos);\"></i>" +
                "<h3 style=\"margin-top:.75rem;\">" + this.categoryLabels[category] + " Evaluation Submitted!</h3>" +
                "<p>Thank you for your feedback! This evaluation has been recorded.</p>" +
                "<button class=\"btn btn-primary mt-2\" onclick=\"STUDENT.finishEvaluation()\"><i class=\"fas fa-list\"></i> Choose Another Evaluation</button>" +
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
        this._justSubmitted = false;
        this.renderCategorySelection();
    },
    professorFormContent() {
        return `<div class="form-section" style="margin-top:1.5rem;">
            <h4 style="margin-bottom:0.75rem;">Rate the following aspects:</h4>
            ${likertScale("teaching_quality", "The professors deliver lessons with good teaching quality")}
            ${likertScale("mastery", "The professors demonstrate mastery of the subject matter.")}
            ${likertScale("clarity", "The professors communicate and explain lessons clearly.")}
            ${likertScale("fairness", "The professors grade and evaluate students fairly.")}
            ${likertScale("punctuality", "Rate the professors punctuality and attendance")}
            ${likertScale("approachability", "Rate the professors approachability and willingness to help students")}
            ${likertScale("feedback", "The professors provide timely and constructive feedback on students performance.")}
            ${likertScale("classroom_mgmt", "Rate the professors classroom management")}
            ${likertScale("teaching_style", "The professors teaching style are effective this semester.")}
        </div>
        ${textareaField("share_your_thoughts", "Share Your Thoughts", "")}`;
    },

    staffFormContent() {
        return `<div class="form-section" style="margin-top:1.5rem;">
            <h4 style="margin-bottom:0.75rem;">Rate the following aspects:</h4>
            ${likertScale("safety", "The guards make me feel safe and greet me warmly whenever I enter the campus.")}
            ${likertScale("registrar", "The registrar's office staff are patient and helpful when answering questions about anything that concerns documents, records and enrollment")}
            ${likertScale("cashier", "Transactions at the cashier or accounting window are stress-free and handled with great professionalism.")}
            ${likertScale("canteen", "The canteen staff serve us warmly and keep the food service area clean and organized.")}
            ${likertScale("substitute", "Substitutes and temporary staff are well-prepared and keep our regular routines going smoothly.")}
            ${likertScale("office_staff", "The office staff quickly replies whenever I ask for help or need paperwork done")}
            ${likertScale("admin_comm", "The school administration keeps us well updated on everything through social media about campus announcement and events.")}
            ${likertScale("maintenance", "The maintenance and hallway staff do a wonderful job keeping our school surroundings safe and clean.")}
        </div>
        ${textareaField("share_your_thoughts", "Share Your Thoughts", "")}`;
    },
    facilitiesFormContent() {
        return `<div class="form-section" style="margin-top:1.5rem;">
            <h4 style="margin-bottom:0.75rem;">Rate the following aspects:</h4>
            ${likertScale("spaces", "The school has great spaces like hanging spots, benches, and trees.")}
            ${likertScale("furniture", "The classroom tables and chairs are all in good condition.")}
            ${likertScale("cleanliness", "General cleanliness in all facilities are observed.")}
            ${likertScale("bathrooms", "The bathrooms are always clean and smell fresh.")}
            ${likertScale("cafeteria", "The cafeteria or canteen has a clean dining space with plenty of room to sit and eat.")}
            ${likertScale("monitors", "The monitor systems in the classrooms are all well-working.")}
            ${likertScale("computers", "The lab computers are all easy to use and are well-managed.")}
            ${likertScale("classrooms", "The classrooms are always bright, clean and well-maintained and makes me comfortable to work properly.")}
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
            ${likertScale("security", "I feel confident that my personal and financial information is secure when making transactions.")}
            ${likertScale("info_clarity", "The payments process provides clear and accurate information about my fees, balances, and transactions.")}
            ${likertScale("digital_trust", "I trust that my personal and financial information is protected when using the digital bank information system for transactions.")}
        </div>
        ${textareaField("share_your_thoughts", "Share Your Thoughts", "")}`;
    },
    showEvalForm() {
        this.startEvaluation();
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
};

if (typeof window !== "undefined") {
    window.STUDENT = STUDENT;
    // Wire automatic draft saving so answers survive refresh, browser-Back,
    // tab-close, or navigating away — thened restored when the student returns.
    STUDENT.beginDraftAutosave();
}
