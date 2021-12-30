"""
Harmonizely.com meeting to HubSpot CRM
"""

import argparse
import datetime
import json
import logging
import os
import pprint

import dotenv
import flask
import hubspot
import nameparser
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from hubspot.crm.associations import BatchInputPublicAssociation
from hubspot.crm.contacts import ApiException, SimplePublicObjectInput

LOGFORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
CONFIG = ""  #  will be loaded in main()
APP = flask.Flask(__name__)  # Standard Flask app


def main(args):
    """
    main function
    """
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format=LOGFORMAT)
    else:
        logging.basicConfig(level=logging.INFO, format=LOGFORMAT)

    logging.debug("starting with arguments %s", args)
    dotenv.load_dotenv()
    global CONFIG  # pylint: disable=global-statement
    CONFIG = json.loads(os.environ.get("HUBSPOT_ACCESS_TOKENS"))
    logging.info(
        "loaded HUBSPOT_ACCESS_TOKENS with emails and hubspot access tokens: %s",
        pprint.pformat(CONFIG),
    )

    APP.run(host="0.0.0.0", port=os.environ.get("listenport", 8080))


def parse_arguments():
    """Parse arguments from command line"""
    parser = argparse.ArgumentParser(
        description="sync harmonizely.com meeting requests with Hubspot CRM"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="set logging level debug",
        action="store_true",
        default=False,
    )
    args_parser = parser.parse_args()
    return args_parser


@APP.route("/")
def healthcheck():
    """
    healthcheck OK on root path
    """
    return "OK"


@APP.errorhandler(404)
def resource_not_found(error):
    """
    add json error message used with flask.abort()
    """
    return flask.jsonify(error=str(error)), 404


@APP.errorhandler(500)
def internal_error(error):
    """
    add json error message used with flask.abort()
    """
    return flask.jsonify(error=str(error)), 500


