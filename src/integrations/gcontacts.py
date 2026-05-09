import logging

from .google_auth import build_google_service

logger = logging.getLogger(__name__)


class GContacts:
    def __init__(self):
        self._service = None

    def _svc(self):
        if self._service is None:
            self._service = build_google_service("people", "v1")
        return self._service

    def create_contact(self, name: str, email: str) -> str:
        """Create a Google Contact. Returns the resource name (e.g. 'people/c123')."""
        logger.info("Google Contacts: creating contact %r <%s>", name, email)
        result = self._svc().people().createContact(
            body={
                "names": [{"givenName": name}],
                "emailAddresses": [{"value": email, "type": "other"}],
            }
        ).execute()
        resource_name = result["resourceName"]
        logger.info("Google Contacts: created %s", resource_name)
        return resource_name

    def search_contacts(self, query: str) -> list[dict]:
        """Search Google Contacts by name or email. Returns list of {name, email}."""
        result = self._svc().people().searchContacts(
            query=query,
            readMask="names,emailAddresses",
        ).execute()
        contacts = []
        for r in result.get("results", []):
            person = r.get("person", {})
            names = person.get("names", [])
            emails = person.get("emailAddresses", [])
            if names and emails:
                display_name = names[0].get("displayName", "")
                email_val = emails[0].get("value", "")
                if display_name and email_val:
                    contacts.append({"name": display_name, "email": email_val})
        return contacts

    def delete_contact_by_email(self, email: str) -> bool:
        """Find and delete a Google Contact by email. Returns True if deleted."""
        logger.info("Google Contacts: looking up resource name for <%s>", email)
        resource_name = self._find_resource_name_by_email(email)
        if not resource_name:
            logger.warning("Google Contacts: no contact found for <%s>", email)
            return False
        logger.info("Google Contacts: deleting %s", resource_name)
        self._svc().people().deleteContact(resourceName=resource_name).execute()
        return True

    def list_contacts(self) -> list[dict]:
        """Fetch all Google Contacts (paginated). Returns list of {name, email}."""
        contacts = []
        next_page_token = None
        while True:
            kwargs = {
                "resourceName": "people/me",
                "pageSize": 200,
                "personFields": "names,emailAddresses",
            }
            if next_page_token:
                kwargs["pageToken"] = next_page_token
            result = self._svc().people().connections().list(**kwargs).execute()
            for person in result.get("connections", []):
                names = person.get("names", [])
                emails = person.get("emailAddresses", [])
                if names and emails:
                    display_name = names[0].get("displayName", "")
                    email_val = emails[0].get("value", "")
                    if display_name and email_val:
                        contacts.append({"name": display_name, "email": email_val})
            next_page_token = result.get("nextPageToken")
            if not next_page_token:
                break
        return contacts

    def _find_resource_name_by_email(self, email: str) -> str | None:
        """Walk connections pages to find the resource name for a given email."""
        next_page_token = None
        while True:
            kwargs = {
                "resourceName": "people/me",
                "pageSize": 200,
                "personFields": "emailAddresses",
            }
            if next_page_token:
                kwargs["pageToken"] = next_page_token
            result = self._svc().people().connections().list(**kwargs).execute()
            for person in result.get("connections", []):
                for ea in person.get("emailAddresses", []):
                    if ea.get("value", "").lower() == email.lower():
                        return person["resourceName"]
            next_page_token = result.get("nextPageToken")
            if not next_page_token:
                break
        return None


gcontacts = GContacts()
