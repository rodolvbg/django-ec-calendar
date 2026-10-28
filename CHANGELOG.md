# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