@APP.route("/<path>", methods=["POST"])
def webhook(path):
    """
    Process webhook POST from Harmonizely
    """

    if path not in CONFIG:
        flask.abort(404, description="Resource not found")

    payload = flask.request.json
    logging.info("got new request with payload:\n%s", pprint.pformat(payload))

    # make an educated guess about the first and last name from full_name
    parsed_name = nameparser.HumanName(payload["invitee"]["full_name"])
    first_name = parsed_name.first.strip()
    if parsed_name.middle:
        first_name += " " + parsed_name.middle.strip()
    logging.debug("parsed first name: %s", first_name)
    last_name = parsed_name.last.strip()
    logging.debug("parsed last name: %s", last_name)

    api_client = hubspot.HubSpot(access_token=CONFIG[path])

    owner = get_owner_id(email=path, api_client=api_client)

    contact = search_contact(payload["invitee"]["email"], api_client=api_client)

    # create contact
    if contact is None:
        # contact does not exist yet
        try:
            contact = api_client.crm.contacts.basic_api.create(
                simple_public_object_input=SimplePublicObjectInput(
                    properties={
                        "email": payload["invitee"]["email"],
                        "firstname": first_name,
                        "lastname": last_name,
                        "phone": payload["invitee"]["phone_number"],
                        "hubspot_owner_id": owner,
                    }
                )
            )
            logging.debug("new contact created, searching again")
            # search again to get all the associations
            contact = search_contact(payload["invitee"]["email"], api_client=api_client)
        except ApiException as error:
            logging.error("Exception when creating contact: %s\n", error)
            flask.abort(500, description=error)

    #  create new deal if the contact has no deals at all
    if not contact.associations or not contact.associations.get("deals", False):
        try:
            # https://developers.hubspot.com/docs/api/crm/deals
            properties = {
                "amount": "",
                "closedate": payload["scheduled_at"].replace("+00:00", "Z"),
                "dealname": "Meeting "
                + first_name
                + " "
                + last_name
                + ": "
                + payload["event_type"]["name"],
                "dealstage": 1159035,
                "hubspot_owner_id": owner,
                "pipeline": "default",
            }
            newdeal = api_client.crm.deals.basic_api.create(
                simple_public_object_input=SimplePublicObjectInput(
                    properties=properties
                )
            )
            logging.debug("created deal:\n%s", pprint.pformat(newdeal))
        except ApiException as error:
            logging.error("Exception when creating deal: %s\n", error)
            flask.abort(500, description=error)

        # add new deal to contact

        associate_contact_to_deal(
            contact_id=contact.id, deal_id=newdeal.id, api_client=api_client
        )

        if contact.associations and contact.associations.get("companies", False):
            # if the contact has a company associate the meeting with it

            associate_company_to_deal(
                company_id=contact.associations["companies"].results[0].id,
                deal_id=newdeal.id,
                api_client=api_client,
            )

    # get meetings for contact
    """
    try:
        api_response = api_client.crm.associations.batch_api.read(
            from_object_type="Contacts",
            to_object_type="Meetings",
            batch_input_public_object_id=BatchInputPublicObjectId(inputs=[{"id": contact.id}]),
        )
        logging.debug(pprint.pformat(api_response))
    except ApiException as error:
        logging.debug("Exception when calling batch_api->read: %s\n", error)
"""

    # create meeting
    try:
        # https://developers.hubspot.com/docs/api/crm/meetings
        properties = {
            "hs_timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "hubspot_owner_id": owner,
            "hs_meeting_title": payload["event_type"]["name"],
            "hs_meeting_body": "Harmonizely meeting: " + payload["location"],
            "hs_internal_meeting_notes": "These are the meeting notes",
            "hs_meeting_external_url": payload["location"],
            "hs_meeting_location": "Remote",
            "hs_meeting_start_time": payload["scheduled_at"].replace("+00:00", "Z"),
            "hs_meeting_end_time": payload["end_date"].replace("+00:00", "Z"),
            "hs_meeting_outcome": "SCHEDULED",
        }

        meeting = api_client.crm.objects.basic_api.create(
            "Meetings",
            simple_public_object_input=SimplePublicObjectInput(properties=properties),
        )
        logging.debug("new meeting:\n%s", pprint.pformat(meeting))
    except ApiException as error:
        logging.error("Exception when creating meeting: %s\n", error)
        flask.abort(500, description=error)

    # associate new meeting with the contact

    associate_contact_to_meeting(
        contact_id=contact.id, meeting_id=meeting.id, api_client=api_client
    )

    if contact.associations and contact.associations.get("companies", False):
        # if the contact has a company associate the meeting with it

        associate_company_to_meeting(
            company_id=contact.associations["companies"].results[0].id,
            meeting_id=meeting.id,
            api_client=api_client,
        )

    #  either the contact has existing deals or we just created one above
    if contact.associations and contact.associations.get("deals", False):
        newdeal = contact.associations["deals"].results[0]

    # if the contact has a deal associate the meeting with it
    associate_deal_to_meeting(
        deal_id=newdeal.id, meeting_id=meeting.id, api_client=api_client
    )

    return "OK"


def associate_contact_to_deal(contact_id, deal_id, api_client):
    """
    Create a bi-directional HubSpot association between a contact and a deal
    """
    try:
        association = api_client.crm.associations.batch_api.create(
            from_object_type="Contact",
            to_object_type="Deal",
            batch_input_public_association=BatchInputPublicAssociation(
                inputs=[
                    {
                        "from": {"id": contact_id},
                        "to": {"id": deal_id},
                        "type": "contact_to_deal",
                    }
                ]
            ),
        )
        logging.debug("associate deal with contact:\n%s", pprint.pformat(association))
    except ApiException as error:
        logging.error("Exception when associate deal with contact: %s\n", error)
        flask.abort(500, description=error)


