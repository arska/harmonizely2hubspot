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
from hubspot.crm.associations import BatchInputPublicAssociation
from hubspot.crm.contacts import ApiException, SimplePublicObjectInput
from werkzeug.exceptions import abort

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
        logging.basicConfig(format=LOGFORMAT)

    logging.debug("starting with arguments %s", args)
    dotenv.load_dotenv()
    global CONFIG
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
        "-n",
        "--noop",
        help="dont actually post/change anything,"
        " just log what would have been posted",
        action="store_true",
        default=False,
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

    """
    # example payload:
    payload = b'{"rescheduling":null,"pretty_canceled_at":null,"pretty_scheduled_at":"Thursday, February 10, 2022 14:00","pretty_scheduled_at_in_invitee_timezone":"Thursday, February 10, 2022 at 2:00 PM","pretty_canceled_at_in_invitee_timezone":null,"event_type":{"name":"APPUiO & Exoscale","location":null,"location_label":null,"description":null,"duration":45,"slug":"exo","is_secret":false,"confirmation_page_type":"internal","confirmation_page_url":null,"notification_type":"calendar","pass_details_to_redirected_page":false,"type":"regular","position":0},"scheduled_at":"2022-02-10T13:00:00+00:00","end_date":"2022-02-10T13:45:00+00:00","invitee":{"first_name":"Aarno","email":"aarno.aukia+test1@vshn.ch","full_name":"Aarno Aukia","timezone":"Europe/Zurich","phone_number":"+41445455300","locale":"en"},"state":"new","canceled_at":null,"uuid":"12345678-1234-1234-1234-12345678","notes":null,"details":null,"answers":[],"location":"https://vshn.zoom.us/j/1234567890","cancellation":null,"payment":null}'
    payload = json.loads(payload)
    """
    payload = flask.request.json
    logging.debug("got new request with payload: %s", pprint.pformat(payload))

    # make an educated guess about the first and last name from full_name
    parsed_name = nameparser.HumanName(payload["invitee"]["full_name"])
    first_name = parsed_name.first.strip()
    if parsed_name.middle:
        first_name += " " + parsed_name.middle.strip()
    logging.debug("parsed first name: %s", first_name)
    last_name = parsed_name.last.strip()
    logging.debug("parsed last name: %s", last_name)

    api_client = hubspot.HubSpot(access_token=CONFIG[path])

    try:
        owners = api_client.crm.owners.get_all()
        owner = [o.id for o in owners if o.email == path][0]
    except hubspot.crm.owners.exceptions.ApiException as error:
        logging.error("loading owner ID failed, problem with API key?")
        flask.abort(500, description=error)

    def search_contact(email):
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
            logging.debug("email %s found: %s", email, pprint.pformat(contact))
            return contact
        except ApiException:
            logging.debug("email not found: %s", email)
            return None

    contact = search_contact(payload["invitee"]["email"])

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
            contact = search_contact(payload["invitee"]["email"])
        except ApiException as error:
            logging.error("Exception when creating contact: %s\n", error)
            abort(500, description=error)

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
                "dealstage": "1159035",
                """
Valid options are: [1159033, 1159034, 1159035, appointmentscheduled, decisionmakerboughtin, contractsent, closedwon, closedlost] (note that the ID "appointmentscheduled" refers to state "design solution")
"""
                "hubspot_owner_id": owner,
                "pipeline": "default",
            }
            newdeal = api_client.crm.deals.basic_api.create(
                simple_public_object_input=SimplePublicObjectInput(
                    properties=properties
                )
            )
            logging.debug("created deal: %s", pprint.pformat(newdeal))
        except ApiException as error:
            logging.error("Exception when creating deal: %s\n", error)
            abort(500, description=error)

        # add new deal to contact
        try:
            association = api_client.crm.associations.batch_api.create(
                from_object_type="Contact",
                to_object_type="Deal",
                batch_input_public_association=BatchInputPublicAssociation(
                    inputs=[
                        {
                            "from": {"id": contact.id},
                            "to": {"id": newdeal.id},
                            "type": "contact_to_deal",
                        }
                    ]
                ),
            )
            logging.debug(
                "associate deal with contact: %s", pprint.pformat(association)
            )
        except ApiException as error:
            logging.error("Exception when associate deal with contact: %s\n", error)
            abort(500, description=error)

        if contact.associations and contact.associations.get("companies", False):
            # if the contact has a company associate the meeting with it
            logging.debug("adding deal to company association")
            try:
                association = api_client.crm.associations.batch_api.create(
                    from_object_type="Companies",
                    to_object_type="Deal",
                    batch_input_public_association=BatchInputPublicAssociation(
                        inputs=[
                            {
                                "from": {
                                    "id": contact.associations["companies"]
                                    .results[0]
                                    .id
                                },
                                "to": {"id": newdeal.id},
                                "type": "company_to_deal",
                            }
                        ]
                    ),
                )
                logging.debug(
                    "associate deal with company: %s", pprint.pformat(association)
                )
            except ApiException as error:
                logging.error("Exception when associate deal with company: %s\n", error)
                abort(500, description=error)

    # get meetings for contact
    """ batch_input_public_object_id = BatchInputPublicObjectId(inputs=[{"id":contact.id}])
    try:
        api_response = api_client.crm.associations.batch_api.read(from_object_type="Contacts", to_object_type="Meetings", batch_input_public_object_id=batch_input_public_object_id)
        logging.debug(pprint.pformat(api_response))
    except ApiException as error:
        logging.debug("Exception when calling batch_api->read: %s\n", error)
    """

    # create meeting
    try:
        # https://developers.hubspot.com/docs/api/crm/meetings
        meeting_properties = {
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
            simple_public_object_input=SimplePublicObjectInput(
                properties=meeting_properties
            ),
        )
        logging.debug("new meeting: %s", pprint.pformat(meeting))
    except ApiException as error:
        logging.error("Exception when creating meeting: %s\n", error)
        abort(500, description=error)

    # associate new meeting with the contact
    try:
        association = api_client.crm.associations.batch_api.create(
            from_object_type="Contact",
            to_object_type="Meeting",
            batch_input_public_association=BatchInputPublicAssociation(
                inputs=[
                    {
                        "from": {"id": contact.id},
                        "to": {"id": meeting.id},
                        "type": "contact_to_meeting_event",
                    }
                ]
            ),
        )
        logging.debug("associate meeting with contact: %s", pprint.pformat(association))
    except ApiException as error:
        logging.error("Exception when associate meeting with contact: %s\n", error)
        abort(500, description=error)

    if contact.associations and contact.associations.get("companies", False):
        # if the contact has a company associate the meeting with it
        logging.debug("adding company association")
        try:
            association = api_client.crm.associations.batch_api.create(
                from_object_type="Companies",
                to_object_type="Meeting",
                batch_input_public_association=BatchInputPublicAssociation(
                    inputs=[
                        {
                            "from": {
                                "id": contact.associations["companies"].results[0].id
                            },
                            "to": {"id": meeting.id},
                            "type": "company_to_meeting_event",
                        }
                    ]
                ),
            )
            logging.debug(
                "associate meeting with company: %s", pprint.pformat(association)
            )
        except ApiException as error:
            logging.error("Exception when associate meeting with company: %s\n", error)
            abort(500, description=error)

    #  either the contact has existing deals or we just created one above
    if contact.associations and contact.associations.get("deals", False):
        newdeal = contact.associations["deals"].results[0]

    # if the contact has a company associate the meeting with it
    logging.debug("adding deal association")
    try:
        association = api_client.crm.associations.batch_api.create(
            from_object_type="Deals",
            to_object_type="Meeting",
            batch_input_public_association=BatchInputPublicAssociation(
                inputs=[
                    {
                        "from": {"id": newdeal.id},
                        "to": {"id": meeting.id},
                        "type": "deal_to_meeting_event",
                    }
                ]
            ),
        )
        logging.debug("associate meeting with deal: %s", pprint.pformat(association))
    except ApiException as error:
        logging.error("Exception when associate meeting with deal: %s\n", error)
        abort(500, description=error)

    return "OK"


if __name__ == "__main__":
    sentry_sdk.init()
    ARG = parse_arguments()
    main(ARG)
