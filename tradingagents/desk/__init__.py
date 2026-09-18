"""The local trade desk: a personal page that never leaves this machine.

Everything else in this project is either a public page or a CLI. This is
neither. It shows a real brokerage balance and will eventually place orders,
so it is deliberately not part of the deployed site — there is no route to it
from agenttrust.kr and there never should be.

``localhost`` is not a security boundary on its own. Any page in any browser
tab can POST to 127.0.0.1; CORS stops the page reading the answer, not the
request arriving. So the desk checks three things on every call: the Host
header is a loopback name, the request carries the token printed at launch,
and it did not come cross-site. See ``guard``.
"""

from .app import DESK_TOKEN_HEADER, create_desk_app, new_token

__all__ = ["DESK_TOKEN_HEADER", "create_desk_app", "new_token"]
