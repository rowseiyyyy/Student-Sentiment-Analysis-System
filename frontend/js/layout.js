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
    MAX_W: 6,
    MIN_H: 120,
    MAX_H: 900,
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

    // The grid containers that group widgets into reorderable sections.
    // A section is the reorder boundary: a widget can move within its own
    // section but not between sections.
    SECTION_SELECTOR: '.chart-grid, .two-col, .stats-grid',

    // ---- edit / live mode -----------------------------------------------

    // Live mode is the default: the saved layout is applied and nothing else.
    // Edit mode adds the drag and resize affordances.
    //
    // Separating the two matters for two reasons. A dashboard is mostly read,
    // and permanent handles on every card are visual noise over that. More
    // importantly the handles sit on top of the cards, so in live mode they
    // would intercept clicks meant for the content underneath.
    editing: false,
    _currentPage: null,
    _sizes: {},   // "<page>:<widget-id>" -> { w, h, order }

    // Switch modes. Turning edit mode on mounts the handles; turning it off
    // removes them and leaves only the applied geometry, so a read-only view
    // carries no editor chrome at all.
    setEditing(on) {
        const root = this._root;
        const pageId = this._currentPage;
        this.editing = !!on;
        if (root && pageId) this.mount(root, pageId);
        this.updateModeUI();
    },

    toggleEditing() {
        this.setEditing(!this.editing);
    },

    // Reflect the current mode on the toolbar button. Kept separate from
    // mountToolbar so both the initial render and a mode switch can call it.
    updateModeUI() {
        const btn = document.getElementById('layout-mode-btn');
        if (!btn) return;
        const label = btn.querySelector('.layout-mode-label');
        const icon = btn.querySelector('i');
        btn.classList.toggle('active', this.editing);
        btn.setAttribute('aria-pressed', this.editing ? 'true' : 'false');
        btn.title = this.editing
            ? 'Edit mode is on — drag widgets to reorder, drag their edges to resize. Switch off to view the finished dashboard.'
            : 'Switch to edit mode to rearrange and resize widgets';
        if (label) label.textContent = this.editing ? 'Editing' : 'Edit layout';
        if (icon) icon.className = this.editing ? 'fas fa-pen' : 'fas fa-pen-to-square';
    },


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

    // (per-widget keys are produced by keyAt/entries below; there is no
    // standalone widgetKey helper because the key depends on both the widget's
    // own id AND its position within its section.)

    // ---- sections & ordering ---------------------------------------------

    // A "section" is one grid container (.chart-grid / .two-col / a bare
    // wrapper) holding a run of sibling widgets. Reordering is scoped to a
    // section: an admin can rearrange charts within the "Sentiment" group or
    // within the "Ratings" group, but the groups themselves keep their
    // authored order. That keeps the page's narrative intact -- you cannot
    // drag a courses chart up into the header block.
    _sectionOf(el) {
        return el.parentElement;
    },

    // The widgets of a section, in their current DOM order. DOM order is the
    // source of truth at render time; _sizes[key].order is what the admin's
    // drag produced and is re-applied to the DOM by reorderSection().
    _sectionWidgets(section) {
        return Array.prototype.filter.call(
            section.children,
            (c) => c.matches && c.matches(this.WIDGET_SELECTOR)
        );
    },

    // The key for a widget given its position. The section index is part of
    // the identity because the positional fallback (no id on the widget) is
    // only unique within its own section.
    keyAt(pageId, el, widgetIndex, sectionIndex) {
        const idEl = el.id ? el : el.querySelector('[id]');
        const id = idEl && idEl.id ? idEl.id : 'idx' + widgetIndex + '_s' + sectionIndex;
        return pageId + ':' + id;
    },

    // Every widget on the page with its key, element and section, in document
    // order. Single source of truth for keying: the geometry pass, the
    // reorder pass and the handle mounting all read this, so a key can never
    // be computed two different ways.
    //
    // Widgets that are NOT inside a section are still included, each treated
    // as its own single-widget section. Several pages render a bare .card as
    // a direct child of the tab content; walking only section elements left
    // those cards with no handles and no saved geometry at all.
    entries(root, pageId) {
        const self = this;
        const out = [];
        const seen = new Set();

        const add = function (el, section, si, wi) {
            if (seen.has(el)) return;
            seen.add(el);
            out.push({
                key: self.keyAt(pageId, el, wi, si),
                el: el,
                section: section,
                sectionIndex: si,
                widgetIndex: wi,
            });
        };

        const sections = root.querySelectorAll(this.SECTION_SELECTOR);
        sections.forEach((section, si) => {
            self._sectionWidgets(section).forEach((el, wi) => add(el, section, si, wi));
        });

        // Any remaining widget is a loose card; group the siblings that share
        // a parent so two loose cards in one wrapper can still reorder.
        const looseGroups = new Map();
        Array.prototype.forEach.call(root.querySelectorAll(this.WIDGET_SELECTOR), (el) => {
            if (seen.has(el)) return;
            const parent = el.parentElement;
            if (!looseGroups.has(parent)) looseGroups.set(parent, []);
            looseGroups.get(parent).push(el);
        });
        let offset = sections.length;
        looseGroups.forEach((els, parent) => {
            els.forEach((el, wi) => add(el, parent, offset, wi));
            offset += 1;
        });
        return out;
    },

    // Reorder a section's DOM children to match the saved order values.
    //
    // Widgets with no saved order keep their authored position: sorting with a
    // default of Infinity puts them last, which would silently move a layout
    // saved before reordering existed. Instead they are given the order they
    // already occupy, and only the explicitly-ordered widgets are moved.
    // Reorder a section's widgets to match their saved order.
    //
    // A widget with no saved order keeps the position it already occupies, so
    // a layout saved before reordering existed is not reshuffled. Sorting with
    // a default of Infinity would push every untouched widget to the end --
    // the opposite of what we want.
    reorderSection(section, entriesInSection) {
        const items = entriesInSection.map((e, i) => ({
            el: e.el,
            order: this._sizes[e.key] && this._sizes[e.key].order != null
                ? this._sizes[e.key].order
                : i,
        }));
        // Stable sort, so two widgets with equal order keep markup order.
        const sorted = items.slice().sort((a, b) => a.order - b.order);
        sorted.forEach((it) => section.appendChild(it.el));
    },

    reorderAll(root, pageId) {
        // Grouped the same way entries() groups, so a reorder pass and the
        // key pass always agree on which widgets share a section.
        const bySection = new Map();
        this.entries(root, pageId).forEach((e) => {
            if (!bySection.has(e.section)) bySection.set(e.section, []);
            bySection.get(e.section).push(e);
        });
        bySection.forEach((entriesInSection, section) => {
            this.reorderSection(section, entriesInSection);
        });
    },

    // ---- applying a layout ---------------------------------------------

    // The page whose layout is loaded, or null if none is. Gestures resolve
    // keys through this, so it is set by load() and by mount() alike: a
    // caller that mounts without a preceding load would otherwise stamp
    // records under a "null:" prefix that no read would ever match.
    _page() {
        return this._currentPage || null;
    },


    // Clamp a stored width to what the current viewport can honour. Below the
    // two-column breakpoint the grid is one column wide, so every widget
    // spans one column no matter what was saved.
    _effectiveW(w) {
        if (window.innerWidth <= 900) return 1;
        return Math.max(this.MIN_W, Math.min(this.MAX_W, w || this.MIN_W));
    },

    applyTo(root, pageId) {
        if (!root || !pageId) return;
        // Apply the saved order first, so the geometry below is written onto
        // the widgets in their final positions.
        this.reorderAll(root, pageId);
        this.entries(root, pageId).forEach((entry) => {
            const el = entry.el;
            const saved = this._sizes[entry.key];
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
        const onResize = function () { self.applyTo(root, self._page()); };
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
                '<button type="button" class="layout-toolbar-btn layout-mode-btn" ' +
                    'id="layout-mode-btn" onclick="LAYOUT.toggleEditing()" aria-pressed="false" ' +
                    'title="Switch to edit mode to rearrange and resize widgets">' +
                    '<i class="fas fa-pen-to-square"></i> ' +
                    '<span class="layout-mode-label">Edit layout</span></button>' +
                '<button type="button" class="layout-toolbar-btn" id="layout-save-btn" ' +
                    'onclick="LAYOUT.saveAndReport()" title="Save this layout for everyone">' +
                    '<i class="fas fa-check"></i> Save layout</button>' +
                '<button type="button" class="layout-toolbar-btn" id="layout-reset-btn" ' +
                    'onclick="LAYOUT.resetAndReport()" title="Restore the default layout">' +
                    '<i class="fas fa-undo"></i> Reset</button>' +
            '</span>';
        this.updateModeUI();
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
        // Set the current page here too, not only in load(): mount is the
        // entry point the pages actually call, and the resize/reorder
        // gestures resolve widget keys against it.
        this._currentPage = pageId;
        this._root = root;
        this.applyTo(root, pageId);
        this.updateModeUI();
        if (!this.canEdit() || !this.editing) {
            // Live mode, or a viewer (faculty / student): geometry only, no
            // affordances at all. Nothing is inserted into the DOM, so there
            // is no control to discover, style around, click through, or
            // trigger by keyboard -- and the cards stay fully interactive.
            this._unmountHandles(root);
            root.classList.remove('layout-editing');
            return function () {};
        }
        this._mountHandles(root, pageId);
        return this.watchResize(root);
    },

    // Remove every handle this module injected. Only touches elements it
    // created (matched by the widget-grip / widget-grip-edge classes), so it
    // cannot strip anything belonging to the page's own markup.
    _unmountHandles(root) {
        if (!root || !root.querySelectorAll) return;
        Array.prototype.forEach.call(
            root.querySelectorAll('.widget-grip, .widget-grip-edge'),
            (el) => { if (el.parentElement) el.parentElement.removeChild(el); }
        );
    },

    // A width stepper on every widget, plus a drag handle on chart widgets.
    // Deliberately plain: the minimum needed, with no new interaction model
    // to learn.
    _mountHandles(root, pageId) {
        const self = this;
        root.classList.add('layout-editing');
        // Remembered so the resize and reorder gestures can re-resolve a
        // widget's key and re-apply the layout without a closure.
        this._root = root;
        this.entries(root, pageId).forEach((entry) => {
            const el = entry.el;
            if (el.querySelector('.widget-grip')) return; // already mounted
            const isChart = el.classList.contains('chart-card');

            // Set one field on this widget's record, creating it on first edit.
            const set = function (field, value) {
                const found = self._keyOf(el);
                self._sizes[found] = Object.assign({}, self._sizes[found]);
                self._sizes[found][field] = value;
            };

            // ---- move handle: drag to reorder within the section ----
            const grip = document.createElement('div');
            grip.className = 'widget-grip';
            grip.setAttribute('role', 'group');
            grip.setAttribute('aria-label', 'Layout controls for this widget');

            const move = document.createElement('button');
            move.type = 'button';
            move.className = 'widget-grip-move';
            move.title = 'Drag to reorder';
            move.setAttribute('aria-label', 'Drag to reorder this widget within its section');
            grip.appendChild(move);
            this._makeDraggable(move, el, entry.section, set);
            this._makeReorderKeyboard(move, el, entry.section, set);
            el.appendChild(grip);

            // ---- edge handles: width, and width+height on charts ----
            this._addResizeHandle(el, 'e', 'ew-resize', 'Drag to change width', 'width', set);
            if (isChart) {
                this._addResizeHandle(el, 'se', 'nwse-resize',
                    'Drag to change width and height', 'both', set);
            }
        });
    },

    // Re-resolve a widget's key. The key is position-derived for widgets
    // without an id, so it must be looked up at gesture time, not captured at
    // mount time: a reorder can change a widget's position.
    _keyOf(el) {
        const page = this._page();
        if (!page || !this._root) return null;
        const found = this.entries(this._root, page).filter((e) => e.el === el)[0];
        return found ? found.key : null;
    },

    // ---- drag to reorder ------------------------------------------------

    // HTML5 drag-and-drop, scoped to one section. The dragged widget moves
    // within its own section only, so a chart can never be dropped into a
    // different group -- that section boundary is the requested constraint.
    _makeDraggable(handle, el, section, set) {
        const self = this;
        el.draggable = true;
        let dragging = false;

        el.addEventListener('dragstart', function (e) {
            // Only a drag that began on the move handle is a reorder, so
            // text selection inside a card still behaves normally.
            if (!e.target.classList.contains('widget-grip-move')) {
                e.preventDefault();
                return;
            }
            dragging = true;
            el.classList.add('widget-dragging');
            e.dataTransfer.effectAllowed = 'move';
            // Firefox refuses to start a drag with no payload set.
            try { e.dataTransfer.setData('text/plain', 'widget'); } catch (err) { /* IE */ }
        });

        el.addEventListener('dragend', function () {
            dragging = false;
            el.classList.remove('widget-dragging');
            self._clearDropMarkers();
        });

        this._sectionWidgets(section).forEach(function (target) {
            target.addEventListener('dragover', function (e) {
                if (!dragging || target === el) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                // Before the midpoint the widget goes before the target,
                // after it goes after: the standard half-and-half rule.
                const rect = target.getBoundingClientRect();
                const after = (e.clientY - rect.top) > rect.height / 2;
                self._clearDropMarkers();
                target.classList.add(after ? 'widget-drop-after' : 'widget-drop-before');
            });
            target.addEventListener('dragleave', function () {
                target.classList.remove('widget-drop-before', 'widget-drop-after');
            });
            target.addEventListener('drop', function (e) {
                if (!dragging || target === el) return;
                e.preventDefault();
                e.stopPropagation();
                const rect = target.getBoundingClientRect();
                const after = (e.clientY - rect.top) > rect.height / 2;
                self._moveRelative(el, target, after, section, set);
                self._clearDropMarkers();
            });
        });
    },

    _clearDropMarkers() {
        Array.prototype.forEach.call(
            document.querySelectorAll('.widget-drop-before, .widget-drop-after'),
            (m) => m.classList.remove('widget-drop-before', 'widget-drop-after')
        );
    },

    // Move `el` before or after `target`, then write an explicit order onto
    // every widget in the section. Recording the whole section (rather than a
    // from/to pair) keeps the stored record unambiguous and makes the next
    // load a plain sort.
    //
    // Every widget in the section gets an order, not just the one that moved.
    // If only the moved widget were stamped, the siblings would keep whatever
    // order they already had and two of them could end up claiming the same
    // slot, making the next load ambiguous.
    _moveRelative(el, target, after, section, set) {
        section.insertBefore(el, after ? target.nextSibling : target);
        const widgets = this._sectionWidgets(section);
        // Stamp by identity, resolving each key *after* the DOM move so
        // position-derived keys match the new order.
        widgets.forEach((w, i) => {
            const setter = this._setterFor(w);
            if (setter) setter('order', i);
        });
    },

    // A bound setter for one widget element, for code that only has the
    // element in hand.
    _setterFor(el) {
        const self = this;
        const key = this._keyOf(el);
        if (!key) return null;
        return function (field, value) {
            self._sizes[key] = Object.assign({}, self._sizes[key]);
            self._sizes[key][field] = value;
        };
    },

    // Keyboard equivalent for the drag handle: a drag-only control would be
    // unreachable without a mouse. Alt+Arrow moves the widget within its
    // section, stopping at the ends.
    _makeReorderKeyboard(handle, el, section, set) {
        const self = this;
        handle.addEventListener('keydown', function (e) {
            const back = e.key === 'ArrowLeft' || e.key === 'ArrowUp';
            const fwd = e.key === 'ArrowRight' || e.key === 'ArrowDown';
            if (!back && !fwd) return;
            e.preventDefault();
            const widgets = self._sectionWidgets(section);
            const i = widgets.indexOf(el);
            const j = back ? i - 1 : i + 1;
            if (i === -1 || j < 0 || j >= widgets.length) return;
            // Moving "back" means landing after the previous sibling.
            self._moveRelative(el, widgets[j], back, section, set);
        });
    },

    // Edge/corner resize drag. `mode` is 'width', 'height' or 'both'.
    // Width is stored in grid units, so a horizontal drag snaps to whole
    // columns rather than to an arbitrary pixel: the unit IS a column, and a
    // fractional span would have no meaning on reload.
    _addResizeHandle(el, corner, cursor, title, mode, set) {
        const self = this;
        const handle = document.createElement('div');
        handle.className = 'widget-grip-edge widget-grip-edge-' + corner;
        handle.style.cursor = cursor;
        handle.title = title;
        handle.setAttribute('role', 'separator');
        handle.tabIndex = 0;
        el.appendChild(handle);

        // The width of one grid unit, measured from a sibling spanning a
        // single column. Turns a pixel drag into column steps.
        //
        // Guarded because getComputedStyle is not available in every host
        // (and a throw here would kill the whole drag on mousedown). Falls
        // back to the section's own width divided by an assumed column count,
        // which is close enough to snap to sensible steps.
        const unitWidth = function () {
            const section = el.parentElement;
            const sibs = self._sectionWidgets(section).filter((s) => s !== el);
            const probe = sibs[0] || el;
            const probeRect = probe.getBoundingClientRect();
            if (probeRect && probeRect.width) {
                let gap = 0;
                if (typeof window.getComputedStyle === 'function') {
                    const cs = window.getComputedStyle(probe);
                    gap = parseFloat(cs.columnGap || cs.gap || '0') || 0;
                }
                return Math.max(80, probeRect.width + gap);
            }
            // No measurable geometry (detached, or a stub DOM): assume the
            // grid is the common 2-column case so the drag still responds.
            const sectionRect = section.getBoundingClientRect
                ? section.getBoundingClientRect()
                : null;
            const basis = sectionRect && sectionRect.width ? sectionRect.width : 800;
            return Math.max(80, basis / 2);
        };

        handle.addEventListener('mousedown', function (e) {
            e.preventDefault();
            e.stopPropagation();
            const startX = e.clientX;
            const startY = e.clientY;
            const startW = self._effectiveW((self._sizes[self._keyOf(el)] || {}).w);
            const startH = el.getBoundingClientRect().height;
            const uw = unitWidth();
            // Suppress text selection for the sweep, otherwise dragging
            // highlights the whole dashboard.
            document.body.classList.add('widget-resizing');
            handle.classList.add('widget-resizing');

            const onMove = function (ev) {
                if (mode !== 'height') {
                    const steps = Math.round((ev.clientX - startX) / uw);
                    set('w', Math.max(self.MIN_W, Math.min(self.MAX_W, startW + steps)));
                }
                if (mode !== 'width') {
                    const dy = ev.clientY - startY;
                    set('h', Math.max(self.MIN_H, Math.min(self.MAX_H,
                        Math.round((startH + dy) / self.HEIGHT_STEP) * self.HEIGHT_STEP)));
                }
                self.applyTo(self._root, self._page());
            };
            const onUp = function () {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                document.body.classList.remove('widget-resizing');
                handle.classList.remove('widget-resizing');
            };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });

        // Arrow keys, so neither dimension is mouse-only. Shift moves faster.
        handle.addEventListener('keydown', function (e) {
            const step = e.shiftKey ? 3 : 1;
            const s = self._sizes[self._keyOf(el)] || {};
            const w = self._effectiveW(s.w);
            const h = s.h || el.getBoundingClientRect().height;
            if (e.key === 'ArrowLeft' && mode !== 'height') {
                set('w', Math.max(self.MIN_W, w - step));
            } else if (e.key === 'ArrowRight' && mode !== 'height') {
                set('w', Math.min(self.MAX_W, w + step));
            } else if (e.key === 'ArrowUp' && mode !== 'width') {
                set('h', Math.max(self.MIN_H, h - self.HEIGHT_STEP * step));
            } else if (e.key === 'ArrowDown' && mode !== 'width') {
                set('h', Math.min(self.MAX_H, h + self.HEIGHT_STEP * step));
            } else {
                return;
            }
            e.preventDefault();
            self.applyTo(self._root, self._page());
        });
    },

};
if (typeof window !== 'undefined') window.LAYOUT = LAYOUT;
