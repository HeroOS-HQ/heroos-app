"""Case services (M2-NEW-07): domain operations over the Company-scoped repositories.

They read and write through ``app.repositories`` (flush, never commit: the
caller owns the transaction) and use the pure workflow domain
(``app.workflows``). Both the HTTP routes and Ask HeroOS persistence
(``app.conversations``) call them, so a Case changes the same way whoever asks.
"""
