# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `CalendarInline`: an object's calendar in its change page (the
  calendar of another model's objects related to it, its admin's), adding
  with the object filled in, and back to its page after a save.
- The names of the URL's parameters with the view and the date
  (`calendar_url_params`), the views' in it (`calendar_url_views`), and the
  return parameter's (`calendar_return_param`); `view_param` and
  `date_param` in the template tag.
- A date picker in the toolbar (`calendar_date_picker`, on by default;
  `date_picker` in the template tag), to go to a date.

- `CalendarView`: a calendar on your own pages with all the admin's does —
  moving (`"save"`, `"confirm"`, `"batch"`), adding with the dates,
  resources, business hours — by the user's model permissions (each
  overridable), saving with `obj.save()`. `urls(name)` gives its page and
  its endpoints; `calendar_for()`, its calendar for another page.
- `CalendarMixin`: what a calendar does wherever it is (the admin's and
  `CalendarView`'s), its hooks: `get_calendar_urls()`,
  `has_calendar_view_permission()`, `save_calendar_object()`,
  `log_calendar_move()`, `get_calendar_initial()`…
- `Calendar`: a calendar to show in any template (`{{ calendar.media }}`,
  `{{ calendar }}`); `get_calendar(request)` of a view.

### Changed

- After a save from the calendar, back to any of the admin's pages it was
  opened from (an inline's object's page too), not only the calendar's.
- `CalendarAdminMixin` is `CalendarMixin` with the admin's permissions,
  changelist, saves and log: the same options and methods as before.
- A detail `get_<field>_display` is labelled by its field.

### Fixed

- Opening the calendar leaves its page's URL as it is: its view and date
  are written only when one goes elsewhere.

- A move saved at once or after asking (`calendar_move_mode` `"save"`,
  `"confirm"`) leaves the event as the server says it is
  (`get_calendar_event()`: its color, title, details, URL, resources…), not
  as it was dropped, until the page was reloaded. The
  `django-ec-calendar:event-change` event has it too (`savedEvent`).

## [0.1.2] - 2026-10-29

### Added

- `calendar_move_mode` (and `get_calendar_move_mode(request)`): how a drag
  goes — `"off"`, `"save"` (at once), `"confirm"` (asked first) or
  `"batch"` (kept, several saved together in a transaction, or discarded;
  leaving with some asks). Its endpoint, `calendar/moves/`.
- `django-ec-calendar:move`, before a move, cancellable, with `save()`,
  `revert()` and `pend()` for the page's own way; and
  `django-ec-calendar:batch-change` after several are saved.
- `prepare_calendar_move()` and `save_calendar_move()`: a move checked, and
  saved, for your own views.

- Business hours: `calendar_business_hours` and
  `get_calendar_business_hours(request, resource=None)` (the calendar's,
  each resource's), `get_calendar_closed()` (holidays, days off), shaded as
  background events, with the time views fitted to them
  (`calendar_fit_hours`), and, with `calendar_outside_hours = "block"`, not
  to be selected, clicked nor moved to (checked by the server for moves;
  `is_calendar_open()`).
- A method for each option, taking the request: `get_calendar_view()`,
  `get_calendar_views()`, `get_calendar_options()`, `get_calendar_detail_fields()`,
  `get_calendar_confirm_move()`, `get_calendar_resource_editable()`,
  `get_calendar_filters()`, `get_calendar_url_state()`,
  `get_calendar_highlight_today()`; and `has_calendar_move_permission(request,
  obj=None)`, `has_calendar_add_permission(request)`, who may move each
  event and add from the calendar.

### Changed

- `calendar_move_mode` instead of `calendar_editable` and
  `calendar_confirm_move` (`calendar_editable = True` is
  `calendar_move_mode = "confirm"`; and without asking, `"save"`).
- `get_calendar_details(request, obj)` and
  `get_calendar_resource_empty_label(request)` take the request.

## [0.1.1] - 2026-10-29

### Added

- Resources: `calendar_resource_field` (a foreign key, as its
  `limit_choices_to` allows, a many-to-many field or a field with choices),
  with a resource for those without one, `resourceIds` for each event, the
  column's resource on the add page, and dragging to another resource
  saving it (`calendar_resource_editable`). `get_calendar_resources()` for
  others; `?resources=1` on an `EventFeedView`, `resources=True` in the
  template tag.
- `calendar_duration_field`: minutes or a `DurationField` instead of an end
  field, shown, resized and saved.
- `get_calendar_queryset(request)`: what the admin's calendar shows (the
  changelist's), to restrict the calendar only.
- `calendar_detail_fields`: more lines of text under an event's title, as
  `list_display`'s fields.
- The view and date in the calendar page's URL (`ec-view`, `ec-date`;
  `calendar_url_state`), and back to the calendar after a save from it.
- The changelist's filters and search on the calendar's page
  (`calendar_filters`), keeping its view and date.
- `django_ec_calendar.unfold`: Unfold's sidebar items of a list and its
  calendar, each active on its own page.
- A move asks first (`calendar_confirm_move`).
- `calendar_highlight_today`; today isn't tinted in a day's view.
- The translations of every view (resources and timelines included) and of
  EventCalendar's "previous"/"next".

### Changed

- Dragging is off by default (`calendar_editable = False`): a slip of the
  mouse would change an event.
- The configuration's texts are `texts.buttons` and `texts.labels`.

## [0.1.0] - 2026-10-29

### Added

- `CalendarAdminMixin`: a calendar of a changelist's objects (its queryset,
  filters and search), a "Calendar" link away. A click opens an object,
  selecting dates adds one with them, dragging one (or its end) saves its
  dates — checked by the model, saved through `save_model()` and logged.
  In Django's admin and in Unfold, following the page's theme.
- `CalendarSource`: objects as EventCalendar's events by their fields
  (`DateTimeField` or `DateField`, an end, all day, a title and a color),
  in the site's time zone whatever the browser's.
- `EventFeedView` and `{% ec_calendar %}`: a calendar on your own pages.
- EventCalendar 5.17.1 (vkurko, MIT), its standalone build, included.
- Events on the calendar's element, to do otherwise without changing its
  script: `django-ec-calendar:event-click`, `:date-click`, `:select`
  (cancellable) and `:event-change`.
- Spanish translation.