def associate_company_to_deal(company_id, deal_id, api_client):
    """
    Create a bi-directional HubSpot association between a company and a deal
    """

    logging.debug("adding deal to company association")
    try:
        association = api_client.crm.associations.batch_api.create(
            from_object_type="Companies",
            to_object_type="Deal",
            batch_input_public_association=BatchInputPublicAssociation(
                inputs=[
                    {
                        "from": {"id": company_id},
                        "to": {"id": deal_id},
                        "type": "company_to_deal",
                    }
                ]
            ),
        )
        logging.debug("associate deal with company:\n%s", pprint.pformat(association))
    except ApiException as error:
        logging.error("Exception when associate deal with company: %s\n", error)
        flask.abort(500, description=error)


def associate_contact_to_meeting(contact_id, meeting_id, api_client):
    """
    Create a bi-directional HubSpot association between a contact and a meeting
    """
    logging.debug("associate meeting with contact")
    try:
        association = api_client.crm.associations.batch_api.create(
            from_object_type="Contact",
            to_object_type="Meeting",
            batch_input_public_association=BatchInputPublicAssociation(
                inputs=[
                    {
                        "from": {"id": contact_id},
                        "to": {"id": meeting_id},
                        "type": "contact_to_meeting_event",
                    }
                ]
            ),
        )
        logging.debug(
            "associate meeting with contact:\n%s", pprint.pformat(association)
        )
    except ApiException as error:
        logging.error("Exception when associate meeting with contact: %s\n", error)
        flask.abort(500, description=error)


def associate_company_to_meeting(company_id, meeting_id, api_client):
    """
    Create a bi-directional HubSpot association between a company and a meeting
    """
    logging.debug("adding company association")
    try:
        association = api_client.crm.associations.batch_api.create(
            from_object_type="Companies",
            to_object_type="Meeting",
            batch_input_public_association=BatchInputPublicAssociation(
                inputs=[
                    {
                        "from": {"id": company_id},
                        "to": {"id": meeting_id},
                        "type": "company_to_meeting_event",
                    }
                ]
            ),
        )
        logging.debug(
            "associate meeting with company:\n%s", pprint.pformat(association)
        )
    except ApiException as error:
        logging.error("Exception when associate meeting with company: %s\n", error)
        flask.abort(500, description=error)


def associate_deal_to_meeting(deal_id, meeting_id, api_client):
    """
    Create a bi-directional HubSpot association between a deal and a meeting
    """
    logging.debug("adding deal association")
    try:
        association = api_client.crm.associations.batch_api.create(
            from_object_type="Deals",
            to_object_type="Meeting",
            batch_input_public_association=BatchInputPublicAssociation(
                inputs=[
                    {
                        "from": {"id": deal_id},
                        "to": {"id": meeting_id},
                        "type": "deal_to_meeting_event",
                    }
                ]
            ),
        )
        logging.debug("associate meeting with deal:\n%s", pprint.pformat(association))
    except ApiException as error:
        logging.error("Exception when associate meeting with deal: %s\n", error)
        flask.abort(500, description=error)


def get_owner_id(email, api_client):
    """
    Get the Hubspot user ID for an email
    """
    try:
        owners = api_client.crm.owners.get_all()
        owner = [o.id for o in owners if o.email == email][0]
    except hubspot.crm.owners.exceptions.ApiException as error:
        logging.error("loading owner ID failed, problem with API key?")
        flask.abort(500, description=error)
    return owner


def search_contact(email, api_client):
    """
    Search for a contact using the email
    :param email: email to search for (does not need to be primary)
    :return: dict of contact or None if not found
    """
    try:
        contact = api_client.crm.contacts.basic_api.get_by_id(
            email,
            id_property="email",
            associations=["Meetings", "Deals", "Companies"],
            properties=["email", "firstname", "lastname"],
        )
        logging.debug("email %s found:\n%s", email, pprint.pformat(contact))
        return contact
    except ApiException:
        logging.debug("email not found: %s", email)
        return None


if __name__ == "__main__":
    sentry_sdk.init(
        os.environ.get("SENTRY_URL"),
        integrations=[FlaskIntegration()],
        traces_sample_rate=1.0,
    )
    ARG = parse_arguments()
    main(ARG)
