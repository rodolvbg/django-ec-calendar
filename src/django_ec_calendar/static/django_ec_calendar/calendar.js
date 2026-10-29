/**
 * django-ec-calendar: makes each [data-django-ec-calendar] element
 * an EventCalendar (https://github.com/vkurko/calendar), from the JSON of
 * its configuration (the element whose id it names: no inline script).
 *
 * The events come from `config.events` (with `config.params`: a
 * changelist's filters). Clicking one opens its page (its `url`);
 * selecting dates, or clicking one, opens `config.add` with them; dragging
 * one, or its end, saves its dates at `config.move` (and puts it back if it
 * can't). The server's times have no offset: the calendar shows them as
 * they are (the site's wall-clock time), whatever the browser's time zone,
 * and sends them back so; its `timeZone` is the site's, for "today" and the
 * time now.
 *
 * Each of those first fires an event on the calendar's element, which
 * bubbles and can be cancelled (`preventDefault()`: not done), with its
 * dates as the server reads them (`start`, `end`):
 *   - `django-ec-calendar:event-click` ({event, url, jsEvent}),
 *   - `django-ec-calendar:date-click` ({start, allDay, jsEvent}),
 *   - `django-ec-calendar:select` ({start, end, allDay, jsEvent}),
 *   - `django-ec-calendar:move` ({event, mode, save(), revert(), pend()}:
 *     cancelled, the page does it, calling one of those);
 * and after a move, `django-ec-calendar:event-change` ({event, saved,
 * error, savedEvent: the server's}); after several saved together, `django-ec-calendar:batch-change`
 * ({saved, events, errors}).
 *
 * With resources (`config.resources`), dropping an event in another one
 * changes it too (`config.resource.editable`), and adding sends it. With
 * `config.urlState`, the view and its date are in the page's URL (`ec-view`,
 * `ec-date`, or `config.urlParams`' names; the views by `config.urlViews`'
 * names), read when it opens, and written only when one goes elsewhere
 * (opening it leaves its URL as it is): back from an event's page, the same
 * place. With `config.returnParam`, the pages it opens get its URL, to come
 * back to it after a save.
 *
 * A drag goes as `config.moveMode` says: "save" (at once), "confirm" (asked
 * first) or "batch" (kept, with a bar to save them together at
 * `config.moves`, or discard them; leaving the page with some asks).
 *
 * Closed times (background events with `extendedProps.closed`: out of the
 * business hours) are the calendar's in the views without resources, and
 * each resource's in theirs; with `config.outsideHours` "block", they can't
 * be selected, clicked, nor moved to.
 *
 * With `config.datePicker`, a date field in its toolbar goes to the date
 * chosen (and follows the one it shows).
 *
 * It follows the page's theme, light or dark (Django's admin, Unfold, a
 * "dark" class), else the system's. `window.djangoEcCalendar.setup()`
 * makes those added later.
 */
