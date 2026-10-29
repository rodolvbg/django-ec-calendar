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
 *   - `django-ec-calendar:select` ({start, end, allDay, jsEvent});
 * and after a move, `django-ec-calendar:event-change` ({event, saved,
 * error}).
 *
 * With resources (`config.resources`), dropping an event in another one
 * changes it too (`config.resource.editable`), and adding sends it. With
 * `config.urlState`, the view and its date are in the page's URL (`ec-view`,
 * `ec-date`), read when it opens: back from an event's page, the same
 * place. With `config.returnParam`, the pages it opens get its URL, to come
 * back to it after a save. A move asks first, with `config.confirmMove`.
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

    /** The view and date of the page's URL (`ec-view`, `ec-date`), if
     * they're the calendar's. */
    function readState(options) {
        const query = new URLSearchParams(window.location.search);
        const view = query.get("ec-view");
        const date = query.get("ec-date") ?? "";
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
            api.go(returning(`${options.add}?${query}`));
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

        async function save(info) {
            const { event } = info;
            const elsewhere = info.newResource !== undefined;
            if (elsewhere && !resource?.editable) {
                failed(info, resource?.message ?? texts.failed);
                return;
            }
            if (
                options.confirmMove &&
                !window.confirm(
                    texts.confirmMove.replace("%(title)s", event.title),
                )
            ) {
                failed(info, "");
                return;
            }
            const dates = event.allDay || options.datesOnly;
            const body = new URLSearchParams({
                pk: event.id,
                start: moment(event.start, dates),
                end: event.end ? moment(event.end, dates) : "",
            });
            if (elsewhere) {
                body.set("resource", String(info.newResource.id));
                body.set("resource_from", String(info.oldResource?.id ?? ""));
            }
            say(texts.saving);
            try {
                const response = await fetch(options.move, {
                    method: "POST",
                    headers: {
                        Accept: "application/json",
                        "X-CSRFToken": options.csrfToken || cookie("csrftoken"),
                    },
                    body,
                    credentials: "same-origin",
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.error || texts.failed);
                }
                say("");
                announce(
                    "event-change",
                    { event, saved: true, error: "" },
                    false,
                );
            } catch (error) {
                failed(info, error.message || texts.failed);
            }
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

        const state = options.urlState ? readState(options) : {};
        const views = options.views.length ? options.views : [];
        const calendar = window.EventCalendar.create(target, {
            view: options.view,
            headerToolbar: {
                start: "prev,next today",
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
                if (!options.urlState) return;
                const url = new URL(window.location.href);
                url.searchParams.set("ec-view", info.view.type);
                url.searchParams.set(
                    "ec-date",
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
            dateClick(info) {
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
            eventDrop: options.move ? save : undefined,
            eventResize: options.move ? save : undefined,
            ...options.options,
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
        for (const name of ["ec-view", "ec-date"]) {
            if (here.has(name) && !url.searchParams.has(name)) {
                url.searchParams.set(name, here.get(name));
            }
        }
    }

    const KEEP = "[data-django-ec-calendar-keep-state]";

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
