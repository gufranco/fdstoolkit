from __future__ import annotations

from fdstoolkit.drive.recognition import ReadRate
from fdstoolkit.drive.sampling import CountedSpan, Recognition
from fdstoolkit.ui.reads_schemas import RateView


def test_a_rate_view_carries_every_figure_of_the_read() -> None:
    # Arrange
    found = ReadRate(
        side=1, read=2, recognition=Recognition(counted=400, unclassed=4, span=CountedSpan.WHOLE)
    )

    # Act
    view = RateView.of(found)

    # Assert
    assert view.model_dump() == {
        "side": 1,
        "read": 2,
        "rate": 0.99,
        "counted": 400,
        "unclassed": 4,
        "span": "over the whole read, since no block framed",
    }
