/**
 * django-event-calendar: makes each [data-django-event-calendar] element
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
 *   - `django-event-calendar:event-click` ({event, url, jsEvent}),
 *   - `django-event-calendar:date-click` ({start, allDay, jsEvent}),
 *   - `django-event-calendar:select` ({start, end, allDay, jsEvent});
 * and after a move, `django-event-calendar:event-change` ({event, saved,
 * error}).
 *
 * It follows the page's theme, light or dark (Django's admin, Unfold, a
 * "dark" class), else the system's. `window.djangoEventCalendar.setup()`
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
        const node = document.getElementById(
            element.dataset.djangoEventCalendar,
        );
        try {
            return node ? JSON.parse(node.textContent) : null;
        } catch {
            return null;
        }
    }

    function create(element, options) {
        const texts = options.texts;
        const status = element.querySelector(".django-event-calendar-status");
        const target = document.createElement("div");
        element.append(target);

        function say(text) {
            if (!status) return;
            status.textContent = text;
            status.hidden = !text;
        }

        /** Fire `django-event-calendar:<name>`; whether it wasn't cancelled. */
        function announce(name, detail, cancelable = true) {
            return element.dispatchEvent(
                new CustomEvent(`django-event-calendar:${name}`, {
                    bubbles: true,
                    cancelable,
                    detail,
                }),
            );
        }

        function add(start, end, allDay) {
            const dates = allDay || options.datesOnly;
            const query = new URLSearchParams({ start: moment(start, dates) });
            if (end) query.set("end", moment(end, dates));
            api.go(`${options.add}?${query}`);
        }

        async function save(info) {
            const { event } = info;
            const dates = event.allDay || options.datesOnly;
            const body = new URLSearchParams({
                pk: event.id,
                start: moment(event.start, dates),
                end: event.end ? moment(event.end, dates) : "",
            });
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
                info.revert();
                say(error.message || texts.failed);
                announce(
                    "event-change",
                    {
                        event,
                        saved: false,
                        error: error.message || texts.failed,
                    },
                    false,
                );
            }
        }

        const views = options.views.length ? options.views : [];
        const calendar = window.EventCalendar.create(target, {
            view: options.view,
            headerToolbar: {
                start: "prev,next today",
                center: "title",
                end: views.join(","),
            },
            buttonText: (defaults) => ({ ...defaults, ...texts }),
            locale: options.locale,
            firstDay: options.firstDay,
            timeZone: options.timeZone,
            dayMaxEvents: true,
            eventSources: [
                { url: options.events, extraParams: options.params },
            ],
            allDayContent: texts.allDay,
            noEventsContent: texts.noEvents,
            moreLinkContent: (arg) =>
                texts.more.replace("%(count)s", String(arg.num)),
            eventClick(info) {
                const url = info.event.extendedProps?.url ?? null;
                const detail = {
                    event: info.event,
                    url,
                    jsEvent: info.jsEvent,
                };
                if (announce("event-click", detail) && url) api.go(url);
            },
            selectable: Boolean(options.add),
            select(info) {
                const dates = info.allDay || options.datesOnly;
                const detail = {
                    start: moment(info.start, dates),
                    end: moment(info.end, dates),
                    allDay: info.allDay,
                    jsEvent: info.jsEvent,
                };
                if (announce("select", detail) && options.add) {
                    add(info.start, info.end, info.allDay);
                }
            },
            dateClick(info) {
                const dates = info.allDay || options.datesOnly;
                const detail = {
                    start: moment(info.date, dates),
                    allDay: info.allDay,
                    jsEvent: info.jsEvent,
                };
                if (announce("date-click", detail) && options.add) {
                    add(info.date, null, info.allDay);
                }
            },
            // Each event says whether it may be dragged (its `editable`).
            editable: false,
            eventDrop: options.move ? save : undefined,
            eventResize: options.move ? save : undefined,
            ...options.options,
        });
        follow(element);
        return calendar;
    }

    function setup(root = document) {
        const made = [];
        for (const element of root.querySelectorAll(
            "[data-django-event-calendar]",
        )) {
            if (element.djangoEventCalendar || !window.EventCalendar) continue;
            const options = config(element);
            if (!options) continue;
            element.djangoEventCalendar = create(element, options);
            made.push(element.djangoEventCalendar);
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
    window.djangoEventCalendar = api;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => setup());
    } else {
        setup();
    }
})();
