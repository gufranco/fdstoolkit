from __future__ import annotations

import base64

from pydantic import BaseModel

from fdstoolkit.build.blank import blank_image

OK = 200


BAD_REQUEST = 400


UNPROCESSABLE = 422


IMAGE = blank_image(sides=2, headered=False, formatted=True, game_name="SMB")


ENCODED = base64.b64encode(IMAGE).decode("ascii")


class Nothing(BaseModel):
    pass