(() => {
    const two = (number) => String(number).padStart(2, "0");

    /** A moment of the calendar as the server reads it: a date, or the
     * wall-clock time. EventCalendar's dates hold it in the browser's
     * local fields, whatever its time zone. */
    function moment(date, allDay) {
        const day = `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())}`;
        if (allDay) return day;
        return `${day}T${two(date.getHours())}:${two(date.getMinutes())}:${two(date.getSeconds())}`;
    }

    function cookie(name) {
        const found = document.cookie
            .split(";")
            .map((part) => part.trim())
            .find((part) => part.startsWith(`${name}=`));
        return found ? decodeURIComponent(found.slice(name.length + 1)) : "";
    }

    // The page's theme ------------------------------------------------------

    /** The lightness (0–1) of a computed colour; null: transparent, or a
     * format it doesn't read. */
    function lightness(color) {
        const value = String(color).trim();
        let match = /^rgba?\(([^)]+)\)$/i.exec(value);
        if (match) {
            const [r, g, b, a = "1"] = match[1]
                .split(/[\s,/]+/)
                .filter(Boolean);
            if (Number.parseFloat(a) === 0) return null;
            return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
        }
        match = /^oklch\(\s*([\d.]+)(%?)[^/)]*(?:\/\s*([\d.]+)%?)?\s*\)$/i.exec(
            value,
        );
        if (match) {
            if (match[3] !== undefined && Number.parseFloat(match[3]) === 0) {
                return null;
            }
            return Number.parseFloat(match[1]) / (match[2] ? 100 : 1);
        }
        return null;
    }

    /** "dark", "light", or null (the system's): the closest data-theme
     * (Django's admin) or "dark"/"light" class (Unfold, Tailwind) around,
     * else the lightness of the closest background. */
    function pageTheme(element) {
        for (
            let node = element.parentElement;
            node;
            node = node.parentElement
        ) {
            const theme = node.getAttribute("data-theme");
            if (theme === "light" || theme === "dark") return theme;
            if (node.classList.contains("dark")) return "dark";
            if (node.classList.contains("light")) return "light";
        }
        for (
            let node = element.parentElement;
            node;
            node = node.parentElement
        ) {
            const value = lightness(getComputedStyle(node).backgroundColor);
            if (value !== null) return value < 0.5 ? "dark" : "light";
        }
        return null;
    }

    const themed = new Set();

    function applyTheme(element) {
        const theme = pageTheme(element);
        element.classList.toggle("ec-dark", theme === "dark");
        element.classList.toggle("ec-auto-dark", theme === null);
    }

    function follow(element) {
        themed.add(element);
        applyTheme(element);
        if (themed.size > 1) return;
        const again = () => {
            for (const node of themed) applyTheme(node);
        };
        const observer = new MutationObserver(again);
        for (const node of [document.documentElement, document.body]) {
            observer.observe(node, {
                attributes: true,
                attributeFilter: ["class", "data-theme", "style"],
            });
        }
        window
            .matchMedia?.("(prefers-color-scheme: dark)")
            ?.addEventListener?.("change", again);
    }

    // The calendar ----------------------------------------------------------

    function config(element) {
        const node = document.getElementById(element.dataset.djangoEcCalendar);
        try {
            return node ? JSON.parse(node.textContent) : null;
        } catch {
            return null;
        }
    }

    function node(tag, className, text) {
        const made = document.createElement(tag);
        made.className = className;
        made.textContent = text;
        return made;
    }

    /** The parameters of the page's URL with its view and date. */
    const DEFAULT_PARAMS = { view: "ec-view", date: "ec-date" };

    /** The names of those of every calendar of the page (for its filters'
     * links and forms to keep them). */
    const stateParams = new Set(Object.values(DEFAULT_PARAMS));

    const urlParams = (options) => ({
        ...DEFAULT_PARAMS,
        ...(options.urlParams ?? {}),
    });

    /** The view and date of the page's URL, if they're the calendar's (a
     * view by its name in the URL, `config.urlViews`, or its own). */
    function readState(options) {
        const names = urlParams(options);
        const query = new URLSearchParams(window.location.search);
        let view = query.get(names.view);
        const date = query.get(names.date) ?? "";
        const named = Object.entries(options.urlViews ?? {}).find(
            ([, alias]) => alias === view,
        );
        if (named) view = named[0];
        return {
            view: [options.view, ...options.views].includes(view)
                ? view
                : undefined,
            date: /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : undefined,
        };
    }

    function create(element, options) {
        const texts = options.texts;
        const resource = options.resource;
        const status = element.querySelector(".django-ec-calendar-status");
        const target = document.createElement("div");
        element.append(target);
        element.classList.toggle(
            "django-ec-calendar--no-today",
            options.highlightToday === false,
        );

        function say(text) {
            if (!status) return;
            status.textContent = text;
            status.hidden = !text;
        }

        /** Fire `django-ec-calendar:<name>`; whether it wasn't cancelled. */
        function announce(name, detail, cancelable = true) {
            return element.dispatchEvent(
                new CustomEvent(`django-ec-calendar:${name}`, {
                    bubbles: true,
                    cancelable,
                    detail,
                }),
            );
        }

        /** `url`, taking the calendar's (where it is now) to come back. */
        function returning(url) {
            if (!options.returnParam) return url;
            const next = new URL(url, window.location.href);
            next.searchParams.set(
                options.returnParam,
                window.location.pathname + window.location.search,
            );
            return next.origin === window.location.origin
                ? next.pathname + next.search + next.hash
                : url;
        }

        /** A resource's id, for the server; null: none. */
        const resourceId = (item) =>
            item && item.id !== resource?.empty ? String(item.id) : null;

        function add(start, end, allDay, where) {
            const dates = allDay || options.datesOnly;
            const query = new URLSearchParams({ start: moment(start, dates) });
            if (end) query.set("end", moment(end, dates));
            const id = resource ? resourceId(where) : null;
            if (id !== null) query.set(resource.param, id);
            // Its add page may have its own (an inline's: its object).
            const url = new URL(options.add, window.location.href);
            for (const [name, value] of query)
                url.searchParams.set(name, value);
            api.go(returning(url.pathname + url.search));
        }

        function failed(info, error) {
            info.revert();
            say(error);
            announce(
                "event-change",
                { event: info.event, saved: false, error },
                false,
            );
        }

        /** A move, as the server reads it. */
        function payload(info) {
            const { event } = info;
            const dates = event.allDay || options.datesOnly;
            const move = {
                pk: event.id,
                start: moment(event.start, dates),
                end: event.end ? moment(event.end, dates) : "",
            };
            if (info.newResource !== undefined) {
                move.resource = String(info.newResource.id);
                move.resource_from = String(info.oldResource?.id ?? "");
            }
            return move;
        }

        const headers = (json) => ({
            Accept: "application/json",
            "X-CSRFToken": options.csrfToken || cookie("csrftoken"),
            ...(json ? { "Content-Type": "application/json" } : {}),
        });

        /** Save a move now; saved, the event as the server says it is (its
         * color, details, resources… may depend on where it went). */
        async function send(info) {
            say(texts.saving);
            try {
                const response = await fetch(options.move, {
                    method: "POST",
                    headers: headers(false),
                    body: new URLSearchParams(payload(info)),
                    credentials: "same-origin",
                });
                // No body (or not JSON): nothing of it.
                const data = await Promise.resolve()
                    .then(() => response.json())
                    .catch(() => ({}));
                if (!response.ok) throw new Error(data?.error || texts.failed);
                const saved = data?.event ?? null;
                if (saved) calendar.updateEvent(saved);
                say("");
                announce(
                    "event-change",
                    {
                        event: info.event,
                        saved: true,
                        error: "",
                        savedEvent: saved,
                    },
                    false,
                );
            } catch (error) {
                failed(info, error.message || texts.failed);
            }
        }

        // Several moves, kept until they're saved together ("batch").
        const pending = new Map();
        const bar = document.createElement("div");
        bar.className = "django-ec-calendar-pending";
        bar.hidden = true;
        const count = document.createElement("span");
        const saveAll = node(
            "button",
            "django-ec-calendar-save button default",
            texts.save,
        );
        const discard = node(
            "button",
            "django-ec-calendar-discard button",
            texts.discard,
        );
        saveAll.type = discard.type = "button";
        bar.append(count, saveAll, discard);
        element.insertBefore(bar, target);
        const plural = new Intl.PluralRules(options.locale);

        function showPending() {
            bar.hidden = pending.size === 0;
            const words =
                texts.pending?.[plural.select(pending.size)] ??
                texts.pending?.other ??
                "%(count)s";
            count.textContent = words.replace(
                "%(count)s",
                String(pending.size),
            );
        }

        /** Keep a move, to save it with the others. */
        function pend(info) {
            if (!options.moves) return send(info);
            const move = payload(info);
            const before = pending.get(move.pk);
            if (before?.resource !== undefined) {
                // From where it was before all of them.
                move.resource ??= before.resource;
                move.resource_from = before.resource_from;
            }
            pending.set(move.pk, move);
            const classes = info.event.classNames ?? [];
            if (!classes.includes(PENDING)) {
                info.event.classNames = [...classes, PENDING];
                calendar.updateEvent(info.event);
            }
            showPending();
        }

        saveAll.addEventListener("click", async () => {
            say(texts.saving);
            const moves = [...pending.values()];
            try {
                const response = await fetch(options.moves, {
                    method: "POST",
                    headers: headers(true),
                    body: JSON.stringify({ moves }),
                    credentials: "same-origin",
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    const errors = data.errors ?? {};
                    say(
                        Object.values(errors).join(" ") ||
                            data.error ||
                            texts.failed,
                    );
                    announce(
                        "batch-change",
                        { saved: false, events: [], errors },
                        false,
                    );
                    return;
                }
                pending.clear();
                showPending();
                say("");
                calendar.refetchEvents();
                announce(
                    "batch-change",
                    { saved: true, events: data.events ?? [], errors: {} },
                    false,
                );
            } catch {
                say(texts.failed);
            }
        });

        discard.addEventListener("click", () => {
            pending.clear();
            showPending();
            say("");
            calendar.refetchEvents(); // Where they are.
        });

        window.addEventListener("beforeunload", (event) => {
            if (pending.size) {
                event.preventDefault();
                event.returnValue = "";
            }
        });

        /** An event dropped, or resized: as its mode says, unless the page
         * does it (its `move` event, cancelled). */
        function moved(info) {
            if (info.newResource !== undefined && !resource?.editable) {
                failed(info, resource?.message ?? texts.failed);
                return Promise.resolve();
            }
            const mode = options.moveMode;
            const detail = {
                event: info.event,
                mode,
                save: () => send(info),
                revert: () => info.revert(),
                pend: () => pend(info),
            };
            if (!announce("move", detail)) return Promise.resolve();
            if (mode === "batch") {
                pend(info);
                return Promise.resolve();
            }
            if (
                mode === "confirm" &&
                !window.confirm(
                    texts.confirmMove.replace("%(title)s", info.event.title),
                )
            ) {
                failed(info, "");
                return Promise.resolve();
            }
            return send(info);
        }

        /** Its title, and its details under it (as text); without any, as
         * EventCalendar shows it. */
        function content(info) {
            const details = info.event.extendedProps?.details ?? [];
            if (!details.length) return undefined;
            const listed = info.view.type.startsWith("list");
            const nodes = [];
            if (!listed && info.timeText) {
                nodes.push(node("time", "ec-event-time", info.timeText));
            }
            nodes.push(node("h4", "ec-event-title", info.event.title));
            for (const { label, value } of details) {
                const line = node(
                    "span",
                    "django-ec-calendar-detail",
                    listed ? `${label}: ${value}` : value,
                );
                line.title = label;
                nodes.push(line);
            }
            return { domNodes: nodes };
        }

        const isResourceView = (view) => view.type.startsWith("resource");

        /** Whether an event is a closed time of this view: the calendar's
         * in a view without resources, a resource's in theirs. */
        const closedHere = (event, view) =>
            Boolean(event.resourceIds?.length) === isResourceView(view);

        /** Whether `[start, end)` is open, for those resources (their ids;
         * none: the calendar's). */
        function isOpen(start, end, view, resources = []) {
            const until = end ?? new Date(start.getTime() + 1);
            return !calendar
                .getEvents()
                .some(
                    (event) =>
                        event.extendedProps?.closed &&
                        closedHere(event, view) &&
                        (!isResourceView(view) ||
                            resources.some((id) =>
                                event.resourceIds
                                    .map(String)
                                    .includes(String(id)),
                            )) &&
                        event.start < until &&
                        event.end > start,
                );
        }

        const blocks = options.outsideHours === "block";

        /** Where an event was dropped, or resized: open? */
        const movable = (info) =>
            isOpen(
                info.event.start,
                info.event.end,
                info.view,
                info.newResource
                    ? [info.newResource.id]
                    : (info.event.resourceIds ?? []),
            );

        // A date to go to (`config.datePicker`), in its toolbar.
        const picker = document.createElement("input");
        picker.type = "date";
        picker.className = "django-ec-calendar-date";
        picker.setAttribute("aria-label", texts.goToDate ?? "");
        const range = options.options?.validRange ?? {};
        if (range.start) picker.min = String(range.start).slice(0, 10);
        if (range.end) picker.max = String(range.end).slice(0, 10);
        picker.addEventListener("change", () => {
            if (picker.value) calendar.setOption("date", picker.value);
        });

        const state = options.urlState ? readState(options) : {};
        const names = urlParams(options);
        stateParams.add(names.view);
        stateParams.add(names.date);
        // What it shows: written in the URL only when it changes (not when
        // it opens).
        let shown = null;
        const views = options.views.length ? options.views : [];
        // (Its callbacks read `calendar` once it's made: when they're called.)
        const calendar = window.EventCalendar.create(target, {
            view: options.view,
            headerToolbar: {
                start: options.datePicker
                    ? "prev,next today datePicker"
                    : "prev,next today",
                center: "title",
                end: views.join(","),
            },
            buttonText(defaults) {
                const text = { ...defaults, ...texts.buttons };
                // Its views' "prev" and "next" ("Previous week"…).
                for (const key of ["prev", "next"]) {
                    text[key] = texts.labels[defaults[key]] ?? defaults[key];
                }
                return text;
            },
            locale: options.locale,
            firstDay: options.firstDay,
            timeZone: options.timeZone,
            dayMaxEvents: true,
            eventSources: [
                { url: options.events, extraParams: options.params },
            ],
            ...(options.resources ? { resources: options.resources } : {}),
            allDayContent: texts.allDay,
            noEventsContent: texts.noEvents,
            moreLinkContent: (arg) =>
                texts.more.replace("%(count)s", String(arg.num)),
            eventContent: content,
            datesSet(info) {
                element.dataset.view = info.view.type;
                picker.value = moment(info.view.currentStart, true);
                const now = `${info.view.type} ${moment(info.view.currentStart, true)}`;
                const opening = shown === null;
                if (!options.urlState || now === shown) return;
                shown = now;
                if (opening) return; // Its URL as it is.
                const url = new URL(window.location.href);
                url.searchParams.set(
                    names.view,
                    options.urlViews?.[info.view.type] ?? info.view.type,
                );
                url.searchParams.set(
                    names.date,
                    moment(info.view.currentStart, true),
                );
                window.history.replaceState(window.history.state, "", url);
            },
            eventClick(info) {
                const url = info.event.extendedProps?.url ?? null;
                const detail = {
                    event: info.event,
                    url,
                    jsEvent: info.jsEvent,
                };
                if (announce("event-click", detail) && url) {
                    api.go(returning(url));
                }
            },
            selectable: Boolean(options.add),
            select(info) {
                const dates = info.allDay || options.datesOnly;
                const detail = {
                    start: moment(info.start, dates),
                    end: moment(info.end, dates),
                    allDay: info.allDay,
                    resource: resourceId(info.resource),
                    jsEvent: info.jsEvent,
                };
                if (announce("select", detail) && options.add) {
                    add(info.start, info.end, info.allDay, info.resource);
                }
            },
            // The closed times of this view only.
            eventFilter: (info) =>
                !info.event.extendedProps?.closed ||
                closedHere(info.event, info.view),
            ...(blocks
                ? {
                      selectConstraint: (info) =>
                          isOpen(
                              info.start,
                              info.end,
                              info.view,
                              info.resource ? [info.resource.id] : [],
                          ),
                      dragConstraint: movable,
                      resizeConstraint: movable,
                  }
                : {}),
            dateClick(info) {
                if (
                    blocks &&
                    !isOpen(
                        info.date,
                        null,
                        info.view,
                        info.resource ? [info.resource.id] : [],
                    )
                ) {
                    return;
                }
                const dates = info.allDay || options.datesOnly;
                const detail = {
                    start: moment(info.date, dates),
                    allDay: info.allDay,
                    resource: resourceId(info.resource),
                    jsEvent: info.jsEvent,
                };
                if (announce("date-click", detail) && options.add) {
                    add(info.date, null, info.allDay, info.resource);
                }
            },
            // Each event says whether it may be dragged (its `editable`).
            editable: false,
            ...(options.move && options.moveMode !== "off"
                ? { eventDrop: moved, eventResize: moved }
                : {}),
            ...options.options,
            customButtons: {
                datePicker: { content: { domNodes: [picker] } },
                ...options.options?.customButtons,
            },
            // Where it was (the page's URL), over where it opens.
            ...(state.view ? { view: state.view } : {}),
            ...(state.date ? { date: state.date } : {}),
        });
        follow(element);
        return calendar;
    }

    /** Links and forms that change a calendar's page (its filters, its
     * search) keep its view and date. */
    function keepState(url) {
        const here = new URLSearchParams(window.location.search);
        for (const name of stateParams) {
            if (here.has(name) && !url.searchParams.has(name)) {
                url.searchParams.set(name, here.get(name));
            }
        }
    }

    const KEEP = "[data-django-ec-calendar-keep-state]";

    /** A moved event waiting to be saved ("batch"). */
    const PENDING = "django-ec-calendar-pending-event";

    document.addEventListener(
        "click",
        (event) => {
            const link = event.target.closest?.(`${KEEP} a[href]`);
            if (!link) return;
            const url = new URL(link.href, window.location.href);
            if (url.pathname !== window.location.pathname) return;
            keepState(url);
            link.href = url.href;
        },
        true,
    );

    document.addEventListener(
        "submit",
        (event) => {
            const form = event.target;
            if (!form.closest?.(KEEP) || form.method.toLowerCase() !== "get") {
                return;
            }
            const url = new URL(window.location.href);
            url.search = "";
            keepState(url);
            for (const [name, value] of url.searchParams) {
                if (form.querySelector(`[name="${name}"]`)) continue;
                const input = document.createElement("input");
                input.type = "hidden";
                input.name = name;
                input.value = value;
                form.append(input);
            }
        },
        true,
    );

    function setup(root = document) {
        const made = [];
        for (const element of root.querySelectorAll(
            "[data-django-ec-calendar]",
        )) {
            if (element.djangoEcCalendar || !window.EventCalendar) continue;
            const options = config(element);
            if (!options) continue;
            element.djangoEcCalendar = create(element, options);
            made.push(element.djangoEcCalendar);
        }
        return made;
    }

    const api = {
        setup,
        moment,
        pageTheme,
        /** Where a click leads (replaceable: a single-page app's router). */
        go: (url) => window.location.assign(url),
    };
    window.djangoEcCalendar = api;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => setup());
    } else {
        setup();
    }
})();
