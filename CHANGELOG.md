# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
