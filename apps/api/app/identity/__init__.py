"""Identity provisioning and Company administration for platform operators (ADR-008, ADR-010).

Used only by ``scripts/manage_identities.py`` with an identity-operator
database login. Nothing in the API imports this package and no HTTP route
reaches these functions. The API role only *reads* identities
(``app.auth.service``); its single identity-creating path is founder
self-registration through the ``heroos_register_company`` database function
(``app.companies.registration``), which can only create a new Company.
"""
