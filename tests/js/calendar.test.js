import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const SCRIPT =
    "../../src/django_event_calendar/static/django_event_calendar/calendar.js";

const TEXTS = {
    today: "Today",
    timeGridWeek: "Week",
    allDay: "All day",
    noEvents: "No events",
    more: "+%(count)s more",
    saving: "Saving…",
    failed: "Not saved",
};

const CONFIG = {
    events: "/admin/agenda/booking/calendar/events/",
    params: { room__id__exact: "1" },
    view: "timeGridWeek",
    views: ["dayGridMonth", "timeGridWeek"],
    add: "/admin/agenda/booking/add/",
    move: "/admin/agenda/booking/calendar/move/",
    csrfToken: "token",
    datesOnly: false,
    locale: "es",
    firstDay: 1,
    timeZone: "+01:00",
    texts: TEXTS,
    options: { slotMinTime: "07:00" },
};

let created;

function page(config = CONFIG, { around = "", raw = null } = {}) {
    const json = raw ?? JSON.stringify(config);
    document.body.innerHTML = `<div id="wrap" ${around}><div class="django-event-calendar" id="c" data-django-event-calendar="c-config"><p class="django-event-calendar-status" hidden></p></div></div><script id="c-config" type="application/json">${json}</script>`;
}

async function load(readyState = "complete") {
    vi.spyOn(document, "readyState", "get").mockReturnValue(readyState);
    vi.resetModules();
    await import(`${SCRIPT}?${Math.random()}`);
    return window.djangoEventCalendar;
}

const options = () => created.at(-1).options;
const element = () => document.getElementById("c");
const status = () => element().querySelector(".django-event-calendar-status");

beforeEach(() => {
    created = [];
    window.EventCalendar = {
        create: vi.fn((target, opts) => {
            const calendar = { target, options: opts };
            created.push(calendar);
            return calendar;
        }),
    };
    window.matchMedia = vi.fn(() => ({ addEventListener: vi.fn() }));
});

afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.className = "";
    document.body.className = "";
    document.body.removeAttribute("style");
});

