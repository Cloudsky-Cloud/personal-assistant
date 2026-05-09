import logging

from .google_auth import build_google_service, get_credentials

logger = logging.getLogger(__name__)

CONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts"
_PERSON_FIELDS = (
    "names,emailAddresses,phoneNumbers,addresses,organizations,biographies,birthdays"
)


def _parse_birthday(value: str) -> dict | None:
    """Parse 'YYYY-MM-DD' or 'MM-DD' into a People API date dict."""
    try:
        parts = value.strip().split("-")
        if len(parts) == 3:
            return {"year": int(parts[0]), "month": int(parts[1]), "day": int(parts[2])}
        if len(parts) == 2:
            return {"month": int(parts[0]), "day": int(parts[1])}
    except (ValueError, IndexError):
        pass
    return None


def _person_to_dict(person: dict) -> dict | None:
    """Convert a People API person resource to a flat contact dict."""
    names = person.get("names", [])
    emails = person.get("emailAddresses", [])
    if not names or not emails:
        return None
    name = names[0].get("displayName", "").strip()
    email = emails[0].get("value", "").strip()
    if not name or not email:
        return None

    contact: dict = {"name": name, "email": email}

    for phone in person.get("phoneNumbers", []):
        ptype = phone.get("canonicalForm") or phone.get("type", "")
        val = phone.get("value", "").strip()
        if not val:
            continue
        ptype = ptype.lower()
        if ptype == "mobile" and "phone_mobile" not in contact:
            contact["phone_mobile"] = val
        elif ptype == "work" and "phone_work" not in contact:
            contact["phone_work"] = val
        elif ptype == "home" and "phone_home" not in contact:
            contact["phone_home"] = val
        elif "phone_mobile" not in contact:
            contact["phone_mobile"] = val

    addrs = person.get("addresses", [])
    if addrs:
        a = addrs[0]
        if a.get("streetAddress"):
            contact["address_street"] = a["streetAddress"]
        if a.get("city"):
            contact["address_city"] = a["city"]
        if a.get("country"):
            contact["address_country"] = a["country"]

    orgs = person.get("organizations", [])
    if orgs and orgs[0].get("name"):
        contact["company"] = orgs[0]["name"]

    bios = person.get("biographies", [])
    if bios and bios[0].get("value"):
        contact["notes"] = bios[0]["value"]

    birthdays = person.get("birthdays", [])
    if birthdays:
        d = birthdays[0].get("date", {})
        if d.get("year") and d.get("month") and d.get("day"):
            contact["birthday"] = f"{d['year']:04d}-{d['month']:02d}-{d['day']:02d}"
        elif d.get("month") and d.get("day"):
            contact["birthday"] = f"{d['month']:02d}-{d['day']:02d}"

    return contact


