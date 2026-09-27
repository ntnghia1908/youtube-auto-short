import pytest

from auto_short.web.urls import UrlError, parse_youtube_url

VID = "tHtxw6ykUmM"


@pytest.mark.parametrize("url", [
    f"https://youtu.be/{VID}?si=R1TwdI4gh0sPcVHB",
    f"https://youtu.be/{VID}",
    f"http://youtu.be/{VID}?t=42",
    f"youtu.be/{VID}",
    f"  https://www.youtube.com/watch?v={VID}&si=abc&t=10s  ",
    f"https://youtube.com/watch?v={VID}&list=PL123&index=2",
    f"https://m.youtube.com/watch?feature=share&v={VID}",
    f"https://www.youtube.com/shorts/{VID}?feature=share",
    f"HTTPS://WWW.YOUTUBE.COM/watch?v={VID}",
])
def test_valid_urls_normalise(url):
    assert parse_youtube_url(url) == (VID, f"https://youtu.be/{VID}")


@pytest.mark.parametrize("url", [
    "",
    "   ",
    "https://www.youtube.com/playlist?list=PL123",
    f"https://vimeo.com/{VID}",
    f"https://youtube.com.evil.example/watch?v={VID}",
    f"https://evil.example/?u=https://youtu.be/{VID}",
    "https://youtu.be/short",
    f"https://youtu.be/{VID}/extra",
    "https://www.youtube.com/watch?v=abc",
    f"https://www.youtube.com/watch?v={VID}&v=aaaaaaaaaaa",
    "https://www.youtube.com/channel/UC123",
    f"https://www.youtube.com/embed/{VID}",
    f"ftp://youtu.be/{VID}",
    f"javascript:alert(1)//youtu.be/{VID}",
    f"https://user:pw@youtu.be/{VID}",
    f"https://youtu.be:8443/{VID}",
    f"https://youtu.be/{VID} https://youtu.be/{VID}",
    "/home/user/video.mp4",
    "https://youtu.be/" + "a" * 3000,
])
def test_invalid_urls_rejected(url):
    with pytest.raises(UrlError):
        parse_youtube_url(url)