describe("calendar.js", () => {
    it("makes an EventCalendar from its configuration", async () => {
        page();
        await load();
        expect(window.EventCalendar.create).toHaveBeenCalledOnce();
        const calendar = created[0];
        expect(calendar.target.parentElement).toBe(element());
        expect(element().djangoEventCalendar).toBe(calendar);
        const o = options();
        expect(o.view).toBe("timeGridWeek");
        expect(o.headerToolbar).toEqual({
            start: "prev,next today",
            center: "title",
            end: "dayGridMonth,timeGridWeek",
        });
        expect(o.locale).toBe("es");
        expect(o.firstDay).toBe(1);
        expect(o.timeZone).toBe("+01:00");
        expect(o.eventSources).toEqual([
            { url: CONFIG.events, extraParams: CONFIG.params },
        ]);
        expect(o.slotMinTime).toBe("07:00");
        expect(o.buttonText({ today: "today", close: "Close" })).toEqual({
            ...TEXTS,
            close: "Close",
        });
        expect(o.allDayContent).toBe("All day");
        expect(o.noEventsContent).toBe("No events");
        expect(o.moreLinkContent({ num: 3 })).toBe("+3 more");
        expect(o.selectable).toBe(true);
        expect(o.editable).toBe(false); // Each event says.
    });

    it("opens an event's page", async () => {
        page();
        const api = await load();
        api.go = vi.fn();
        options().eventClick({ event: { extendedProps: { url: "/x/" } } });
        expect(api.go).toHaveBeenCalledWith("/x/");
        options().eventClick({ event: { extendedProps: {} } });
        options().eventClick({ event: {} });
        expect(api.go).toHaveBeenCalledOnce();
    });

    it("adds with the dates selected, or the one clicked", async () => {
        page();
        const api = await load();
        api.go = vi.fn();
        options().select({
            start: new Date("2026-10-28T09:30:00"),
            end: new Date("2026-10-28T11:00:00"),
            allDay: false,
        });
        expect(api.go).toHaveBeenLastCalledWith(
            `${CONFIG.add}?start=2026-10-28T09%3A30%3A00&end=2026-10-28T11%3A00%3A00`,
        );
        options().select({
            start: new Date("2026-10-28T00:00:00"),
            end: new Date("2026-10-30T00:00:00"),
            allDay: true,
        });
        expect(api.go).toHaveBeenLastCalledWith(
            `${CONFIG.add}?start=2026-10-28&end=2026-10-30`,
        );
        options().dateClick({
            date: new Date("2026-10-28T10:00:00"),
            allDay: false,
        });
        expect(api.go).toHaveBeenLastCalledWith(
            `${CONFIG.add}?start=2026-10-28T10%3A00%3A00`,
        );
    });

    it("a model's days are days, whatever the view", async () => {
        page({ ...CONFIG, datesOnly: true });
        const api = await load();
        api.go = vi.fn();
        options().dateClick({
            date: new Date("2026-10-28T10:00:00"),
            allDay: false,
        });
        expect(api.go).toHaveBeenLastCalledWith(
            `${CONFIG.add}?start=2026-10-28`,
        );
    });

    it("without adding nor moving", async () => {
        page({ ...CONFIG, add: null, move: null, views: [] });
        await load();
        const o = options();
        expect(o.selectable).toBe(false);
        expect(o.dateClick).toBeUndefined();
        expect(o.eventDrop).toBeUndefined();
        expect(o.eventResize).toBeUndefined();
        expect(o.headerToolbar.end).toBe("");
    });

    it("saves a move, with its CSRF token", async () => {
        const fetch = vi.fn(async () => ({ ok: true, json: async () => ({}) }));
        vi.stubGlobal("fetch", fetch);
        page();
        await load();
        const revert = vi.fn();
        await options().eventDrop({
            event: {
                id: "7",
                start: new Date("2026-10-28T15:00:00"),
                end: new Date("2026-10-28T16:30:00"),
                allDay: false,
            },
            revert,
        });
        const [url, init] = fetch.mock.calls[0];
        expect(url).toBe(CONFIG.move);
        expect(init.method).toBe("POST");
        expect(init.headers["X-CSRFToken"]).toBe("token");
        expect(String(init.body)).toBe(
            "pk=7&start=2026-10-28T15%3A00%3A00&end=2026-10-28T16%3A30%3A00",
        );
        expect(revert).not.toHaveBeenCalled();
        expect(status().hidden).toBe(true);
        // Without an end, or all day.
        await options().eventResize({
            event: {
                id: "8",
                start: new Date("2026-11-02T00:00:00"),
                end: null,
                allDay: true,
            },
            revert,
        });
        expect(String(fetch.mock.calls[1][1].body)).toBe(
            "pk=8&start=2026-11-02&end=",
        );
    });

    it("puts it back when it can't, and says why", async () => {
        vi.stubGlobal(
            "fetch",
            vi
                .fn()
                .mockResolvedValueOnce({
                    ok: false,
                    json: async () => ({
                        error: "It can't end before it starts.",
                    }),
                })
                .mockResolvedValueOnce({
                    ok: false,
                    json: async () => Promise.reject(),
                })
                .mockRejectedValueOnce(new Error("")),
        );
        page();
        await load();
        const event = {
            id: "7",
            start: new Date(),
            end: new Date(),
            allDay: false,
        };
        const revert = vi.fn();
        await options().eventDrop({ event, revert });
        expect(revert).toHaveBeenCalledOnce();
        expect(status().hidden).toBe(false);
        expect(status().textContent).toBe("It can't end before it starts.");
        await options().eventDrop({ event, revert });
        expect(status().textContent).toBe("Not saved");
        await options().eventDrop({ event, revert });
        expect(status().textContent).toBe("Not saved");
        expect(revert).toHaveBeenCalledTimes(3);
    });

    it("takes the CSRF token from its cookie, else", async () => {
        const fetch = vi.fn(async () => ({ ok: true }));
        vi.stubGlobal("fetch", fetch);
        // biome-ignore lint/suspicious/noDocumentCookie: what the script reads.
        document.cookie = "other=1";
        // biome-ignore lint/suspicious/noDocumentCookie: what the script reads.
        document.cookie = "csrftoken=from%20cookie";
        page({ ...CONFIG, csrfToken: "" });
        await load();
        await options().eventDrop({
            event: { id: "1", start: new Date(), end: null, allDay: false },
            revert: vi.fn(),
        });
        expect(fetch.mock.calls[0][1].headers["X-CSRFToken"]).toBe(
            "from cookie",
        );
        // biome-ignore lint/suspicious/noDocumentCookie: what the script reads.
        document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
        page({ ...CONFIG, csrfToken: "" });
        await load();
        await options().eventDrop({
            event: { id: "1", start: new Date(), end: null, allDay: false },
            revert: vi.fn(),
        });
        expect(fetch.mock.calls[1][1].headers["X-CSRFToken"]).toBe("");
    });

    it("works without its status element", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => ({ ok: true })),
        );
        page();
        status().remove();
        await load();
        await options().eventDrop({
            event: { id: "1", start: new Date(), end: null, allDay: false },
            revert: vi.fn(),
        });
    });

    it("does nothing without its configuration, its library, or twice", async () => {
        page(CONFIG, { raw: "{not json" });
        await load();
        expect(created).toHaveLength(0);
        document.getElementById("c-config").remove();
        window.djangoEventCalendar.setup();
        expect(created).toHaveLength(0);

        page();
        const saved = window.EventCalendar;
        window.EventCalendar = undefined;
        await load();
        expect(created).toHaveLength(0);
        window.EventCalendar = saved;
        const api = window.djangoEventCalendar;
        expect(api.setup()).toHaveLength(1);
        expect(api.setup()).toHaveLength(0); // Made already.
    });

    it("waits for the page when it's still loading", async () => {
        page();
        await load("loading");
        expect(created).toHaveLength(0);
        document.dispatchEvent(new Event("DOMContentLoaded"));
        expect(created).toHaveLength(1);
    });

    it("goes where it's told", async () => {
        page();
        const api = await load();
        const assign = vi.fn();
        vi.spyOn(window, "location", "get").mockReturnValue({ assign });
        api.go("/somewhere/");
        expect(assign).toHaveBeenCalledWith("/somewhere/");
    });
});

