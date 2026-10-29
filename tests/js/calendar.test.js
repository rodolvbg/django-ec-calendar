import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const SCRIPT =
    "../../src/django_ec_calendar/static/django_ec_calendar/calendar.js";

const TEXTS = {
    buttons: { today: "Today", timeGridWeek: "Week" },
    labels: { "Next week": "Semana siguiente" },
    confirmMove: "Save the new dates of “%(title)s”?",
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
    resources: null,
    resource: null,
    urlState: false,
    highlightToday: true,
    confirmMove: false,
    returnParam: null,
    texts: TEXTS,
    options: { slotMinTime: "07:00" },
};

let created;

function page(config = CONFIG, { around = "", raw = null } = {}) {
    const json = raw ?? JSON.stringify(config);
    document.body.innerHTML = `<div id="wrap" ${around}><div class="django-ec-calendar" id="c" data-django-ec-calendar="c-config"><p class="django-ec-calendar-status" hidden></p></div></div><script id="c-config" type="application/json">${json}</script>`;
}

async function load(readyState = "complete") {
    vi.spyOn(document, "readyState", "get").mockReturnValue(readyState);
    vi.resetModules();
    await import(`${SCRIPT}?${Math.random()}`);
    return window.djangoEcCalendar;
}

const options = () => created.at(-1).options;
const element = () => document.getElementById("c");
const status = () => element().querySelector(".django-ec-calendar-status");

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
        expect(element().djangoEcCalendar).toBe(calendar);
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
        expect(
            o.buttonText({
                today: "today",
                close: "Close",
                prev: "Previous week",
                next: "Next week",
            }),
        ).toEqual({
            today: "Today",
            timeGridWeek: "Week",
            close: "Close",
            prev: "Previous week", // Not translated: as it was.
            next: "Semana siguiente",
        });
        expect(o.resources).toBeUndefined();
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
        // Nothing to add: only its events fire.
        const api = window.djangoEcCalendar;
        api.go = vi.fn();
        const clicked = vi.fn();
        element().addEventListener("django-ec-calendar:date-click", clicked);
        o.dateClick({ date: new Date("2026-10-28T10:00:00"), allDay: false });
        o.select({
            start: new Date("2026-10-28T10:00:00"),
            end: new Date("2026-10-28T11:00:00"),
            allDay: false,
        });
        expect(clicked).toHaveBeenCalledOnce();
        expect(api.go).not.toHaveBeenCalled();
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
        window.djangoEcCalendar.setup();
        expect(created).toHaveLength(0);

        page();
        const saved = window.EventCalendar;
        window.EventCalendar = undefined;
        await load();
        expect(created).toHaveLength(0);
        window.EventCalendar = saved;
        const api = window.djangoEcCalendar;
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

