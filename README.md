# Harmonizely.com meeting to HubSpot CRM

This application listens for [Harmonizely.com](https://harmonizely.com/?fpr=aarno62) "Zapier Webhooks" and creates [HubSpot](https://hubspot.com) Contacts, Deals and Meetings.

The env variable HUBSPOT_ACCESS_TOKEN contains the [HubSpot private App token](https://developers.hubspot.com/docs/api/private-apps) (with Contacts (read/write), Deals (read/write) and Owners (read) privileges) and HUBSPOT_USERS a comma-delimited list of HubSpot users email addresses that will be the owners of the objects created.

Example:
HUBSPOT_ACCESS_TOKEN="pat-xx-xxxxxxxx-xxxx-xxxx..."
HUBSPOT_USERS="user1@example.com,user2@example.com"

The application listens by default on tcp port 8080 and answers any requests to / with "OK" (e.g. for liveness probes). The webhook requests need to be sent to /user1@example.com

This is an example JSON payload I used to test the integration using [YARC](https://chrome.google.com/webstore/detail/yet-another-rest-client/ehafadccdcdedbhcbddihehiodgcddpl?hl=en):

```
{"answers": [], "canceled_at": null, "cancellation": null, "details": null, "end_date": "2022-02-18T07:45:00+00:00", "event_type": {"confirmation_page_type": "internal", "confirmation_page_url": null, "description": null, "duration": 45, "is_secret": false, "location": null, "location_label": null, "name": "60 min", "notification_type": "calendar", "pass_details_to_redirected_page": false, "position": 1, "slug": "60", "type": "regular"}, "invitee": {"email": "aarno.aukia@vshn.ch", "first_name": "Aarno", "full_name": "Aarno Aukia", "locale": "en", "phone_number": null, "timezone": "Europe/Zurich"}, "location": "https://vshn.zoom.us/j/1234567890", "notes": null, "payment": null, "pretty_canceled_at": null, "pretty_canceled_at_in_invitee_timezone": null, "pretty_scheduled_at": "Friday, February 18, 2022 08:00", "pretty_scheduled_at_in_invitee_timezone": "Friday, February 18, 2022 at 8:00 AM", "rescheduling": null, "scheduled_at": "2022-02-18T07:00:00+00:00", "state": "new", "uuid": "12345678-1234-1234-1234-12345678"}
```
