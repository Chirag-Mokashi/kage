"""Calendar write backend for kage using macOS EventKit.

This module provides the `EventKitBackend` class for creating macOS calendar events
via the EventKit framework (pyobjc). It is designed to be used only on macOS and
should not be imported on non-macOS platforms.

The class supports creating calendar events with a title, start and end time (in
ISO-8601 format), and an optional calendar name. If no calendar name is provided,
the default calendar for new events is used.

Note: This module uses lazy imports for EventKit and Foundation to avoid
platform-specific import errors on non-macOS systems.
"""
from __future__ import annotations
from datetime import datetime


class EventKitBackend:
    def __init__(self):
        pass

    def create(self, *, title: str, start: str, end: str, calendar_name: str | None = None) -> str:
        import EventKit as EK
        from Foundation import NSDate

        store = EK.EKEventStore.alloc().init()

        cal = None
        if calendar_name:
            for c in (store.calendarsForEntityType_(EK.EKEntityTypeEvent) or []):
                if c.title() == calendar_name:
                    cal = c
                    break
        if cal is None:
            cal = store.defaultCalendarForNewEvents()
        if cal is None:
            raise RuntimeError("no calendar available for new events")

        ev = EK.EKEvent.eventWithEventStore_(store)
        ev.setTitle_(title)
        ev.setStartDate_(NSDate.dateWithTimeIntervalSince1970_(datetime.fromisoformat(start).timestamp()))
        ev.setEndDate_(NSDate.dateWithTimeIntervalSince1970_(datetime.fromisoformat(end).timestamp()))
        ev.setCalendar_(cal)

        ok, err = store.saveEvent_span_error_(ev, EK.EKSpanThisEvent, None)
        if not ok:
            raise RuntimeError(f"calendar save failed: {err}")
        return ev.eventIdentifier()