describe("its theme", () => {
    const classes = () =>
        [...element().classList].filter((c) => c.startsWith("ec-"));

    it("the admin's data-theme, or a dark/light class", async () => {
        document.documentElement.setAttribute("data-theme", "dark");
        page();
        await load();
        expect(classes()).toEqual(["ec-dark"]);
        page(CONFIG, { around: 'class="light"' });
        window.djangoEventCalendar.setup();
        expect(classes()).toEqual([]);
        page(CONFIG, { around: 'data-theme="light"' });
        window.djangoEventCalendar.setup();
        expect(classes()).toEqual([]);
        document.documentElement.removeAttribute("data-theme");
        page(CONFIG, { around: 'class="dark"' });
        window.djangoEventCalendar.setup();
        expect(classes()).toEqual(["ec-dark"]);
    });

    it("else the lightness of the background, else the system's", async () => {
        page(CONFIG, { around: 'style="background-color: rgb(20, 20, 20)"' });
        await load();
        expect(classes()).toEqual(["ec-dark"]);
        page(CONFIG, { around: 'style="background-color: rgba(0, 0, 0, 0)"' });
        window.djangoEventCalendar.setup();
        expect(classes()).toEqual(["ec-auto-dark"]);
        page(CONFIG, {
            around: 'style="background-color: rgb(250, 250, 250)"',
        });
        window.djangoEventCalendar.setup();
        expect(classes()).toEqual([]);
    });

    it("reads oklch backgrounds (Unfold's)", async () => {
        page();
        const api = await load();
        const wrap = document.getElementById("wrap");
        const style = vi.spyOn(window, "getComputedStyle");
        for (const [color, theme] of [
            ["oklch(21% 0.034 264.665)", "dark"],
            ["oklch(0.985 0.002 247.839)", "light"],
            ["oklch(21% 0.03 264 / 0)", null],
            ["oklch(21% 0.03 264 / 0.5)", "dark"],
            ["color(display-p3 1 1 1)", null],
        ]) {
            style.mockImplementation((node) => ({
                backgroundColor: node === wrap ? color : "rgba(0, 0, 0, 0)",
            }));
            expect(api.pageTheme(element())).toBe(theme);
        }
    });

    it("follows a theme switch", async () => {
        page();
        await load();
        expect(classes()).toEqual(["ec-auto-dark"]);
        document.documentElement.setAttribute("data-theme", "dark");
        await new Promise((resolve) => setTimeout(resolve));
        expect(classes()).toEqual(["ec-dark"]);
    });

    it("without matchMedia", async () => {
        window.matchMedia = undefined;
        page();
        await load();
        expect(created).toHaveLength(1);
    });
});
