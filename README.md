# Harmonizely.com meeting to HubSpot CRM

This application listens for [Harmonizely.com](https://harmonizely.com/?fpr=aarno62) "Zapier Webhooks" and creates [HubSpot](https://hubspot.com) Contacts, Deals and Meetings.

The env variable HUBSPOT_ACCESS_TOKENS is a JSON dictionary with the HubSpot users email address as key and the [HubSpot private App token](https://developers.hubspot.com/docs/api/private-apps) (with Contacts (read/write), Deals (read/write) and Owners (read) privileges).

Example: HUBSPOT_ACCESS_TOKENS='{"test@example.com":"pat-xx-xxxxxxxx-xxxx-xxxx..."}'

The application listens by default on tcp port 8080 and answers any requests to / with "OK" (e.g. for liveness probes). The webhook requests need to be sent to /test@example.com, based on which the access token is chosen from the config.

This is an example JSON payload I used to test the integration using [YARC](https://chrome.google.com/webstore/detail/yet-another-rest-client/ehafadccdcdedbhcbddihehiodgcddpl?hl=en):

```
{"rescheduling":null,"pretty_canceled_at":null,"pretty_scheduled_at":"Thursday, February 10, 2022 14:00","pretty_scheduled_at_in_invitee_timezone":"Thursday, February 10, 2022 at 2:00 PM","pretty_canceled_at_in_invitee_timezone":null,"event_type":{"name":"APPUiO & Exoscale","location":null,"location_label":null,"description":null,"duration":45,"slug":"exo","is_secret":false,"confirmation_page_type":"internal","confirmation_page_url":null,"notification_type":"calendar","pass_details_to_redirected_page":false,"type":"regular","position":0},"scheduled_at":"2022-02-10T13:00:00+00:00","end_date":"2022-02-10T13:45:00+00:00","invitee":{"first_name":"Aarno","email":"aarno.aukia+test1@vshn.ch","full_name":"Aarno Aukia","timezone":"Europe/Zurich","phone_number":"+41445455300","locale":"en"},"state":"new","canceled_at":null,"uuid":"12345678-1234-1234-1234-12345678","notes":null,"details":null,"answers":[],"location":"https://vshn.zoom.us/j/1234567890","cancellation":null,"payment":null}
```
