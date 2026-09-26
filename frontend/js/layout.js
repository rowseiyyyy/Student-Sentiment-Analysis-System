/* ============================================================
   LAYOUT — shared, admin-editable widget geometry.

   One module owns the whole feature so the admin and faculty pages cannot
   drift apart. Responsibilities:

   1. Read the saved layout for a page and apply it to the rendered widgets.
   2. Expose resize affordances to administrators ONLY.
   3. Persist an administrator's changes, and let them be reset.

   Sizing model
   ------------
   Width is stored in *grid units* (how many columns of the page's current
   grid the widget spans), never in pixels. That is what makes a saved layout
   survive a change to the page container's max-width: "span 2" means two
   columns of whatever the grid is today, so widening the container re-flows
   the layout instead of leaving stranded fixed-width columns. Height is
   stored in pixels, snapped to a 10px step, and only ever applied to
   widgets with a fixed-height body (a chart canvas) -- forcing a height onto
   a text card just clips it.

   Responsiveness
   -------------
   A saved width is a preference, not a promise. On a narrow viewport the
   grid collapses to one column, so a `span 3` must become `span 1`, or a
   wide-screen save would overflow a phone. _effectiveW() does that clamp and
   the CSS media queries are the backstop.
*/
const LAYOUT = {
    // Bounds. The server enforces the same numbers; these are the tighter,
    // design-driven limits the UI offers.
    MIN_W: 1,
    MAX_W: 4,
    MIN_H: 160,
    MAX_H: 700,
    HEIGHT_STEP: 10,

    // Which layout document each page uses, keyed by page id so a page cannot
    // write to another page's layout by mistake.
    PAGE_FOR: {
        'page-admin-dashboard': 'admin_dashboard',
        'page-faculty-dashboard': 'faculty_dashboard',
    },

    // Deliberately limited to the chart and card surfaces. The KPI row and
    // data tables are left alone: a stretched KPI strip reads as a bug
    // rather than a chosen layout.
    WIDGET_SELECTOR: '.chart-card, .card',

    editing: false,
    _currentPage: null,
    _sizes: {},   // "<page>:<widget-id>" -> { w, h }

    // ---- role gate ------------------------------------------------------
    // The single place deciding whether editing is offered, so there is one
    // condition to audit rather than one per control. The server refuses
    // non-admin writes independently, so this is about not offering an
    // affordance that cannot work -- not the security boundary.
    //
    // Reads the signed-in user from whichever module is live. A faculty
    // session never populates ADMIN.currentUser (they logged in through
    // FACULTY), so checking only ADMIN would be correct today by accident;
    // checking both makes the gate right for the reason stated rather than by
    // coincidence.
    currentUser() {
        const candidates = [
            typeof ADMIN !== 'undefined' && ADMIN.currentUser,
            typeof FACULTY !== 'undefined' && FACULTY.currentUser,
        ];
        for (const u of candidates) {
            if (u && u.role) return u;
        }
        return null;
    },

    canEdit() {
        const user = this.currentUser();
        return !!(user && user.role === 'administrator');
    },

    layoutNameFor(pageId) {
        return this.PAGE_FOR[pageId] || null;
    },

    widgetKey(pageId, el, index) {
        // Prefer a stable id on the widget or one of its descendants (the
        // chart host divs all have ids). Fall back to the positional index,
        // which is stable for a given page as long as its markup does not
        // change -- a new widget inserted at the top would shift it, which is
        // why the id path is tried first.
        const idEl = el.id ? el : el.querySelector('[id]');
        const id = idEl && idEl.id ? idEl.id : 'idx' + index;
        return pageId + ':' + id;
    },

    // ---- applying a layout ---------------------------------------------

    // Clamp a stored width to what the current viewport can honour. Below the
    // two-column breakpoint the grid is one column wide, so every widget
    // spans one column no matter what was saved.
    _effectiveW(w) {
        if (window.innerWidth <= 900) return 1;
        return Math.max(this.MIN_W, Math.min(this.MAX_W, w || this.MIN_W));
    },

    applyTo(root, pageId) {
        if (!root || !pageId) return;
        const nodes = root.querySelectorAll(this.WIDGET_SELECTOR);
        nodes.forEach((el, i) => {
            const key = this.widgetKey(pageId, el, i);
            const saved = this._sizes[key];
            el.style.gridColumn = 'span ' + this._effectiveW(saved ? saved.w : 1);
            if (saved && saved.h && el.classList.contains('chart-card')) {
                const h = Math.max(this.MIN_H, Math.min(this.MAX_H, saved.h));
                el.style.setProperty('--widget-h', h + 'px');
            } else {
                el.style.removeProperty('--widget-h');
            }
        });
    },

    // ---- loading / saving ------------------------------------------------

    async load(pageId) {
        this._currentPage = pageId;
        const name = this.layoutNameFor(pageId);
        if (!name) return;
        try {
            const data = await API.getDashboardLayout(name);
            this._sizes = (data && data.widgets) || {};
        } catch (err) {
            // A layout is a presentation preference. If it cannot be read the
            // page must still render with its built-in defaults rather than
            // showing an error over the whole dashboard.
            console.warn('Layout load failed, using defaults:', err);
            this._sizes = {};
        }
    },

    // Re-apply on viewport change so the narrow-viewport clamp takes effect
    // when a window is resized, not only on load.
    watchResize(root) {
        const self = this;
        const onResize = function () { self.applyTo(root, self._currentPage); };
        window.addEventListener('resize', onResize);
        return function () { window.removeEventListener('resize', onResize); };
    },

    currentSizes() {
        return Object.assign({}, this._sizes);
    },

    async save() {
        const name = this.layoutNameFor(this._currentPage);
        if (!name || !this.canEdit()) return false;
        try {
            await API.saveDashboardLayout(name, this._sizes);
            return true;
        } catch (err) {
            console.error('Layout save failed:', err);
            return false;
        }
    },

    async reset() {
        const name = this.layoutNameFor(this._currentPage);
        if (!name || !this.canEdit()) return false;
        try {
            await API.resetDashboardLayout(name);
            this._sizes = {};
            return true;
        } catch (err) {
            console.error('Layout reset failed:', err);
            return false;
        }
    },

    // ---- toolbar (admin only) ---------------------------------------------

    // Renders the Save / Reset controls in the navbar. Kept out of index.html
    // and injected here so a non-admin never receives the markup at all --
    // the buttons are not merely hidden with CSS, they are never created.
    mountToolbar() {
        const slot = document.getElementById('layout-toolbar-slot');
        if (!slot) return;
        if (!this.canEdit()) {
            slot.innerHTML = '';
            return;
        }
        if (slot.dataset.mounted === '1') return;
        slot.dataset.mounted = '1';
        slot.innerHTML =
            '<span class="layout-toolbar">' +
                '<button type="button" class="layout-toolbar-btn" id="layout-save-btn" ' +
                    'onclick="LAYOUT.saveAndReport()" title="Save this layout for everyone">' +
                    '<i class="fas fa-check"></i> Save layout</button>' +
                '<button type="button" class="layout-toolbar-btn" id="layout-reset-btn" ' +
                    'onclick="LAYOUT.resetAndReport()" title="Restore the default layout">' +
                    '<i class="fas fa-undo"></i> Reset</button>' +
            '</span>';
    },

    async saveAndReport() {
        const ok = await this.save();
        if (ok) {
            showToast('Layout saved. Everyone now sees this arrangement.', 'success');
        } else {
            showToast('Could not save the layout. Please try again.', 'error');
        }
    },

    async resetAndReport() {
        const ok = await this.reset();
        const root = document.querySelector('.layout-editing') ||
            document.getElementById(this._currentPage);
        if (ok) {
            this.applyTo(root, this._currentPage);
            if (root && this.canEdit()) this._mountHandles(root, this._currentPage);
            showToast('Layout reset to default.', 'success');
        } else {
            showToast('Could not reset the layout. Please try again.', 'error');
        }
    },

    // The tab renderers are async (they await their API calls), so the widgets
    // usually do not exist yet when the layout fetch resolves. Waiting for
    // them with a MutationObserver -- rather than a fixed timeout or a bare
    // call from renderTab -- means the handles attach to the real rendered
    // cards on the first try regardless of which request finishes first.
    //
    // Disconnects as soon as one widget appears, so it is not a permanent
    // observer on the page.
    mountWhenReady(root, pageId) {
        const self = this;
        if (!root) return;
        const hasWidgets = function () {
            return root.querySelector(self.WIDGET_SELECTOR);
        };
        if (hasWidgets()) {
            self.mount(root, pageId);
            return;
        }
        const observer = new MutationObserver(function () {
            if (!hasWidgets()) return;
            observer.disconnect();
            self.mount(root, pageId);
        });
        observer.observe(root, { childList: true, subtree: true });
    },

    // Attach the editor to a rendered page. Idempotent: called again after a
    // re-render it replaces the handles rather than stacking a second set.
    // Returns an unwatch function so a caller that re-renders often can drop
    // the previous resize listener.
    mount(root, pageId) {
        if (!root || !this.layoutNameFor(pageId)) return function () {};
        this.applyTo(root, pageId);
        if (!this.canEdit()) {
            // Faculty and students: geometry only, no affordances at all.
            // Nothing is inserted into the DOM, so there is no control to
            // discover, style around, or trigger by keyboard.
            root.classList.remove('layout-editing');
            return function () {};
        }
        this._mountHandles(root, pageId);
        return this.watchResize(root);
    },

    // A width stepper on every widget, plus a drag handle on chart widgets.
    // Deliberately plain: the minimum needed, with no new interaction model
    // to learn.
    _mountHandles(root, pageId) {
        const self = this;
        root.classList.add('layout-editing');
        const nodes = root.querySelectorAll(this.WIDGET_SELECTOR);
        nodes.forEach((el, i) => {
            if (el.querySelector('.widget-grip')) return; // already mounted

            const key = this.widgetKey(pageId, el, i);
            const isChart = el.classList.contains('chart-card');

            const grip = document.createElement('div');
            grip.className = 'widget-grip';
            grip.setAttribute('role', 'group');
            grip.setAttribute('aria-label', 'Layout controls for this widget');

            const wWrap = document.createElement('div');
            wWrap.className = 'widget-grip-width';
            const dec = document.createElement('button');
            dec.type = 'button';
            dec.className = 'widget-grip-btn';
            dec.innerHTML = '<i class="fas fa-minus"></i>';
            dec.title = 'Narrower';
            dec.setAttribute('aria-label', 'Make this widget narrower');
            const val = document.createElement('span');
            val.className = 'widget-grip-val';
            const inc = document.createElement('button');
            inc.type = 'button';
            inc.className = 'widget-grip-btn';
            inc.innerHTML = '<i class="fas fa-plus"></i>';
            inc.title = 'Wider';
            inc.setAttribute('aria-label', 'Make this widget wider');
            wWrap.appendChild(dec);
            wWrap.appendChild(val);
            wWrap.appendChild(inc);

            const curW = function () {
                return self._effectiveW((self._sizes[key] || {}).w);
            };
            const sync = function () {
                val.textContent = curW() + '×';
                // Disable at the bounds rather than silently doing nothing.
                dec.disabled = curW() <= self.MIN_W;
                inc.disabled = curW() >= self.MAX_W;
            };
            const setW = function (w) {
                self._sizes[key] = Object.assign({}, self._sizes[key], { w: w });
                self.applyTo(root, pageId);
                sync();
            };
            dec.addEventListener('click', function (e) {
                e.stopPropagation();
                setW(Math.max(self.MIN_W, curW() - 1));
            });
            inc.addEventListener('click', function (e) {
                e.stopPropagation();
                setW(Math.min(self.MAX_W, curW() + 1));
            });

            grip.appendChild(wWrap);
            el.appendChild(grip);
            sync();
            // Height: only offered where a height means something, i.e. a
            // chart card with a canvas inside.
            if (isChart) {
                const handle = document.createElement('div');
                handle.className = 'widget-grip-resize';
                handle.title = 'Drag to change height';
                handle.setAttribute('role', 'separator');
                handle.setAttribute('aria-orientation', 'horizontal');
                handle.setAttribute('aria-label', 'Drag to change this chart height');
                handle.tabIndex = 0;

                const applyH = function (px) {
                    const h = Math.max(self.MIN_H, Math.min(self.MAX_H, px));
                    self._sizes[key] = Object.assign({}, self._sizes[key], { h: h });
                    self.applyTo(root, pageId);
                };

                handle.addEventListener('mousedown', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    const startY = e.clientY;
                    const startH = el.getBoundingClientRect().height;
                    // Suppress text selection for the duration of the drag,
                    // otherwise the sweep highlights the whole dashboard.
                    document.body.classList.add('widget-resizing');
                    const onMove = function (ev) {
                        // 10px steps, matching what is stored, so the saved
                        // value is tidy rather than an arbitrary pixel.
                        const delta = ev.clientY - startY;
                        const snapped =
                            Math.round((startH + delta) / self.HEIGHT_STEP) * self.HEIGHT_STEP;
                        applyH(snapped);
                    };
                    const onUp = function () {
                        document.removeEventListener('mousemove', onMove);
                        document.removeEventListener('mouseup', onUp);
                        document.body.classList.remove('widget-resizing');
                    };
                    document.addEventListener('mousemove', onMove);
                    document.addEventListener('mouseup', onUp);
                });

                // Keyboard equivalent: a drag-only control would be
                // unreachable without a mouse.
                handle.addEventListener('keydown', function (e) {
                    const step = e.shiftKey ? self.HEIGHT_STEP * 5 : self.HEIGHT_STEP;
                    const current = (self._sizes[key] || {}).h ||
                        el.getBoundingClientRect().height;
                    if (e.key === 'ArrowUp') {
                        e.preventDefault();
                        applyH(current - step);
                    } else if (e.key === 'ArrowDown') {
                        e.preventDefault();
                        applyH(current + step);
                    }
                });

                grip.appendChild(handle);
            }
        });
    },
};
if (typeof window !== 'undefined') window.LAYOUT = LAYOUT;
