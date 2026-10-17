"""Tiny lxml.html replacement for Android (BeautifulSoup based).

Only the subset used by tieba_reply_stats.parse is implemented:
  * document_fromstring / fragment_fromstring / tostring
  * Element.xpath() with simple //tag[pred], .//tag[pred], /@attr
"""

from . import html  # noqa: F401