class GContacts:
    def __init__(self):
        self._service = None

    def _svc(self):
        if self._service is None:
            logger.info("Google Contacts: building People API service")
            try:
                creds = get_credentials()
            except RuntimeError as exc:
                logger.error("Google Contacts: credential error — %s", exc)
                raise

            granted = set(creds.scopes or [])
            logger.info("Google Contacts: token scopes = %s", sorted(granted))
            if granted and CONTACTS_SCOPE not in granted:
                logger.error(
                    "Google Contacts: TOKEN IS MISSING SCOPE %s — "
                    "delete data/google_token.json and re-run: "
                    "docker-compose run --rm bot python setup_auth.py",
                    CONTACTS_SCOPE,
                )

            self._service = build_google_service("people", "v1")
            logger.info("Google Contacts: People API service ready")
        return self._service

    # ── Write ─────────────────────────────────────────────────────────────────

    def create_contact(self, name: str, email: str, **kwargs) -> str:
        """Create a Google Contact with optional extended fields."""
        body: dict = {
            "names": [{"givenName": name}],
            "emailAddresses": [{"value": email, "type": "other"}],
        }

        phones = []
        for ptype in ("mobile", "work", "home"):
            val = kwargs.get(f"phone_{ptype}")
            if val:
                phones.append({"value": val, "type": ptype})
        if phones:
            body["phoneNumbers"] = phones

        street = kwargs.get("address_street")
        city = kwargs.get("address_city")
        country = kwargs.get("address_country")
        if any([street, city, country]):
            body["addresses"] = [{
                "streetAddress": street or "",
                "city": city or "",
                "country": country or "",
                "type": "home",
            }]

        if kwargs.get("company"):
            body["organizations"] = [{"name": kwargs["company"], "type": "work"}]

        if kwargs.get("notes"):
            body["biographies"] = [{"value": kwargs["notes"], "contentType": "TEXT_PLAIN"}]

        if kwargs.get("birthday"):
            parsed = _parse_birthday(kwargs["birthday"])
            if parsed:
                body["birthdays"] = [{"date": parsed}]

        logger.info(
            "Google Contacts: creating contact name=%r email=%s fields=%s",
            name, email, list(body.keys()),
        )
        try:
            result = self._svc().people().createContact(body=body).execute()
        except Exception as exc:
            logger.error(
                "Google Contacts: createContact API call failed for %r <%s>: %s",
                name, email, exc,
            )
            raise

        resource_name = result["resourceName"]
        logger.info("Google Contacts: created %s for %r", resource_name, name)
        return resource_name

    def delete_contact_by_email(self, email: str) -> bool:
        """Find and delete a Google Contact by email. Returns True if deleted."""
        logger.info("Google Contacts: looking up resource name for <%s>", email)
        resource_name = self._find_resource_name_by_email(email)
        if not resource_name:
            logger.warning("Google Contacts: no contact found for <%s>", email)
            return False
        logger.info("Google Contacts: deleting %s", resource_name)
        try:
            self._svc().people().deleteContact(resourceName=resource_name).execute()
        except Exception as exc:
            logger.error(
                "Google Contacts: deleteContact failed for %s <%s>: %s",
                resource_name, email, exc,
            )
            raise
        logger.info("Google Contacts: deleted %s", resource_name)
        return True

    # ── Read ──────────────────────────────────────────────────────────────────

    def search_contacts(self, query: str) -> list[dict]:
        """Search Google Contacts by name or email. Returns list of contact dicts."""
        logger.info("Google Contacts: searching for %r", query)
        try:
            result = self._svc().people().searchContacts(
                query=query,
                readMask=_PERSON_FIELDS,
            ).execute()
        except Exception as exc:
            logger.error("Google Contacts: searchContacts API call failed: %s", exc)
            raise

        raw = result.get("results", [])
        logger.info("Google Contacts: search returned %d raw results", len(raw))
        contacts = []
        for r in raw:
            contact = _person_to_dict(r.get("person", {}))
            if contact:
                contacts.append(contact)
        logger.info("Google Contacts: parsed %d contacts from search", len(contacts))
        return contacts

    def list_contacts(self) -> list[dict]:
        """Fetch all Google Contacts (paginated). Returns list of contact dicts."""
        logger.info("Google Contacts: listing all contacts")
        contacts = []
        next_page_token = None
        page = 0
        while True:
            page += 1
            kwargs: dict = {
                "resourceName": "people/me",
                "pageSize": 200,
                "personFields": _PERSON_FIELDS,
            }
            if next_page_token:
                kwargs["pageToken"] = next_page_token
            try:
                result = self._svc().people().connections().list(**kwargs).execute()
            except Exception as exc:
                logger.error(
                    "Google Contacts: connections.list failed on page %d: %s", page, exc
                )
                raise

            connections = result.get("connections", [])
            logger.info("Google Contacts: page %d — %d connections", page, len(connections))
            for person in connections:
                contact = _person_to_dict(person)
                if contact:
                    contacts.append(contact)

            next_page_token = result.get("nextPageToken")
            if not next_page_token:
                break

        logger.info("Google Contacts: listed %d contacts total", len(contacts))
        return contacts

    # ── Internal ──────────────────────────────────────────────────────────────

    def _find_resource_name_by_email(self, email: str) -> str | None:
        """Walk connections pages to find the resource name for a given email."""
        next_page_token = None
        page = 0
        while True:
            page += 1
            kwargs: dict = {
                "resourceName": "people/me",
                "pageSize": 200,
                "personFields": "emailAddresses",
            }
            if next_page_token:
                kwargs["pageToken"] = next_page_token
            result = self._svc().people().connections().list(**kwargs).execute()
            logger.debug(
                "Google Contacts: _find page %d — %d connections",
                page, len(result.get("connections", [])),
            )
            for person in result.get("connections", []):
                for ea in person.get("emailAddresses", []):
                    if ea.get("value", "").lower() == email.lower():
                        return person["resourceName"]
            next_page_token = result.get("nextPageToken")
            if not next_page_token:
                break
        return None


gcontacts = GContacts()