describe("its events", () => {
    const listeners = [];

    afterEach(() => {
        for (const args of listeners.splice(0)) {
            document.removeEventListener(...args);
        }
    });

    function listen(name, cancel = false) {
        const heard = [];
        const listener = (event) => {
            heard.push(event);
            if (cancel) event.preventDefault();
        };
        const type = `django-ec-calendar:${name}`;
        document.addEventListener(type, listener);
        listeners.push([type, listener]);
        return heard;
    }

    it("tells of a click on an event, and lets it be done otherwise", async () => {
        page();
        const api = await load();
        api.go = vi.fn();
        const heard = listen("event-click", true);
        const event = { extendedProps: { url: "/x/" } };
        options().eventClick({ event, jsEvent: "click" });
        expect(heard).toHaveLength(1);
        expect(heard[0].target).toBe(element()); // Bubbled to the document.
        expect(heard[0].detail).toEqual({
            event,
            url: "/x/",
            jsEvent: "click",
        });
        expect(api.go).not.toHaveBeenCalled();
        options().eventClick({ event: {} });
        expect(heard[1].detail.url).toBe(null);
    });

    it("tells of a click on a date, or a selection, with the server's dates", async () => {
        page();
        const api = await load();
        api.go = vi.fn();
        const clicks = listen("date-click", true);
        const selections = listen("select", true);
        options().dateClick({
            date: new Date("2026-10-28T09:00:00"),
            allDay: false,
        });
        expect(clicks[0].detail).toEqual({
            start: "2026-10-28T09:00:00",
            allDay: false,
            resource: null,
            jsEvent: undefined,
        });
        options().select({
            start: new Date("2026-10-28T00:00:00"),
            end: new Date("2026-10-30T00:00:00"),
            allDay: true,
        });
        expect(selections[0].detail).toEqual({
            start: "2026-10-28",
            end: "2026-10-30",
            allDay: true,
            resource: null,
            jsEvent: undefined,
        });
        expect(api.go).not.toHaveBeenCalled(); // Both cancelled.
    });

    it("tells whether a move was saved", async () => {
        vi.stubGlobal(
            "fetch",
            vi
                .fn()
                .mockResolvedValueOnce({ ok: true })
                .mockResolvedValueOnce({
                    ok: false,
                    json: async () => ({ error: "No." }),
                }),
        );
        page();
        await load();
        const heard = listen("event-change");
        const event = { id: "1", start: new Date(), end: null, allDay: false };
        await options().eventDrop({ event, revert: vi.fn() });
        await options().eventDrop({ event, revert: vi.fn() });
        expect(heard.map((e) => e.detail)).toEqual([
            { event, saved: true, error: "" },
            { event, saved: false, error: "No." },
        ]);
        expect(heard[0].cancelable).toBe(false);
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
        window.djangoEcCalendar.setup();
        expect(classes()).toEqual([]);
        page(CONFIG, { around: 'data-theme="light"' });
        window.djangoEcCalendar.setup();
        expect(classes()).toEqual([]);
        document.documentElement.removeAttribute("data-theme");
        page(CONFIG, { around: 'class="dark"' });
        window.djangoEcCalendar.setup();
        expect(classes()).toEqual(["ec-dark"]);
    });

    it("else the lightness of the background, else the system's", async () => {
        page(CONFIG, { around: 'style="background-color: rgb(20, 20, 20)"' });
        await load();
        expect(classes()).toEqual(["ec-dark"]);
        page(CONFIG, { around: 'style="background-color: rgba(0, 0, 0, 0)"' });
        window.djangoEcCalendar.setup();
        expect(classes()).toEqual(["ec-auto-dark"]);
        page(CONFIG, {
            around: 'style="background-color: rgb(250, 250, 250)"',
        });
        window.djangoEcCalendar.setup();
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

describe("its place in the page's URL", () => {
    afterEach(() => window.history.replaceState(null, "", "/"));

    it("opens where the URL says, and keeps it there", async () => {
        window.history.replaceState(
            null,
            "",
            "/calendar/?room=1&ec-view=dayGridMonth&ec-date=2026-11-02",
        );
        page({ ...CONFIG, urlState: true });
        await load();
        expect(options().view).toBe("dayGridMonth");
        expect(options().date).toBe("2026-11-02");
        options().datesSet({
            view: {
                type: "timeGridWeek",
                currentStart: new Date("2026-11-09T00:00:00"),
            },
        });
        expect(window.location.search).toBe(
            "?room=1&ec-view=timeGridWeek&ec-date=2026-11-09",
        );
        expect(element().dataset.view).toBe("timeGridWeek");
    });

    it("not a view or a date it doesn't know", async () => {
        window.history.replaceState(
            null,
            "",
            "/calendar/?ec-view=resourceTimelineYear&ec-date=soon",
        );
        page({ ...CONFIG, urlState: true });
        await load();
        expect(options().view).toBe("timeGridWeek");
        expect(options().date).toBeUndefined();
        window.history.replaceState(null, "", "/calendar/");
        page({ ...CONFIG, urlState: true });
        window.djangoEcCalendar.setup();
        expect(options().date).toBeUndefined();
    });

    it("not without urlState", async () => {
        window.history.replaceState(
            null,
            "",
            "/calendar/?ec-view=dayGridMonth",
        );
        page();
        await load();
        expect(options().view).toBe("timeGridWeek");
        options().datesSet({
            view: { type: "timeGridDay", currentStart: new Date() },
        });
        expect(window.location.search).toBe("?ec-view=dayGridMonth");
        expect(element().dataset.view).toBe("timeGridDay"); // For its CSS.
    });

    it("its filters' links and forms keep it", async () => {
        window.history.replaceState(
            null,
            "",
            "/calendar/?ec-view=dayGridMonth&ec-date=2026-11-02",
        );
        page();
        await load();
        const keep = document.createElement("div");
        keep.setAttribute("data-django-ec-calendar-keep-state", "");
        keep.innerHTML =
            '<a id="here" href="/calendar/?room=2">Blue</a>' +
            '<a id="away" href="/elsewhere/?room=2">Away</a>' +
            '<form id="search" method="get" action=""><input name="q" value="x"></form>' +
            '<form id="posted" method="post"></form>';
        document.body.append(keep);
        const stop = (event) => event.preventDefault();
        document.addEventListener("click", stop);
        document.addEventListener("submit", stop);
        document.getElementById("here").click();
        document.getElementById("away").click();
        expect(document.getElementById("here").getAttribute("href")).toBe(
            `${window.location.origin}/calendar/?room=2&ec-view=dayGridMonth&ec-date=2026-11-02`,
        );
        expect(document.getElementById("away").getAttribute("href")).toBe(
            "/elsewhere/?room=2",
        );
        const search = document.getElementById("search");
        search.dispatchEvent(
            new Event("submit", { bubbles: true, cancelable: true }),
        );
        expect(
            [...search.querySelectorAll("input")].map((i) => [i.name, i.value]),
        ).toEqual([
            ["q", "x"],
            ["ec-view", "dayGridMonth"],
            ["ec-date", "2026-11-02"],
        ]);
        // Twice: not again.
        search.dispatchEvent(
            new Event("submit", { bubbles: true, cancelable: true }),
        );
        expect(search.querySelectorAll("input")).toHaveLength(3);
        const posted = document.getElementById("posted");
        posted.dispatchEvent(
            new Event("submit", { bubbles: true, cancelable: true }),
        );
        expect(posted.querySelectorAll("input")).toHaveLength(0);
        // Elsewhere on the page: as they are.
        const other = document.createElement("a");
        other.href = "/calendar/?room=3";
        document.body.append(other);
        other.click();
        expect(other.getAttribute("href")).toBe("/calendar/?room=3");
        window.history.replaceState(null, "", "/calendar/");
        document.getElementById("here").click(); // Nothing to keep.
        document.removeEventListener("click", stop);
        document.removeEventListener("submit", stop);
    });

    it("takes the calendar's URL to the pages it opens", async () => {
        window.history.replaceState(
            null,
            "",
            "/calendar/?ec-view=dayGridMonth",
        );
        page({ ...CONFIG, returnParam: "_ec_calendar" });
        const api = await load();
        api.go = vi.fn();
        options().eventClick({
            event: { extendedProps: { url: "/x/1/?a=b" } },
        });
        expect(api.go).toHaveBeenLastCalledWith(
            "/x/1/?a=b&_ec_calendar=%2Fcalendar%2F%3Fec-view%3DdayGridMonth",
        );
        options().dateClick({
            date: new Date("2026-10-28T10:00:00"),
            allDay: false,
        });
        expect(api.go.mock.calls.at(-1)[0]).toContain(
            "&_ec_calendar=%2Fcalendar%2F",
        );
        // Another site's page: as it is.
        options().eventClick({
            event: { extendedProps: { url: "https://elsewhere.example/x/" } },
        });
        expect(api.go).toHaveBeenLastCalledWith("https://elsewhere.example/x/");
    });
});

describe("its resources", () => {
    const RESOURCES = {
        ...CONFIG,
        resources: [
            { id: "1", title: "Ana" },
            { id: "__none__", title: "No professional" },
        ],
        resource: {
            param: "professional",
            empty: "__none__",
            editable: true,
            message: "It can't be moved to another professional.",
        },
    };

    it("as EventCalendar's, and the add page in its column", async () => {
        page(RESOURCES);
        const api = await load();
        api.go = vi.fn();
        expect(options().resources).toEqual(RESOURCES.resources);
        const clicks = [];
        element().addEventListener("django-ec-calendar:date-click", (e) =>
            clicks.push(e.detail.resource),
        );
        const date = new Date("2026-10-28T10:00:00");
        options().dateClick({ date, allDay: false, resource: { id: 1 } });
        expect(api.go).toHaveBeenLastCalledWith(
            `${CONFIG.add}?start=2026-10-28T10%3A00%3A00&professional=1`,
        );
        options().dateClick({
            date,
            allDay: false,
            resource: { id: "__none__" },
        });
        expect(api.go).toHaveBeenLastCalledWith(
            `${CONFIG.add}?start=2026-10-28T10%3A00%3A00`,
        );
        options().select({
            start: date,
            end: new Date("2026-10-28T11:00:00"),
            allDay: false,
            resource: { id: "1" },
        });
        expect(api.go.mock.calls.at(-1)[0]).toContain("&professional=1");
        expect(clicks).toEqual(["1", null]);
    });

    it("from where it's fetched", async () => {
        page({ ...CONFIG, resources: { url: "/events/?resources=1" } });
        await load();
        expect(options().resources).toEqual({ url: "/events/?resources=1" });
    });

    it("saves a move to another", async () => {
        const fetch = vi.fn(async () => ({ ok: true }));
        vi.stubGlobal("fetch", fetch);
        page(RESOURCES);
        await load();
        const event = { id: "7", start: new Date(), end: null, allDay: false };
        await options().eventDrop({
            event,
            revert: vi.fn(),
            oldResource: { id: "__none__" },
            newResource: { id: 1 },
        });
        const body = new URLSearchParams(fetch.mock.calls[0][1].body);
        expect(body.get("resource")).toBe("1");
        expect(body.get("resource_from")).toBe("__none__");
        await options().eventDrop({
            event,
            revert: vi.fn(),
            newResource: { id: "1" },
        });
        expect(
            new URLSearchParams(fetch.mock.calls[1][1].body).get(
                "resource_from",
            ),
        ).toBe("");
    });

    it("puts it back where it may not change", async () => {
        const fetch = vi.fn();
        vi.stubGlobal("fetch", fetch);
        page({
            ...RESOURCES,
            resource: { ...RESOURCES.resource, editable: false },
        });
        await load();
        const revert = vi.fn();
        await options().eventDrop({
            event: { id: "7", start: new Date(), end: null, allDay: false },
            revert,
            newResource: { id: "1" },
        });
        expect(revert).toHaveBeenCalledOnce();
        expect(fetch).not.toHaveBeenCalled();
        expect(status().textContent).toBe(
            "It can't be moved to another professional.",
        );
    });

    it("without its configuration, says it can't", async () => {
        vi.stubGlobal("fetch", vi.fn());
        page();
        await load();
        const revert = vi.fn();
        await options().eventDrop({
            event: { id: "7", start: new Date(), end: null, allDay: false },
            revert,
            newResource: { id: "1" },
        });
        expect(revert).toHaveBeenCalledOnce();
        expect(status().textContent).toBe("Not saved");
    });
});

describe("a move, asked first", () => {
    it("saved when one says yes, put back when no", async () => {
        const fetch = vi.fn(async () => ({ ok: true }));
        vi.stubGlobal("fetch", fetch);
        const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false);
        page({ ...CONFIG, confirmMove: true });
        await load();
        const changes = [];
        element().addEventListener("django-ec-calendar:event-change", (e) =>
            changes.push(e.detail),
        );
        const event = {
            id: "7",
            title: "Call",
            start: new Date(),
            end: null,
            allDay: false,
        };
        const revert = vi.fn();
        await options().eventDrop({ event, revert });
        expect(confirm).toHaveBeenCalledWith("Save the new dates of “Call”?");
        expect(revert).toHaveBeenCalledOnce();
        expect(fetch).not.toHaveBeenCalled();
        expect(status().hidden).toBe(true);
        expect(changes).toEqual([{ event, saved: false, error: "" }]);
        confirm.mockReturnValueOnce(true);
        await options().eventDrop({ event, revert });
        expect(fetch).toHaveBeenCalledOnce();
    });
});

describe("its details", () => {
    function info(type, details) {
        return {
            event: { title: "María", extendedProps: { details } },
            timeText: "9:00 – 9:45",
            view: { type },
        };
    }

    it("under its title, as text", async () => {
        page();
        await load();
        const details = [{ label: "Status", value: "<b>Booked</b>" }];
        const { domNodes } = options().eventContent(
            info("timeGridDay", details),
        );
        expect(
            domNodes.map((n) => [n.tagName, n.className, n.textContent]),
        ).toEqual([
            ["TIME", "ec-event-time", "9:00 – 9:45"],
            ["H4", "ec-event-title", "María"],
            ["SPAN", "django-ec-calendar-detail", "<b>Booked</b>"],
        ]);
        expect(domNodes[2].title).toBe("Status");
        // In a list: no time (it has its own column), labelled.
        const listed = options().eventContent(
            info("listWeek", details),
        ).domNodes;
        expect(listed.map((n) => n.textContent)).toEqual([
            "María",
            "Status: <b>Booked</b>",
        ]);
        // No time (all day).
        const allDay = info("dayGridMonth", details);
        allDay.timeText = "";
        expect(options().eventContent(allDay).domNodes).toHaveLength(2);
    });

    it("without any, as EventCalendar shows it", async () => {
        page();
        await load();
        expect(options().eventContent(info("timeGridDay", []))).toBeUndefined();
        expect(
            options().eventContent({ event: { extendedProps: {} }, view: {} }),
        ).toBeUndefined();
    });
});

describe("today", () => {
    it("tinted, unless it's off", async () => {
        page();
        await load();
        expect(
            element().classList.contains("django-ec-calendar--no-today"),
        ).toBe(false);
        page({ ...CONFIG, highlightToday: false });
        window.djangoEcCalendar.setup();
        expect(
            element().classList.contains("django-ec-calendar--no-today"),
        ).toBe(true);
    });
});
