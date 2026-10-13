"""Identity provisioning for platform operators (ADR-008).

Used only by ``scripts/manage_identities.py`` with an identity-operator
database login. Nothing in the API imports this package: the API role can only
*read* identities (``app.auth.service``), and no HTTP route reaches these
functions.
"""
