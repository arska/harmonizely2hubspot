"""
Harmonizely.com meeting to HubSpot CRM
"""

import argparse
import datetime
import logging
import os
import pprint

import dotenv
import flask
import hubspot
import nameparser
import phonenumbers
import sentry_sdk
from hubspot.crm.associations import BatchInputPublicAssociation
from hubspot.crm.contacts import ApiException, SimplePublicObjectInput
from sentry_sdk.integrations.flask import FlaskIntegration

LOGFORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
CONFIG = {}  # will be loaded in main()
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
    config = {}
    config["token"] = os.environ.get("HUBSPOT_ACCESS_TOKEN")
    config["emails"] = os.environ.get("HUBSPOT_USERS").split(",")
    global CONFIG  # pylint: disable=global-statement
    CONFIG = config
    logging.info(
        "loaded HUBSPOT_ACCESS_TOKEN and HUBSPOT_USERS with emails: %s",
        CONFIG["emails"],
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


def search_or_create_contact(api_client, payload, first_name, last_name, owner):
    """
    contact searching, creation and updating
    """

    try:
        phone_number = [
            x.get("value", "")
            for x in payload["answers"]
            if "phone" in x.get("question_label", "").lower()
            or "telephon" in x.get("question_label", "").lower()
            or "telefon" in x.get("question_label", "").lower()
        ][0]
        if phone_number != "":
            phonenumberobj = phonenumbers.parse(phone_number, None)
            phone_number = phonenumbers.format_number(
                phonenumberobj, phonenumbers.PhoneNumberFormat.INTERNATIONAL
            )
    except IndexError:
        # phone number not supplied
        phone_number = ""
    except phonenumbers.phonenumberutil.NumberParseException:
        # number could not be parsed, e.g. because it is a
        # local number without country code
        # ignore since we don't have a country to match it to
        pass

    logging.debug("got phone_number: %s", phone_number)

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
                        "phone": phone_number,
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
    else:
        # contact found
        logging.info("contact found: %s", contact)

    # check if the hubspot contact has the lastname in the firstname field
    if contact.properties["lastname"] is None or (
        last_name != "" and contact.properties["firstname"].endswith(last_name)
    ):
        hubspot_update(
            api_client, contact, {"firstname": first_name, "lastname": last_name}
        )

    # check if the hubspot phone number should be updated
    if phone_number != "" and (
        contact.properties.get("phone", None) is None
        or (
            not contact.properties["phone"].startswith("+")
            and phone_number.startswith("+")
        )
    ):
        hubspot_update(api_client, contact, {"phone": phone_number})
    # check if the existing hubspot phone number needs formatting
    elif (
        contact.properties.get("phone", None) is not None
        and contact.properties["phone"] != ""
    ):
        try:
            phonenumberobj = phonenumbers.parse(contact.properties["phone"], None)
            formatted_phone_number = phonenumbers.format_number(
                phonenumberobj, phonenumbers.PhoneNumberFormat.INTERNATIONAL
            )
            if formatted_phone_number != contact.properties["phone"]:
                # the contacts phone number needs formatting
                hubspot_update(api_client, contact, {"phone": formatted_phone_number})
        except phonenumbers.phonenumberutil.NumberParseException:
            # number could not be parsed, e.g. because it is a
            # local number without country code
            # ignore since we don't have a country to match it to
            pass

    return contact


def hubspot_update(api_client, contact, properties):
    """
    hubspot contact update with "properties" diff
    """
    try:
        logging.info("Updating contact %s to %s", contact, properties)
        api_client.crm.contacts.basic_api.update(
            contact.id, SimplePublicObjectInput(properties=properties)
        )
    except ApiException as error:
        logging.error("Exception when updating contact: %s\n", error)
        flask.abort(500, description=error)


@APP.route("/<path>", methods=["GET", "POST"])
def webhook(path):
    """
    Process webhook POST from Harmonizely
    """

    if path not in CONFIG["emails"]:
        flask.abort(404, description="Resource not found")

    payload = flask.request.json
    logging.info("got new request with payload:\n%s", pprint.pformat(payload))

    if payload is None:
        flask.abort(400, description="no payload")

    first_name, last_name = parse_name(payload["invitee"]["full_name"])

    api_client = hubspot.HubSpot(access_token=CONFIG["token"])

    # get the Hubspot user id for the email address specified as the URL path
    owner = get_owner_id(email=path, api_client=api_client)

    contact = search_or_create_contact(
        api_client, payload, first_name, last_name, owner
    )

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
                "dealstage": 1159035,  # Deal stage "New" at VSHN
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
            # if the contact has a company associate the deal with it

            associate_company_to_deal(
                company_id=contact.associations["companies"].results[0].id,
                deal_id=newdeal.id,
                api_client=api_client,
            )

    # get meetings for contact
    # future: check if there is a meeting already
    # future: update/delete existing meeting
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

    try:
        meeting_title = [
            x.get("value", "")
            for x in payload["answers"]
            if "title" in x.get("question_label", "").lower()
            or "titel" in x.get("question_label", "").lower()
        ][0]
    except IndexError:
        meeting_title = ""

    try:
        meeting_comment = [
            x.get("value", "")
            for x in payload["answers"]
            if "kommentar" in x.get("question_label", "").lower()
            or "comment" in x.get("question_label", "").lower()
            or "agenda" in x.get("question_label", "").lower()
        ][0]
    except IndexError:
        meeting_comment = ""

    # create meeting
    try:
        # https://developers.hubspot.com/docs/api/crm/meetings
        properties = {
            "hs_timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "hubspot_owner_id": owner,
            "hs_meeting_title": payload["event_type"]["name"]
            + (": " + meeting_title if meeting_title else ""),
            "hs_meeting_body": "Harmonizely meeting location: "
            + str(payload["location"])
            + ("\n" + meeting_comment if meeting_comment else ""),
            "hs_internal_meeting_notes": "",
            "hs_meeting_external_url": str(payload["location"]),
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
        newdeal = find_first_non_closed_deal(
            api_client, contact.associations["deals"].results
        )

        # if the contact has a deal associate the meeting with it
        associate_deal_to_meeting(
            deal_id=newdeal.id, meeting_id=meeting.id, api_client=api_client
        )

    return "OK"


def find_first_non_closed_deal(api_client, deals):
    """
    Select the first non-closed deal from a list of deal associations
    """
    for deal_association in deals:
        try:
            deal = api_client.crm.deals.basic_api.get_by_id(deal_association.id)
            logging.debug(
                "deal %s found:\n%s", deal_association.id, pprint.pformat(deal)
            )
            if "closed" not in deal.properties["dealstage"]:
                return deal
        except ApiException:
            logging.debug("deal not found: %s", deal_association.id)
    # if we end here we didn't find a non-closed deal, so just take one
    return deals[0]


def parse_name(full_name):
    """
    Parse the assumed first and last names from the full name
    """
    # remove "Herr" and "Frau" from the name
    # https://github.com/derek73/python-nameparser/pull/99
    nameparser.config.CONSTANTS.titles.add("Herr", "Frau")

    # make an educated guess about the first and last name from full_name
    parsed_name = nameparser.HumanName(full_name)
    first_name = parsed_name.first.strip()
    if parsed_name.middle:
        first_name += " " + parsed_name.middle.strip()
    logging.debug("parsed first name: %s", first_name)
    last_name = parsed_name.last.strip()
    logging.debug("parsed last name: %s", last_name)
    return first_name, last_name


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


def sentry_healthcheck_sampling(context):
    """
    Sample healthcheck requests every second to / for
    sentry performance monitoring wayyy lower than the rest
    """
    if (
        context.get("wsgi_environ", False)
        and context["wsgi_environ"].get("REQUEST_URI", False)
        and context["wsgi_environ"]["REQUEST_URI"] == "/"
    ):
        # ignore calls to the healthcheck endpoint
        return 0.001
    # else sample 100%
    return 1


if __name__ == "__main__":
    sentry_sdk.init(
        os.environ.get("SENTRY_URL"),
        integrations=[FlaskIntegration()],
        traces_sampler=sentry_healthcheck_sampling,
    )
    ARG = parse_arguments()
    main(ARG)
