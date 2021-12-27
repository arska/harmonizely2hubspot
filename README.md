= Harmonizely.com meeting to HubSpot CRM

This application listens for Harmonizely.com "Zapier Webhooks" and creates HubSpot Contacts, Deals and Meetings.

The env variable HUBSPOT_ACCESS_TOKENS is a JSON dictionary with the HubSpot users email address as key and the [HubSpot private App token](https://developers.hubspot.com/docs/api/private-apps) (with Contacts (read/write), Deals (read/write) and Owners (read) privileges).

Example: HUBSPOT_ACCESS_TOKENS='{"test@example.com":"pat-xx-xxxxxxxx-xxxx-xxxx..."}'

The application listens by default on tcp port 8080 and answers any requests to / with "OK" (e.g. for liveness probes). The webhook requests need to be sent to /test@example.com, based on which the access token is chosen from the config.
